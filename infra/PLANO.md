# Plano: SQLite na VM com CI/CD automatizado

Objetivo: preparar a VM (VM.Standard.E2.1.Micro, 1 GB de RAM, Ubuntu + Nginx com HTTPS na 443; o site é servido por `/etc/nginx/sites-available/default`) para hospedar bancos SQLite de projetos futuros, em paralelo ao site estático, com provisionamento, backup e verificação totalmente automatizados via GitHub Actions.

## Status (2026-10-17)

Implementado em `infra/` e `.github/workflows/`. **O código é a fonte da verdade**; as seções abaixo são o plano original. Diferenças em relação a ele:

- **Litestream 0.5.17** (tarball com SHA256 fixo em `config.env`, instalado em `/usr/local/bin`). Na 0.5 a config usa `replica:` (singular), não `replicas:`. Os níveis de compactação são poucos e o `sync-interval` é de 1 minuto, porque o Object Storage Always Free tem cerca de **50 mil requisições por mês**.
- **Bucket sem versionamento**: o Litestream apaga arquivos antigos por conta própria, e com versionamento eles continuariam ocupando os 20 GB.
- Nomes de banco: `^[a-z][a-z0-9-]{1,26}$`, para `app-<nome>` caber no limite de 32 caracteres de usuário do Linux.
- O módulo do Litestream se chama `lib/backups.sh` (e não `litestream.sh`) e também instala o timer de snapshots.
- Os scripts executados como root (snapshot, restore-test, smoke-test) são copiados para `/usr/local/lib/infra/`, com dono root, e não rodam a partir de `/opt/infra`, que é gravável pelo usuário de deploy.
- **Sudo:** o usuário `ubuntu` das imagens da OCI já tem sudo total sem senha, então não foi criado um sudoers restrito. O workflow cria o `/opt/infra` sozinho, sem bootstrap manual. Se no futuro for criado um usuário `deploy` dedicado, ele precisa de NOPASSWD para `/opt/infra/provision.sh`, `/usr/local/lib/infra/restore-test.sh` e para o `install -d` do `/opt/infra`.
- Os snapshots rodam como `app-<nome>`, para evitar que `-wal`/`-shm` sejam criados com dono root. O smoke test verifica o dono desses arquivos.
- Keep-alive anti-ociosidade em `keepalive.timer` (substitui o crontab).

## Decisões

| Tema | Decisão |
|---|---|
| Modelo | **Um arquivo `.db` por projeto**, em `/var/lib/sqlite/<projeto>/app.db`. Cada backend roda na própria VM, como usuário de sistema próprio, e abre o arquivo direto. Não existe processo "servidor de banco" |
| Código de infra | Pasta `infra/` neste repositório |
| Provisionamento | Um script `provision.sh` **idempotente**: rodar 1 ou 100 vezes dá o mesmo resultado. Executado pelo CI a cada push em `infra/**` |
| Fonte da verdade | `infra/databases.txt`: um nome de projeto por linha. Adicionar uma linha cria usuário, pasta, permissões e backup |
| Backup off-site | **Litestream** replicando continuamente para o **Object Storage gratuito da Oracle** (API compatível com S3, 20 GB no Always Free) |
| Backup local | Snapshot diário com `sqlite3 .backup` e retenção de 7 dias, para restaurar rápido |
| Verificação | Workflow semanal que **restaura** cada banco do Object Storage e roda `PRAGMA integrity_check` |
| Rede | Nginx continua servindo o site em `/`. Cada projeto futuro ganha um snippet `location /api/<projeto>/` em `/etc/nginx/apps.d/` |

## Estrutura final no repositório

```
.github/workflows/
  deploy.yaml            # existente (site), ganha paths-ignore para infra/**
  infra.yaml             # novo: lint -> deploy da infra -> smoke test
  backup-verify.yaml     # novo: cron semanal de teste de restauração
infra/
  PLANO.md               # este arquivo
  databases.txt          # lista declarativa de bancos (começa vazia ou com "exemplo")
  provision.sh           # script idempotente principal (roda como root na VM)
  lib/
    swap.sh              # cria swapfile 2G + vm.swappiness=10
    system.sh            # desliga serviços sem uso, limita journald, keep-alive anti-ociosidade
    packages.sh          # apt: sqlite3, nginx; litestream .deb com versão fixa + sha256
    databases.sh         # usuários, pastas, permissões, PRAGMAs iniciais
    litestream.sh        # gera /etc/litestream.yml a partir de databases.txt
    nginx.sh             # instala config do site + apps.d, valida com nginx -t
  templates/
    litestream.yml.tmpl
    app.service.tmpl     # unit systemd modelo para backends futuros
    app-nginx.conf.tmpl  # location /api/<projeto>/ -> 127.0.0.1:<porta>
  systemd/
    sqlite-snapshot.service
    sqlite-snapshot.timer
    keepalive.service    # sysbench 6h/dia com Nice=19 (substitui o crontab antigo)
    keepalive.timer
  nginx/
    site.conf            # config atual do site, trazida da VM na fase 0
  scripts/
    snapshot.sh          # .backup + integrity_check + rotação de 7 dias
    restore-test.sh      # restaura do S3 para /tmp e valida
    smoke-test.sh        # checagens pós-deploy
```

---

## Fase 0: descoberta e bootstrap (manual, uma vez só)

Tudo o que vem depois é automatizado. Esta fase prepara o terreno.

1. **Confirmar o ambiente na VM**
   ```bash
   lsb_release -a; uname -m; free -h; swapon --show; df -h /
   nginx -v; sudo nginx -T > ~/nginx-dump.txt
   ls /etc/letsencrypt 2>/dev/null; systemctl list-timers | grep -i certbot
   ```
   Copiar o bloco `server` do site para `infra/nginx/site.conf`. **Se houver certbot**, manter as linhas `ssl_certificate*` e `include /etc/letsencrypt/...` exatamente como estão, porque o provision não pode quebrar o HTTPS.

2. **Object Storage (Console da OCI)**
   - Criar o bucket `sqlite-backups` (privado, Standard tier), **sem** versionamento.
   - Em *Profile → Customer Secret Keys*, gerar um par de chaves no formato S3.
   - Anotar o namespace e a região. O endpoint fica: `https://<namespace>.compat.objectstorage.<region>.oraclecloud.com`

3. **Usuário de deploy com sudo restrito**
   O usuário do CI (o mesmo `REMOTE_USER` que já faz o rsync do site) ganha permissão para rodar **apenas** o provision como root:
   ```
   # /etc/sudoers.d/infra-deploy   (validar com: sudo visudo -cf /etc/sudoers.d/infra-deploy)
   deploy ALL=(root) NOPASSWD: /opt/infra/provision.sh
   ```
   > Na prática, quem controla o branch `main` e os secrets tem root na VM, porque o CI envia o script que roda com sudo. Mitigação: proteger o `main` (sem push direto, exigir PR) e usar um *GitHub Environment* `production` nos jobs de deploy.

   Criar `/opt/infra` com dono `deploy`, que é o destino do rsync. O sudoers aponta para o caminho exato do script.

4. **Secrets e variables no GitHub** (Settings → Secrets and variables → Actions)

   | Nome | Tipo | Valor |
   |---|---|---|
   | `REMOTE_HOST`, `REMOTE_USER`, `SERVER_SSH_KEY` | secret | já existem |
   | `SSH_KNOWN_HOSTS` | secret | saída de `ssh-keyscan <host>`, para fixar a chave do host e não usar `StrictHostKeyChecking=no` |
   | `LITESTREAM_ACCESS_KEY_ID` | secret | Customer Secret Key, parte de acesso |
   | `LITESTREAM_SECRET_ACCESS_KEY` | secret | Customer Secret Key, parte secreta |
   | `S3_ENDPOINT` | variable | endpoint do passo 2 |
   | `S3_BUCKET` | variable | `sqlite-backups` |
   | `OCI_REGION` | variable | ex.: `sa-saopaulo-1` |

**Pronto quando:** `ssh deploy@host sudo -n /opt/infra/provision.sh --help` responde sem pedir senha (pode ser um script placeholder).

---

## Fase 1: `provision.sh` idempotente

Script em bash com `set -euo pipefail`, que exige root, faz log em `/var/log/infra-provision.log` e chama os módulos de `lib/` em ordem. Cada módulo **verifica antes de agir**.

1. **`swap.sh`**: se `/swapfile` não existir, cria 2 GB, aplica `chmod 600` e `mkswap`, adiciona ao `/etc/fstab` e configura `vm.swappiness=10` em `/etc/sysctl.d/99-infra.conf`.
1. **`system.sh`**: enxuga a VM e cuida do keep-alive.
   - Desliga com `disable --now`: `udisks2`, `rpcbind` + `rpcbind.socket`, `iscsid` + `iscsid.socket`, `multipathd` + `multipathd.socket`. Aplica `mask` no `packagekit`. Remove o snap `lxd`.
   - Limita o journald com `/etc/systemd/journald.conf.d/size.conf` (`SystemMaxUse=100M`).
   - Configura `snap set system refresh.retain=2`, para guardar menos revisões antigas de snaps no disco.
   - Instala `keepalive.service` + `keepalive.timer`: diário às 01:00, `sysbench cpu --threads=1 --time=21600 run`, com `Nice=19` e `CPUWeight=1`, para nunca competir com o site e os backends.
   - Remove do crontab do `ubuntu` as linhas antigas de `sysbench` e `certbot renew`, se ainda existirem.
2. **`packages.sh`**: `apt-get install -y sqlite3 nginx`. Para o Litestream, baixa o `.deb` amd64 da versão fixada em `LITESTREAM_VERSION` nas releases do GitHub, **confere o SHA256** registrado no repositório e só então instala. Pula se `litestream version` já bate.
3. **`databases.sh`**: para cada linha de `databases.txt`:
   - valida o nome com `^[a-z][a-z0-9-]{1,30}$`;
   - cria o usuário de sistema `app-<projeto>` (`--system --no-create-home --shell /usr/sbin/nologin`);
   - cria `/var/lib/sqlite/<projeto>/` com dono `app-<projeto>:app-<projeto>` e modo `0750`. **A pasta precisa ser gravável**, porque o WAL cria `-wal` e `-shm` ao lado do `.db`;
   - se `app.db` não existir, cria o arquivo e aplica `PRAGMA journal_mode=WAL;`, que fica persistido no arquivo;
   - **nunca apaga nada.** Um projeto removido da lista só gera um aviso no log, e os dados ficam na VM.
4. **`litestream.sh`**: gera `/etc/litestream.yml` a partir do template, com uma entrada por banco:
   ```yaml
   dbs:
     - path: /var/lib/sqlite/<projeto>/app.db
       replicas:
         - type: s3
           bucket: ${S3_BUCKET}
           path: <projeto>
           endpoint: ${S3_ENDPOINT}
           region: ${OCI_REGION}
           force-path-style: true
   ```
   As credenciais vão para `/etc/default/litestream` (modo `0600`, dono root), escritas pelo CI a partir dos secrets. Se o arquivo gerado mudou, roda `systemctl restart litestream`. Habilita o serviço com `enable --now`.
5. **Snapshots locais**: instala `sqlite-snapshot.service` e `.timer` (diário às 04:00, com `Persistent=true`). O `snapshot.sh` faz, para cada banco: `sqlite3 app.db ".backup /var/backups/sqlite/<projeto>/<data>.db"`, depois `PRAGMA integrity_check` na cópia, e apaga cópias com mais de 7 dias.
6. **`nginx.sh`**: copia `nginx/site.conf` e garante `include /etc/nginx/apps.d/*.conf;` dentro do `server`. Em seguida roda `nginx -t`: **se falhar, restaura a config anterior** (backup feito antes da cópia) e sai com erro. Se passar, roda `systemctl reload nginx`.
7. **Rodar o `smoke-test.sh` no final** (ver Fase 3).

**Pronto quando:** rodar o provision duas vezes seguidas na VM produz zero mudanças na segunda execução, e o log mostra "ok, nada a fazer" em cada módulo.

---

## Fase 2: workflows de CI/CD

### 2.1 `deploy.yaml` (site, já existe)

- Adicionar `paths-ignore: ['infra/**', '.github/workflows/infra.yaml', '.github/workflows/backup-verify.yaml']`, para mudanças de infra não republicarem o site.
- Aproveitar e atualizar `actions/checkout@v3` e `setup-node@v3` para `@v4`. A v3 roda em Node 16, que está depreciado nos runners.

### 2.2 `infra.yaml` (novo)

```yaml
name: Infra
on:
  push:
    branches: [main]
    paths: ['infra/**', '.github/workflows/infra.yaml']
  pull_request:
    paths: ['infra/**']
  workflow_dispatch:

concurrency: { group: infra, cancel-in-progress: false }   # nunca dois provisions ao mesmo tempo

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: find infra -name '*.sh' -exec shellcheck {} +
      - name: nginx -t em container
        run: docker run --rm -v $PWD/infra/nginx/site.conf:/etc/nginx/conf.d/default.conf:ro nginx:stable nginx -t
        # usa certificados autoassinados de mentira se o site.conf referenciar /etc/letsencrypt
      - name: validar databases.txt
        run: "! grep -vE '^\\s*(#|$)' infra/databases.txt | grep -vxE '[a-z][a-z0-9-]{1,30}'"   # falha se houver nome inválido

  deploy:
    needs: lint
    if: github.event_name != 'pull_request'
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - name: Configurar SSH
        run: |
          install -m 700 -d ~/.ssh
          echo "${{ secrets.SERVER_SSH_KEY }}" > ~/.ssh/id && chmod 600 ~/.ssh/id
          echo "${{ secrets.SSH_KNOWN_HOSTS }}" > ~/.ssh/known_hosts
      - name: Enviar infra
        run: rsync -az --delete -e "ssh -i ~/.ssh/id" infra/ ${{ secrets.REMOTE_USER }}@${{ secrets.REMOTE_HOST }}:/opt/infra/
      - name: Provisionar
        run: |
          ssh -i ~/.ssh/id ${{ secrets.REMOTE_USER }}@${{ secrets.REMOTE_HOST }} \
            "sudo -n /opt/infra/provision.sh" <<EOF
          LITESTREAM_ACCESS_KEY_ID=${{ secrets.LITESTREAM_ACCESS_KEY_ID }}
          LITESTREAM_SECRET_ACCESS_KEY=${{ secrets.LITESTREAM_SECRET_ACCESS_KEY }}
          S3_ENDPOINT=${{ vars.S3_ENDPOINT }}
          S3_BUCKET=${{ vars.S3_BUCKET }}
          OCI_REGION=${{ vars.OCI_REGION }}
          EOF
```
As credenciais vão pelo **stdin** do SSH, nunca como argumento de linha de comando, porque argumentos ficam visíveis em `ps` e nos logs. O `provision.sh` lê o stdin e grava `/etc/default/litestream`.

### 2.3 `backup-verify.yaml` (novo)

- `on: schedule: cron '0 6 * * 1'` (segunda, 03:00 em Brasília) e `workflow_dispatch`.
- Via SSH, roda `restore-test.sh`, que para cada banco executa `litestream restore -o /tmp/verify-<projeto>.db s3://...`, depois `PRAGMA integrity_check` (tem que retornar `ok`), compara a contagem de tabelas com o banco vivo e apaga o arquivo temporário.
- Também confere se o snapshot local mais recente tem menos de 26 horas.
- Se falhar, o GitHub manda e-mail automaticamente sobre o workflow quebrado. Esse é o alerta.

Para o `restore-test.sh` rodar com sudo, adicionar no sudoers: `deploy ALL=(root) NOPASSWD: /opt/infra/scripts/restore-test.sh`.

---

## Fase 3: smoke test pós-deploy

O `smoke-test.sh` roda no fim de cada provision. Se qualquer item falhar, o job do CI fica vermelho.

- [ ] `swapon --show` lista `/swapfile`
- [ ] `systemctl is-active nginx litestream` retorna `active` para os dois
- [ ] `systemctl list-timers sqlite-snapshot.timer` mostra o próximo disparo
- [ ] `curl -fsS -o /dev/null http://127.0.0.1/` retorna 200 (o site continua no ar)
- [ ] para cada banco: `PRAGMA journal_mode` retorna `wal`, `PRAGMA integrity_check` retorna `ok`, e o dono do arquivo é `app-<projeto>`
- [ ] `litestream databases` lista todos os bancos de `databases.txt`
- [ ] `free -m`: registrar a memória disponível no log, para acompanhar o consumo ao longo do tempo

---

## Fase 4: contrato para projetos futuros

Um projeto novo que quer banco segue este passo a passo:

1. **Neste repo:** adicionar `meuprojeto` em `infra/databases.txt` e abrir um PR. O merge provisiona usuário, pasta e backup.
2. **No repo do projeto:**
   - fazer o build no CI (nunca na VM) e enviar o artefato por rsync para `/opt/apps/meuprojeto/`;
   - instalar a unit systemd a partir de `infra/templates/app.service.tmpl`:
     ```ini
     [Service]
     User=app-meuprojeto
     Environment=DATABASE_PATH=/var/lib/sqlite/meuprojeto/app.db
     Environment=PORT=3001
     ExecStartPre=/opt/apps/meuprojeto/migrate      # migrações antes de subir
     ExecStart=/opt/apps/meuprojeto/start
     MemoryMax=150M                                  # protege o resto da VM
     Restart=on-failure
     NoNewPrivileges=true
     ProtectSystem=strict
     ReadWritePaths=/var/lib/sqlite/meuprojeto
     ```
   - adicionar o snippet Nginx a partir de `app-nginx.conf.tmpl` (`location /api/meuprojeto/ { proxy_pass http://127.0.0.1:3001/; }`);
   - ao abrir a conexão, aplicar os PRAGMAs `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON` e `cache_size=-16000`. O `journal_mode=WAL` já vem do provision.
3. Para automatizar os passos 2 e 3, o provision pode instalar a unit e o snippet a partir de um `infra/apps/<projeto>.env` (porta e comando). Decidir isso quando o primeiro projeto real aparecer, para não abstrair cedo demais.

> **Atenção ao Litestream e às migrações:** o Litestream é compatível com qualquer escrita normal, mas **não** com `VACUUM INTO` sobre o próprio arquivo, nem com apagar e recriar o `.db`. Migrações devem ser feitas com `ALTER` e `CREATE` dentro de transações.

---

## Fase 5: recuperação de desastre (documentar e testar uma vez)

Escrever em `infra/RESTORE.md` e **executar de verdade** uma vez:

1. VM perdida: criar uma VM nova, fazer a fase 0 (sudoers e known_hosts) e rodar o workflow `infra.yaml` manualmente.
2. Para cada projeto: `systemctl stop app-<projeto>`, depois `litestream restore -o /var/lib/sqlite/<projeto>/app.db s3://...`, depois `chown` e `systemctl start`.
3. Para voltar a um ponto específico no tempo: `litestream restore -timestamp 2026-10-17T12:00:00Z ...`.

---

## Ordem de execução e critérios de aceite

| # | Entrega | Critério de aceite |
|---|---|---|
| 0 | Bootstrap | `sudo -n /opt/infra/provision.sh` roda via SSH sem senha, secrets cadastrados, `site.conf` atual versionado |
| 1 | `provision.sh` + módulos | Duas execuções seguidas, segunda sem mudanças. Site continua respondendo |
| 2 | `infra.yaml` | Push em `infra/**` provisiona sozinho. PR roda só o lint. Push que só mexe no site não dispara a infra, e vice-versa |
| 3 | Banco `exemplo` em `databases.txt` | Arquivo criado com WAL, aparece no bucket da OCI em até 1 minuto após uma escrita |
| 4 | `backup-verify.yaml` | Execução manual fica verde. Corromper de propósito um snapshot local faz ela ficar vermelha |
| 5 | `RESTORE.md` | Restauração completa testada uma vez numa pasta temporária |
| 6 | Templates para projetos | Um backend "hello" de teste lê e grava no `exemplo` atrás de `/api/exemplo/` |

## Orçamento de memória

Medição real em 2026-10-17: 964 MiB no total, **516 MiB usados, só 282 MiB disponíveis**, sem swap. O uso base é o dobro do esperado para um Ubuntu. Suspeitos: Oracle Cloud Agent e snapd (o certbot está instalado via snap). Investigar antes de subir qualquer backend.

| Item | RAM |
|---|---|
| Ubuntu + agentes atuais (medido) | ~516 MB |
| Litestream | ~20–40 MB |
| SQLite | 0 (roda dentro de cada backend) |
| **Sobra hoje** | **~240 MB** + 2 GB de swap: 1 ou 2 backends leves (Go ou Node enxuto) |
| Sobra se enxugar os agentes | ~400–500 MB |

## Achados da fase 0 (2026-10-17)

- Ubuntu 22.04.1 LTS, x86_64, 35 GB livres em disco. O suporte padrão do 22.04 vai até abril de 2027: planejar a migração para o 24.04.
- Nginx 1.18. Só `sites-enabled/default` está ativo e `conf.d/` está vazio. Para HTTP/2 nessa versão a sintaxe é `listen 443 ssl http2;` (`http2 on;` só existe a partir da 1.25).
- Certbot via snap (`snap.certbot.renew.timer`) com `authenticator = nginx` e `installer = nginx`. A renovação só rescreve os mesmos caminhos de certificado (`live/` é symlink), então o arquivo versionado continua válido. Depois do primeiro provision, rodar `sudo certbot renew --dry-run` uma vez para confirmar.
- Swap de 2 GB criado manualmente em 2026-10-17 (`/swapfile`, no fstab, `vm.swappiness=10` em `/etc/sysctl.d/99-infra.conf`). O `lib/swap.sh` deve detectar isso e não fazer nada.
- **Causa principal do consumo de memória:** o crontab do usuário `ubuntu` tinha `* 1 * * * sysbench --test=cpu --time=21600 run`, ou seja, **um sysbench novo a cada minuto entre 01:00 e 01:59, cada um durando 6 horas**: 60 processos simultâneos, ~500 MB e toda a CPU até ~08:00. A intenção era uma carga diária para a Oracle não recuperar a VM por ociosidade. Esse keep-alive passa a ser gerenciado pelo repo (`keepalive.timer`, um processo só, com `Nice=19`).
- O crontab também tem `0 0 * * * /usr/bin/certbot renew`, que duplica o `snap.certbot.renew.timer`. Pode ser removido.
- Disco de boot é paravirtualizado (sem sessões iSCSI): `iscsid` e `multipathd` podem ser desligados.
- Outros consumidores: oracle-cloud-agent (snap, plugins `gomon` e `oci-wlp`), snapd, journald. Sem uso: lxd, udisks2, rpcbind, packagekit.

## Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Provision quebra o Nginx e derruba o site | `nginx -t` antes do reload com rollback automático, `nginx -t` também no CI, e smoke test com `curl` |
| Certbot e repo disputam o `site.conf` | A config versionada já contém as linhas do Certbot. A renovação com o plugin nginx não muda os caminhos. Validar com `certbot renew --dry-run` após o primeiro provision |
| Credenciais S3 vazam nos logs | Envio via stdin, arquivo `0600`, secrets mascarados pelo Actions |
| CI com root na VM | Sudoers restrito a caminhos exatos, branch protegido, environment `production` |
| Backup silenciosamente quebrado | Teste de restauração semanal automatizado |
| Bucket enche os 20 GB gratuitos | Retenção do Litestream (`retention: 168h`) e lifecycle policy no bucket |
| VM sem memória | Swap de 2 GB, `MemoryMax` por app, `free -m` registrado a cada deploy |
