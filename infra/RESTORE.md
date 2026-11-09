# Recuperação de desastre

Os backups ficam no Object Storage e na própria VM:

| Onde | O quê | Retenção |
|---|---|---|
| Object Storage (bucket `S3_BUCKET`, pasta `<projeto>/`) | Litestream: replicação contínua, com atraso máximo de `LITESTREAM_SYNC_INTERVAL` | 7 dias de point-in-time |
| `/var/backups/sqlite/<projeto>/AAAA-MM-DD.db` na VM | Snapshot diário (04:00 UTC) | 7 dias |
| `/var/backups/sqlite/<projeto>/pre-deploy-<sha>.db` na VM | Cópia antes de cada deploy de uma app com backend (hoje, o imago e o ethos), antes da migração do commit `<sha>` | 7 dias (apagada pelo snapshot diário) |

## Restaurar um banco na mesma VM

```bash
sudo systemctl stop app-<projeto>          # o backend não pode estar escrevendo
sudo systemctl stop litestream
sudo mv /var/lib/sqlite/<projeto>/app.db{,.quebrado}
sudo rm -f /var/lib/sqlite/<projeto>/app.db-{wal,shm}

# opção A: último estado do Object Storage
sudo bash -c 'set -a; . /etc/default/litestream; set +a; litestream restore -config /etc/litestream.yml /var/lib/sqlite/<projeto>/app.db'
# opção B: um ponto no tempo
sudo bash -c 'set -a; . /etc/default/litestream; set +a; litestream restore -config /etc/litestream.yml -timestamp 2026-10-17T12:00:00Z /var/lib/sqlite/<projeto>/app.db'
# opção C: snapshot local
sudo cp /var/backups/sqlite/<projeto>/2026-10-17.db /var/lib/sqlite/<projeto>/app.db

sudo chown app-<projeto>:app-<projeto> /var/lib/sqlite/<projeto>/app.db
sudo -u app-<projeto> sqlite3 /var/lib/sqlite/<projeto>/app.db 'PRAGMA integrity_check; PRAGMA journal_mode=WAL;'
sudo systemctl start litestream app-<projeto>
```

Para o imago e para uma app com backend em `apps/` (hoje, o ethos), siga a seção abaixo: ela tem passos a mais.

## Restaurar o banco do imago ou de uma aplicação

O backup traz de volta as contas apagadas depois dele. Toda exclusão de conta passa pelo imago, a conta única ([imago-plan.md](../imago-plan.md), "exclusão de conta"), que grava no journald da unit `app-imago` só o id da conta (`conta <id> excluída`). Depois de restaurar **qualquer** banco, o do imago ou o de uma aplicação, o `reapply-deletions` do imago lê essas linhas e refaz as exclusões no imago e em cada aplicação do `IMAGO_APPS` (pelo `POST /internal/users/{id}/delete` de cada uma), sem mandar email, **antes** de as aplicações abrirem de novo. A conta que já não existe no imago também sai das aplicações (é o caso de um banco de aplicação restaurado), e ele pode rodar quantas vezes quiser: a exclusão é idempotente no imago e em cada aplicação. Detalhes em [apps/imago/README.md](../apps/imago/README.md).

As exclusões feitas no ethos antes da passagem do login dele para o imago (ETH-64) não estão no journal do `app-imago`: estão no do `app-ethos` (`app.auth.deletion: conta <id> excluída`). Elas só importam se o backup do ethos for de antes da passagem, e então o `reapply-deletions` do próprio ethos as refaz (passo 4).

**Restaurar o imago perde as contas criadas depois do ponto restaurado.** Quem tinha uma delas entra de novo como conta nova, com outro id (os ids são aleatórios e um id perdido não volta a ser sorteado), e os dados dela nas aplicações ficam órfãos: ninguém os vê, mas continuam nos bancos das aplicações até serem religados à conta nova ou apagados à mão, pelo id antigo. Se o banco quebrado ainda abre, os ids dessas contas estão nele (passo 2).

Os comandos do CLI rodam como o usuário de cada serviço, com o ambiente da unit, pelo `systemd-run`: os `EnvironmentFile=` são `0600` do root, então `sudo -u app-<nome>` não basta. Defina uma vez no shell:

```bash
imago_cli=(sudo systemd-run --quiet --pipe --wait --collect --uid=app-imago --gid=app-imago
  --working-directory=/opt/apps/imago
  -p EnvironmentFile=/etc/infra/smtp.env -p EnvironmentFile=/etc/infra/internal/imago.env
  -p EnvironmentFile=/etc/infra/apps/imago.env
  -E PYTHONDONTWRITEBYTECODE=1)
ethos_cli=(sudo systemd-run --quiet --pipe --wait --collect --uid=app-ethos --gid=app-ethos
  --working-directory=/opt/apps/ethos
  -p EnvironmentFile=/etc/infra/internal/ethos.env -p EnvironmentFile=/etc/infra/apps/ethos.env
  -E PYTHONDONTWRITEBYTECODE=1)
```

Nos passos abaixo, `<banco>` é o banco restaurado (`imago` ou `ethos`).

**0. Antes de parar o serviço**

```bash
# Escolha o backup: o pre-deploy-<sha>.db de um deploy, um snapshot diário ou o Litestream
sudo ls -lt /var/backups/sqlite/<banco>/
# O journal do app-imago precisa ser mais antigo que o backup: senão, exclusões feitas entre o backup
# e a primeira linha do journal não voltam a ser aplicadas (o journald guarda até 100M)
sudo journalctl -u app-imago -o short-iso --no-pager | head -n 1
# As exclusões que o reapply-deletions vai ler
sudo journalctl -u app-imago -o cat --no-pager | grep -cE 'conta [0-9]+ excluída'
```

Se o problema foi uma **migração que estragou os dados**, o `pre-deploy-<sha>.db` é o do deploy que a aplicou, e o código também precisa voltar (o código novo rodaria a migração de novo na subida). Antes de tudo:

1. Garanta que a `main` não vai publicar a migração quebrada de novo (corrija ou reverta antes do próximo push).
2. Faça o rollback: Actions → o workflow da aplicação (Imago ou Ethos) → Run workflow com o commit publicado antes de `<sha>`. O serviço sobe com o código antigo, ainda no banco estragado (o deploy leva junto os arquivos de migração que o banco já tem).
3. Siga os passos abaixo com a opção A, **pulando** o `alembic upgrade head` do passo 3 (ele aplicaria a migração quebrada de novo). O `reapply-deletions` roda com o código antigo, que bate com o banco restaurado.
4. Nunca suba o `app-<banco>` com `systemctl start`: a subida rodaria a migração quebrada. No lugar dele, rode o mesmo rollback de novo (agora o banco está na revisão antiga, o deploy tira os arquivos da migração quebrada e a subida não migra nada): no ethos, logo antes do passo 4, que precisa dele no ar (o health check do deploy não passa pelo imago); no imago, no passo 5, depois de subir o `litestream` e os timers.

**1. Fechar as aplicações e parar tudo que escreve no banco**

```bash
# Sem o imago, o nginx responde 500 na API de todas as aplicações (menos o /health) e ninguém entra:
# é assim que elas ficam fechadas até o passo 5
sudo systemctl stop imago-cleanup.timer imago-cleanup.service app-imago
# Se o banco é o do ethos, o serviço e os alertas dele também
sudo systemctl stop ethos-alerts.timer ethos-alerts.service app-ethos
sudo systemctl stop litestream
```

**2. Pôr o backup no lugar**

```bash
sudo mv /var/lib/sqlite/<banco>/app.db{,.quebrado}
sudo rm -f /var/lib/sqlite/<banco>/app.db-{wal,shm}

# opção A: cópia de antes de um deploy
sudo cp /var/backups/sqlite/<banco>/pre-deploy-<sha>.db /var/lib/sqlite/<banco>/app.db
# opção B: snapshot local
sudo cp /var/backups/sqlite/<banco>/2026-10-17.db /var/lib/sqlite/<banco>/app.db
# opção C: Litestream (último estado ou, com -timestamp, um ponto no tempo)
sudo bash -c 'set -a; . /etc/default/litestream; set +a; litestream restore -config /etc/litestream.yml /var/lib/sqlite/<banco>/app.db'

sudo chown app-<banco>:app-<banco> /var/lib/sqlite/<banco>/app.db
sudo -u app-<banco> sqlite3 /var/lib/sqlite/<banco>/app.db 'PRAGMA integrity_check; PRAGMA journal_mode=WAL;'   # ok e wal
sudo -u app-<banco> sqlite3 /var/lib/sqlite/<banco>/app.db 'PRAGMA foreign_key_check;'                         # nada
sudo -u app-<banco> sqlite3 /var/lib/sqlite/<banco>/app.db 'SELECT version_num FROM alembic_version;'          # revisão do backup
```

Se o banco é o do imago, anote as contas que o backup perdeu (as criadas depois dele), se o banco quebrado ainda abre: os dados delas nas aplicações ficam órfãos, com esses ids.

```bash
sudo -u app-imago sqlite3 -cmd "ATTACH '/var/lib/sqlite/imago/app.db' AS restaurado" \
  /var/lib/sqlite/imago/app.db.quebrado \
  'SELECT id, created_at FROM main.users WHERE id NOT IN (SELECT id FROM restaurado.users);'
```

**3. Migrar o banco restaurado, com o serviço ainda parado**

```bash
# O banco na revisão do código instalado (o backup pode ser de antes da última migração)
"${imago_cli[@]}" /opt/apps/imago/.venv/bin/alembic upgrade head    # se o banco é o do imago
"${ethos_cli[@]}" /opt/apps/ethos/.venv/bin/alembic upgrade head    # se o banco é o do ethos
```

**4. Reaplicar as exclusões, com as aplicações ainda fechadas**

O imago chama a API interna de cada aplicação direto em `127.0.0.1`: elas precisam estar no ar, mas continuam fechadas para fora enquanto o `app-imago` está parado.

```bash
# Se o banco restaurado é o do ethos (as aplicações que não foram paradas já estão no ar)
sudo systemctl start app-ethos
# Lê as linhas do journal pelo stdin; as outras linhas são ignoradas. Refaz as exclusões no imago e
# em cada aplicação do IMAGO_APPS, sem email
sudo journalctl -u app-imago -o cat --no-pager \
  | "${imago_cli[@]}" /opt/apps/imago/.venv/bin/python -m app.cli reapply-deletions
# Uma aplicação que falhou fica com a tarefa de exclusão pendente: leve-a agora, sem esperar o timer
"${imago_cli[@]}" /opt/apps/imago/.venv/bin/python -m app.cli run-tasks
```

A saída diz quantas linhas leu e o que fez com as contas (o formato está no [apps/imago/README.md](../apps/imago/README.md)). Se ele sair com erro (linha fora do formato, entrada vazia), confira o `-o cat` e o `sudo` do `journalctl` e rode de novo. Se o `run-tasks` contar falhas, a aplicação daquela tarefa não respondeu: confira o `journalctl -u app-<aplicação>` e rode o `run-tasks` de novo, até não sobrar falha, antes do passo 5.

Se o banco restaurado é o do ethos e o backup é de antes da passagem do login para o imago, refaça também as exclusões que o ethos fez sozinho, com o `reapply-deletions` dele, que lê o journal do `app-ethos` (detalhes em [apps/ethos/README.md](../apps/ethos/README.md#comandos-de-operação-cli)):

```bash
sudo journalctl -u app-ethos -o cat --no-pager \
  | "${ethos_cli[@]}" /opt/apps/ethos/.venv/bin/python -m app.cli reapply-deletions
```

**5. Abrir e conferir**

```bash
sudo systemctl start litestream app-imago imago-cleanup.timer ethos-alerts.timer
systemctl is-active app-imago app-ethos litestream imago-cleanup.timer ethos-alerts.timer   # active (5x)
curl -fsS http://127.0.0.1:3003/health                                      # {"status":"ok"}
curl -fsS https://manasomali.com/api/imago/health                           # {"status":"ok"}
curl -fsS https://manasomali.com/api/ethos/health                           # {"status":"ok"}
sudo journalctl -u app-imago -u app-<banco> -n 20 --no-pager                # sem erro na subida
```

Depois, rode o **Verificar backups** (Actions → Verificar backups → Run workflow): o Litestream começa uma geração nova a partir do banco restaurado. Quando tudo estiver certo, apague o `app.db.quebrado`, que ainda tem os dados das contas apagadas (a política de privacidade promete que eles somem dos backups em até 8 dias): `sudo rm /var/lib/sqlite/<banco>/app.db.quebrado`.

## Ensaiar o restore sem parar o serviço

Numa cópia, nunca no `app.db` em uso. Os serviços continuam no ar o tempo todo. O `DATABASE_PATH` da cópia vai pelo `env`, depois do `systemd-run`: um `-E DATABASE_PATH=...` perderia para o `EnvironmentFile=` e o comando rodaria no banco de produção. No imago, o `IMAGO_APPS` vazio faz o `reapply-deletions` mexer só na cópia, sem chamar as aplicações de produção.

```bash
ensaio=$(sudo -u app-imago mktemp -d /var/tmp/imago-ensaio.XXXXXX)
sudo -u app-imago cp /var/backups/sqlite/imago/pre-deploy-<sha>.db "$ensaio/app.db"
sudo -u app-imago sqlite3 "$ensaio/app.db" 'PRAGMA integrity_check;'      # ok
sudo journalctl -u app-imago -o cat --no-pager | grep -E 'conta [0-9]+ excluída'   # ids a reaplicar
copia=(/usr/bin/env DATABASE_PATH="$ensaio/app.db" IMAGO_APPS=)
"${imago_cli[@]}" "${copia[@]}" /opt/apps/imago/.venv/bin/alembic upgrade head
sudo journalctl -u app-imago -o cat --no-pager \
  | "${imago_cli[@]}" "${copia[@]}" /opt/apps/imago/.venv/bin/python -m app.cli reapply-deletions
# De novo: 0 contas apagadas
sudo journalctl -u app-imago -o cat --no-pager \
  | "${imago_cli[@]}" "${copia[@]}" /opt/apps/imago/.venv/bin/python -m app.cli reapply-deletions
curl -fsS https://manasomali.com/api/imago/health                          # 200 durante todo o ensaio
sudo rm -rf "$ensaio"
```

O ensaio das exclusões de antes da passagem, numa cópia do banco do ethos, é o mesmo com `app-ethos`, o `ethos_cli`, `/usr/bin/env DATABASE_PATH="$ensaio/app.db"` e o journal do `app-ethos` (`grep 'app.auth.deletion: conta'`).

## VM perdida

1. Criar uma VM nova (Ubuntu 24.04 ou mais novo, x86_64) e apontar o DNS para o IP novo.
2. Atualizar os secrets `REMOTE_HOST` e `SSH_KNOWN_HOSTS` (`ssh-keyscan <ip>`) no GitHub.
3. Reemitir o certificado **antes** do workflow, porque a config versionada do Nginx aponta para os arquivos do Let's Encrypt e o `nginx -t` falha sem eles:
   `sudo apt install -y nginx && sudo snap install --classic certbot && sudo certbot --nginx -d manasomali.com -d www.manasomali.com`
4. Rodar o workflow **Infra** manualmente (Actions → Infra → Run workflow). Ele cria usuários, pastas e bancos **vazios** e gera os tokens da API interna de novo (os da VM antiga se perderam com ela; o imago e as aplicações leem os novos). O smoke test avisa que a API das aplicações depende de um imago ainda não publicado.
5. Para cada projeto, seguir "Restaurar um banco na mesma VM" (opção A). Antes do primeiro deploy a unit `app-<projeto>` não sobe (não há `.venv`), então o `systemctl start` dela não faz nada.
6. Rodar o workflow **Publish Website** e os deploys dos backends, o do imago primeiro (a API das aplicações pergunta a ele quem é o usuário): Actions → Imago → Run workflow e depois Actions → Ethos → Run workflow, com o SHA do último commit da `main`; a subida aplica as migrações que faltarem.
7. O journal da VM antiga se perdeu com ela: as exclusões de conta feitas entre o último envio do Litestream (até `LITESTREAM_SYNC_INTERVAL`) e a perda da VM não têm como ser reaplicadas (risco aceito no plano). Se o disco antigo ainda puder ser lido, as linhas saem com `journalctl -D <pasta do journal antigo> -u app-imago -o cat > exclusoes.log`. Como o CLI só existe na VM depois do deploy do passo 6 (é ele que cria a `.venv`), reaplique logo depois dele: os passos 1, 4 (com `< exclusoes.log` no lugar do `journalctl`) e 5 de "Restaurar o banco do imago ou de uma aplicação".

## Testar a restauração

O workflow **Verificar backups** faz isso toda segunda. Para rodar na hora: Actions → Verificar backups → Run workflow. Para cada banco do `databases.txt` (o imago e o ethos inclusive), o `restore-test.sh` restaura do Object Storage numa pasta temporária, confere o `integrity_check` e o número de objetos do schema contra o banco vivo e exige um snapshot diário (`AAAA-MM-DD.db`) das últimas 26h; um `pre-deploy-<sha>.db` recente não conta. O CI de cada aplicação (`packages/deploy/test-vm.sh`) roda o `restore-test.sh` com o banco dela e um Litestream falso. No do ethos, o banco está populado, e antes o `apps/ethos/backend/tests/vm-restore.sh` ensaia o passo a passo de "Restaurar o banco de uma app" com o `reapply-deletions`.
