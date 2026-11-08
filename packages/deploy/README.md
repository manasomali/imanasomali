# Scripts do deploy

Scripts que publicam uma aplicação de `apps/` na VM, rodados pelo workflow dela (`.github/workflows/<nome>.yaml`), com o nome da aplicação como parâmetro. Servem ao ethos e vão servir ao imago e ao engrafi: nenhuma aplicação importa código de outra (ver [apps/README.md](../../apps/README.md)), então o que o deploy delas tem em comum fica aqui.

Os 9 passos do deploy, o rollback e as regras (migrações só aditivas, mudança de infra num PR anterior) estão em [apps/ethos/README.md](../../apps/ethos/README.md#deploy). Valem para qualquer aplicação, trocando `ethos` pelo nome.

| Arquivo | Onde roda | O quê |
|---|---|---|
| `vm.sh` | VM, pelo SSH | passos na VM: `check`, `revision`, `install`, `backup` e `restart` |
| `keep-migrations.sh` | runner | rollback para antes de uma migração aplicada: copia da `main` as migrações que o banco já tem e o commit não |
| `backend.rsync-filter` | runner | regras do rsync do backend: a `.venv` fica intocada; `tests/`, caches, `.env` e bancos locais não sobem |
| `clean-assets.sh` | VM, pelo SSH | apaga os assets do front com mais de N dias que não estão no build atual |
| `test-deploy-scripts.sh` | CI, sem root | testes de `clean-assets.sh`, `keep-migrations.sh` e da recusa de nome inválido |
| `test-vm.sh` | CI, root num Ubuntu 24.04 limpo | `vm.sh` de ponta a ponta com o backend da aplicação e o `restore-test.sh` do `backup-verify.yaml` |

## Contrato

O nome da aplicação segue a regra do [infra/databases.txt](../../infra/databases.txt): `^[a-z][a-z0-9-]{1,26}$`. Dele saem o usuário, a unit, os caminhos e os comandos, então o `vm.sh` e o `test-vm.sh` recusam qualquer outro nome antes de qualquer passo.

Na VM, tudo criado pelo provision (`infra/apps/<nome>/` e a linha `<nome>` do `databases.txt`); o deploy só confere (`vm.sh check`) e falha pedindo o workflow Infra se faltar algo:

| O quê | Onde |
|---|---|
| Unit | `app-<nome>.service`, `Type=exec`, com `ExecStartPre=/opt/apps/<nome>/.venv/bin/alembic upgrade head` |
| Usuário da aplicação | `app-<nome>`: lê o código, é dono do banco e dos backups |
| Backend | `/opt/apps/<nome>/`, do usuário de deploy (`DEPLOY_USER` do `infra/config.env`, com sudo sem senha) |
| Frontend | `/var/www/<nome>/`, do usuário de deploy; o build do Vite com os arquivos com hash em `assets/` |
| Banco | `/var/lib/sqlite/<nome>/app.db` |
| Backup pré-deploy | `/var/backups/sqlite/<nome>/pre-deploy-<sha>.db` (pasta `0700` do `app-<nome>`) |
| Python | `PYTHON_VERSION` do `infra/apps/<nome>/app.conf`, igual ao `apps/<nome>/backend/.python-version`, instalado pelo provision em `UV_PYTHON_INSTALL_DIR` (o `vm.sh` nunca baixa um) |

No repo, o backend em `apps/<nome>/backend/`:

- projeto do uv sem `build-system`, com `uv.lock` e `.python-version`;
- código em `app/`, com o ASGI em `app.main:app` e `GET /health` respondendo `{"status":"ok"}`;
- migrações do Alembic em `migrations/`, com os arquivos em `migrations/versions/<revisão>_<descrição>.py` (revisão numérica, `0001`, `0002`...), e o banco escolhido pela variável `DATABASE_PATH`, no app e no Alembic;
- `.env.example` com uma config de dev que sobe trocando só o `DATABASE_PATH` (o `test-vm.sh` sobe a API com ela);
- testes em `tests/`, que não sobem para a VM.

## Como uma aplicação usa

O `.github/workflows/ethos.yaml` é o modelo: copie trocando `ethos` pelo nome. Os `paths` do workflow já têm `packages/**`, e o filtro do job que decide se há deploy precisa contar `packages/` como algo que vai para a VM.

Job de checagem dos scripts (num `ubuntu-24.04`, sempre com os scripts do commit do workflow):

```bash
shellcheck -x packages/deploy/*.sh
bash packages/deploy/test-deploy-scripts.sh
sudo apt-get update -q && sudo apt-get install -y -q --no-install-recommends sqlite3
sudo bash packages/deploy/test-vm.sh <nome> [<ensaio>]
```

Job de deploy, com a `main` (os scripts e as migrações) e o commit a publicar em `target/`:

```bash
$SSH "$TARGET" bash -s -- <nome> check "$python" < packages/deploy/vm.sh
revision=$($SSH "$TARGET" bash -s -- <nome> revision < packages/deploy/vm.sh)
bash packages/deploy/keep-migrations.sh \
  target/apps/<nome>/backend/migrations/versions apps/<nome>/backend/migrations/versions "$revision"
rsync -rlptz --chmod=D0755,F0644 --delete --filter="merge packages/deploy/backend.rsync-filter" \
  -e "$SSH" target/apps/<nome>/backend/ "$TARGET:/opt/apps/<nome>/"
$SSH "$TARGET" bash -s -- <nome> install < packages/deploy/vm.sh
$SSH "$TARGET" bash -s -- <nome> backup "$SHA" < packages/deploy/vm.sh
$SSH "$TARGET" bash -s -- <nome> restart < packages/deploy/vm.sh
# health check e front (sem --delete, index.html por último), e então:
args=$(printf '%q ' /var/www/<nome>/assets 7 "${files[@]}")
$SSH "$TARGET" "bash -s -- $args" < packages/deploy/clean-assets.sh
```

Regras:

- **Nada fica instalado na VM**: cada passo chega pelo stdin (`bash -s`) e só lê os argumentos. O usuário de deploy roda como `app-<nome>` só o que lê o banco e grava o backup, e como root só o `systemctl`. Nada do journal vai para o log do Actions (o repositório é público).
- **O nome vai literal no workflow**, nunca de uma entrada do `workflow_dispatch` nem de outra variável.
- **Os scripts são sempre os da `main`**, também num rollback, que publica o backend de um commit antigo com eles. Uma mudança aqui precisa continuar funcionando com os commits anteriores de todas as aplicações.
- **Uma mudança aqui dispara o workflow de todas as aplicações** (checagens e deploy, cada uma no seu grupo de concorrência) e o do site, que não usa estes scripts e publica o mesmo build de novo. Um erro aqui para o deploy de todas.

## Testes

- `bash packages/deploy/test-deploy-scripts.sh`: sem root, em pastas temporárias; roda em qualquer máquina com bash e as ferramentas GNU (o Git Bash serve).
- `sudo bash packages/deploy/test-vm.sh <nome> [<ensaio>]`: só no CI, num Ubuntu 24.04 limpo, com sudo a partir de um usuário comum (o papel do usuário de deploy). Instala o uv e o Python como o provision, cria o `app-<nome>` e as pastas da VM numa pasta temporária, e roda o `vm.sh` com o backend da aplicação: `check`, `revision`, rsync e `install`, migração e `/health` como `app-<nome>`, `backup` e `restart`. No fim, roda o `restore-test.sh` com um Litestream falso, nos caminhos reais da VM (`/etc/infra`, `/var/lib/sqlite`...), e por isso recusa um runner onde eles já existem.
- `<ensaio>`: script da aplicação, lido com `source` depois dos passos do deploy e antes do `restore-test.sh`, para o que só ela tem. As variáveis e funções que ele pode usar estão no cabeçalho do `test-vm.sh`. O do ethos, `apps/ethos/backend/tests/vm-restore.sh`, ensaia o [infra/RESTORE.md](../../infra/RESTORE.md) com o banco populado pelo `seed`: uma exclusão com a linha no journald, o ensaio numa cópia, o restore do `pre-deploy-<sha>.db` e o `reapply-deletions`.
