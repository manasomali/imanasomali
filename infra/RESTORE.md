# Recuperação de desastre

Os backups ficam no Object Storage e na própria VM:

| Onde | O quê | Retenção |
|---|---|---|
| Object Storage (bucket `S3_BUCKET`, pasta `<projeto>/`) | Litestream: replicação contínua, com atraso máximo de `LITESTREAM_SYNC_INTERVAL` | 7 dias de point-in-time |
| `/var/backups/sqlite/<projeto>/AAAA-MM-DD.db` na VM | Snapshot diário (04:00 UTC) | 7 dias |
| `/var/backups/sqlite/<projeto>/pre-deploy-<sha>.db` na VM | Cópia antes de cada deploy de uma app com backend (hoje, o ethos), antes da migração do commit `<sha>` | 7 dias (apagada pelo snapshot diário) |

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

Para uma app com backend em `apps/` (hoje, o ethos), siga a seção abaixo: ela tem passos a mais.

## Restaurar o banco de uma app (ethos)

O backup traz de volta as contas apagadas depois dele. Cada exclusão de conta grava no journald da unit `app-ethos` só o id (`INFO app.auth.deletion: conta 42 excluída`), e o `reapply-deletions` apaga essas contas de novo **antes** de o app voltar ao ar. Ele não manda email nem grava um `account_deleted` repetido, ignora conta que não existe e pode rodar quantas vezes quiser. Detalhes em [apps/ethos/README.md](../apps/ethos/README.md#comandos-de-operação-cli).

Os comandos do CLI rodam como `app-ethos`, com o ambiente da unit, pelo `systemd-run` (o `smtp.env` é `0600` do root, então `sudo -u app-ethos` não basta). Defina uma vez no shell:

```bash
ethos_cli=(sudo systemd-run --quiet --pipe --wait --collect --uid=app-ethos --gid=app-ethos
  --working-directory=/opt/apps/ethos
  -p EnvironmentFile=/etc/infra/smtp.env -p EnvironmentFile=/etc/infra/apps/ethos.env
  -E PYTHONDONTWRITEBYTECODE=1)
```

**0. Antes de parar o serviço**

```bash
# Escolha o backup: o pre-deploy-<sha>.db de um deploy, um snapshot diário ou o Litestream
sudo ls -lt /var/backups/sqlite/ethos/
# O journal precisa ser mais antigo que o backup: senão, exclusões feitas entre o backup e a
# primeira linha do journal não voltam a ser aplicadas (o journald guarda até 100M)
sudo journalctl -u app-ethos -o short-iso --no-pager | head -n 1
# As exclusões que o reapply-deletions vai ler
sudo journalctl -u app-ethos -o cat --no-pager | grep -c 'app.auth.deletion: conta'
```

Se o problema foi uma **migração que estragou os dados**, o `pre-deploy-<sha>.db` é o do deploy que a aplicou, e o código também precisa voltar (o código novo rodaria a migração de novo na subida). Antes de tudo:

1. Garanta que a `main` não vai publicar a migração quebrada de novo (corrija ou reverta antes do próximo push).
2. Faça o rollback: Actions → Ethos → Run workflow com o commit publicado antes de `<sha>`. O serviço sobe com o código antigo, ainda no banco estragado (o deploy leva junto os arquivos de migração que o banco já tem).
3. Siga os passos abaixo com a opção A, **pulando** o `alembic upgrade head` do passo 3 (ele aplicaria a migração quebrada de novo). O `reapply-deletions` roda com o código antigo, que bate com o banco restaurado (precisa ser um commit com o comando, da ETH-42 em diante).
4. No passo 4, suba só o `litestream` e o `ethos-alerts.timer` e, no lugar do `app-ethos`, rode o mesmo rollback de novo: agora o banco está na revisão antiga, o deploy tira os arquivos da migração quebrada e a subida não migra nada.

**1. Parar tudo que escreve no banco**

```bash
sudo systemctl stop ethos-alerts.timer ethos-alerts.service app-ethos
sudo systemctl stop litestream
```

**2. Pôr o backup no lugar**

```bash
sudo mv /var/lib/sqlite/ethos/app.db{,.quebrado}
sudo rm -f /var/lib/sqlite/ethos/app.db-{wal,shm}

# opção A: cópia de antes de um deploy
sudo cp /var/backups/sqlite/ethos/pre-deploy-<sha>.db /var/lib/sqlite/ethos/app.db
# opção B: snapshot local
sudo cp /var/backups/sqlite/ethos/2026-10-17.db /var/lib/sqlite/ethos/app.db
# opção C: Litestream (último estado ou, com -timestamp, um ponto no tempo)
sudo bash -c 'set -a; . /etc/default/litestream; set +a; litestream restore -config /etc/litestream.yml /var/lib/sqlite/ethos/app.db'

sudo chown app-ethos:app-ethos /var/lib/sqlite/ethos/app.db
sudo -u app-ethos sqlite3 /var/lib/sqlite/ethos/app.db 'PRAGMA integrity_check; PRAGMA journal_mode=WAL;'   # ok e wal
sudo -u app-ethos sqlite3 /var/lib/sqlite/ethos/app.db 'PRAGMA foreign_key_check;'                         # nada
sudo -u app-ethos sqlite3 /var/lib/sqlite/ethos/app.db 'SELECT version_num FROM alembic_version;'          # revisão do backup
```

**3. Migrar e reaplicar as exclusões, com o serviço ainda parado**

```bash
# O banco na revisão do código instalado (o backup pode ser de antes da última migração)
"${ethos_cli[@]}" /opt/apps/ethos/.venv/bin/alembic upgrade head
# Lê as linhas do journal pelo stdin; as outras linhas são ignoradas
sudo journalctl -u app-ethos -o cat --no-pager \
  | "${ethos_cli[@]}" /opt/apps/ethos/.venv/bin/python -m app.cli reapply-deletions
```

A saída diz quantas linhas leu, quantas contas apagou, quantas ignorou (já não existiam no backup) e quantas pulou. Uma conta pulada é o último admin ativo do banco restaurado: torne admin a conta que já era admin depois do backup (`"${ethos_cli[@]}" /opt/apps/ethos/.venv/bin/python -m app.cli create-admin <email>`) e rode o `reapply-deletions` de novo. Se ele sair com erro (linha fora do formato, entrada vazia), nada foi apagado: confira o `-o cat` e o `sudo` do `journalctl`. O `reapply-deletions` também avança o contador de ids das contas até o maior id do log, para nenhuma conta nova herdar o id de uma apagada.

**4. Subir e conferir**

```bash
sudo systemctl start litestream app-ethos ethos-alerts.timer
systemctl is-active app-ethos litestream ethos-alerts.timer                 # active (3x)
curl -fsS http://127.0.0.1:3001/health                                      # {"status":"ok"}
curl -fsS https://manasomali.com/api/ethos/health                           # {"status":"ok"}
sudo journalctl -u app-ethos -n 20 --no-pager                               # sem erro na subida
```

Depois, rode o **Verificar backups** (Actions → Verificar backups → Run workflow): o Litestream começa uma geração nova a partir do banco restaurado. Quando tudo estiver certo, apague o `app.db.quebrado`, que ainda tem os dados das contas apagadas (a política de privacidade promete que eles somem dos backups em até 8 dias): `sudo rm /var/lib/sqlite/ethos/app.db.quebrado`.

## Ensaiar o restore do ethos sem parar o serviço

Numa cópia, nunca no `app.db` em uso. O app continua no ar o tempo todo. O `DATABASE_PATH` da cópia vai pelo `env`, depois do `systemd-run`: um `-E DATABASE_PATH=...` perderia para o `EnvironmentFile=` do `ethos.env` e o comando rodaria no banco de produção.

```bash
ensaio=$(sudo -u app-ethos mktemp -d /var/tmp/ethos-ensaio.XXXXXX)
sudo -u app-ethos cp /var/backups/sqlite/ethos/pre-deploy-<sha>.db "$ensaio/app.db"
sudo -u app-ethos sqlite3 "$ensaio/app.db" 'PRAGMA integrity_check;'      # ok
sudo journalctl -u app-ethos -o cat --no-pager | grep 'app.auth.deletion: conta'   # ids a reaplicar
"${ethos_cli[@]}" /usr/bin/env DATABASE_PATH="$ensaio/app.db" /opt/apps/ethos/.venv/bin/alembic upgrade head
sudo journalctl -u app-ethos -o cat --no-pager \
  | "${ethos_cli[@]}" /usr/bin/env DATABASE_PATH="$ensaio/app.db" /opt/apps/ethos/.venv/bin/python -m app.cli reapply-deletions
# De novo: 0 contas apagadas
sudo journalctl -u app-ethos -o cat --no-pager \
  | "${ethos_cli[@]}" /usr/bin/env DATABASE_PATH="$ensaio/app.db" /opt/apps/ethos/.venv/bin/python -m app.cli reapply-deletions
curl -fsS https://manasomali.com/api/ethos/health                          # 200 durante todo o ensaio
sudo rm -rf "$ensaio"
```

## VM perdida

1. Criar uma VM nova (Ubuntu 24.04 ou mais novo, x86_64) e apontar o DNS para o IP novo.
2. Atualizar os secrets `REMOTE_HOST` e `SSH_KNOWN_HOSTS` (`ssh-keyscan <ip>`) no GitHub.
3. Reemitir o certificado **antes** do workflow, porque a config versionada do Nginx aponta para os arquivos do Let's Encrypt e o `nginx -t` falha sem eles:
   `sudo apt install -y nginx && sudo snap install --classic certbot && sudo certbot --nginx -d manasomali.com -d www.manasomali.com`
4. Rodar o workflow **Infra** manualmente (Actions → Infra → Run workflow). Ele cria usuários, pastas e bancos **vazios**.
5. Para cada projeto, seguir "Restaurar um banco na mesma VM" (opção A). Antes do primeiro deploy a unit `app-<projeto>` não sobe (não há `.venv`), então o `systemctl start` dela não faz nada.
6. Rodar o workflow **Publish Website** e os deploys dos backends. O do ethos é Actions → Ethos → Run workflow, com o SHA do último commit da `main`; a subida aplica as migrações que faltarem.
7. O journal da VM antiga se perdeu com ela: as exclusões de conta feitas entre o último envio do Litestream (até `LITESTREAM_SYNC_INTERVAL`) e a perda da VM não têm como ser reaplicadas (risco aceito no plano). Se o disco antigo ainda puder ser lido, as linhas saem com `journalctl -D <pasta do journal antigo> -u app-ethos -o cat > exclusoes.log`. Como o CLI só existe na VM depois do deploy do passo 6 (é ele que cria a `.venv`), reaplique logo depois dele: `sudo systemctl stop ethos-alerts.timer app-ethos`, o passo 3 de "Restaurar o banco de uma app" com `< exclusoes.log` no lugar do `journalctl` e o passo 4.

## Testar a restauração

O workflow **Verificar backups** faz isso toda segunda. Para rodar na hora: Actions → Verificar backups → Run workflow. Para cada banco do `databases.txt` (o ethos inclusive), o `restore-test.sh` restaura do Object Storage numa pasta temporária, confere o `integrity_check` e o número de objetos do schema contra o banco vivo e exige um snapshot diário (`AAAA-MM-DD.db`) das últimas 26h; um `pre-deploy-<sha>.db` recente não conta. O CI do ethos (`apps/ethos/deploy/test-vm.sh`) roda o `restore-test.sh` com o banco do ethos populado e um Litestream falso, e também o passo a passo de "Restaurar o banco de uma app" com o `reapply-deletions`.
