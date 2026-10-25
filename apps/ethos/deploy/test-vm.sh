#!/usr/bin/env bash
# Testa o vm.sh num runner Ubuntu 24.04 (o sistema da VM), sem SSH: uv e Python instalados pelas
# funções do provision (infra/lib/packages.sh), o usuário que chamou o sudo no papel do usuário de
# deploy (sudo sem senha, como o ubuntu da VM), app-ethos dono do banco e o rsync do backend com o
# mesmo backend.rsync-filter do workflow. As pastas da VM ficam numa pasta temporária.
# No fim, com o banco populado pelo seed: o restore do infra/RESTORE.md (backup, exclusão gravada
# no journald, restore e reapply-deletions pelo systemd-run, como na VM) e o restore-test.sh do
# backup-verify.yaml. Este último usa os caminhos fixos da VM (/var/lib/sqlite, /etc/infra...) e
# um litestream falso, e por isso só roda num runner limpo.
# Roda na raiz do repo, pelo ethos.yaml: sudo bash apps/ethos/deploy/test-vm.sh
set -euo pipefail
shopt -s inherit_errexit

INFRA_DIR=$PWD/infra
# shellcheck source=infra/lib/common.sh
source "$INFRA_DIR/lib/common.sh"
# shellcheck source=infra/config.env
source "$INFRA_DIR/config.env"
# shellcheck source=infra/lib/packages.sh
source "$INFRA_DIR/lib/packages.sh"

require_root
deploy_user=${SUDO_USER:?rode com sudo, a partir do usuário que faz o papel do usuário de deploy}
[[ $deploy_user != root ]] || die "rode com sudo a partir de um usuário comum"

here=$PWD/apps/ethos/deploy
backend=$PWD/apps/ethos/backend
app_user=app-ethos
test_unit=ethos-deploy-test.service
sha=0123456789abcdef0123456789abcdef01234567

fail() {
  echo "::error::$*"
  exit 1
}

root=$(mktemp -d)
out=$root/out
uvicorn_pid=""
# Caminhos fixos da VM que o teste do restore-test.sh cria (num runner limpo, nenhum existe antes)
vm_paths=(/usr/local/lib/infra /etc/infra /var/lib/sqlite /var/backups/sqlite /etc/default/litestream
  /etc/litestream.yml /usr/local/bin/litestream)
created_vm_paths=0
cleanup() {
  if [[ -n $uvicorn_pid ]]; then
    kill "$uvicorn_pid" 2>/dev/null || true
  fi
  systemctl stop "$test_unit" 2>/dev/null || true
  rm -f "/etc/systemd/system/$test_unit"
  systemctl daemon-reload
  if ((created_vm_paths)); then
    rm -rf "${vm_paths[@]}"
  fi
  rm -rf "$root"
}
trap cleanup EXIT
# Percorrível pelo app-ethos e pelo usuário de deploy, como /opt, /var/www e /var/lib na VM
chmod 0755 "$root"

app_dir=$root/opt/apps/ethos
web_dir=$root/www/ethos
db=$root/sqlite/ethos/app.db
backup_dir=$root/backups/ethos
config=$root/etc/config.env

# vm.sh pelo stdin, como o workflow manda pelo SSH, rodado pelo usuário de deploy
vm() {
  runuser -u "$deploy_user" -- env \
    DEPLOY_UNIT="${unit:-app-ethos.service}" DEPLOY_APP_DIR="$app_dir" DEPLOY_WEB_DIR="$web_dir" \
    DEPLOY_DB="$db" DEPLOY_BACKUP_DIR="$backup_dir" DEPLOY_INFRA_CONFIG="$config" \
    bash -s -- "$@" < "$here/vm.sh"
}

# Saída de uma falha esperada, recuada: um "::error::" no começo da linha viraria anotação de erro
# no Actions, num job que passou
show() { sed 's/^/    | /' "$1"; }

expect_failure() {
  local message=$1
  shift
  if "$@" >"$out" 2>&1; then
    show "$out"
    fail "deveria falhar: $*"
  fi
  show "$out"
  grep -qF -- "$message" "$out" || fail "mensagem esperada: $message"
}

# Mesmas opções do passo "Enviar o backend" do ethos.yaml
push_backend() {
  runuser -u "$deploy_user" -- rsync -rlpt --chmod=D0755,F0644 --delete \
    --filter="merge $here/backend.rsync-filter" "$backend/" "$app_dir/"
}

as_app() { runuser -u "$app_user" -- "$@"; }

echo "--- uv e Python como o provision instala"
install_uv
install_pythons
python_version=$(<"$backend/.python-version")

echo "--- pastas e banco como o provision cria"
if ! id "$app_user" >/dev/null 2>&1; then
  useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$app_user"
fi
install -d -m 0755 "$root/opt" "$root/opt/apps" "$root/www" "$root/sqlite" "$root/backups" "$root/etc"
install -d -m 0755 -o "$deploy_user" -g "$deploy_user" "$app_dir" "$web_dir"
install -d -m 0750 -o "$app_user" -g "$app_user" "$(dirname "$db")"
install -d -m 0700 -o "$app_user" -g "$app_user" "$backup_dir"
as_app sqlite3 "$db" 'PRAGMA journal_mode=WAL;' >/dev/null
cp "$INFRA_DIR/config.env" "$config"

echo "--- check: sem a unit, falha pedindo o Infra"
expect_failure "app-ethos.service não está instalada na VM: rode o workflow Infra" vm check "$python_version"

echo "--- check: com uma unit que existe"
unit=systemd-journald.service
vm check "$python_version"
expect_failure "Python 3.0.0 não está instalado" vm check 3.0.0
expect_failure "versão do Python inválida" vm check '3.14; true'
mv "$config" "$config.off"
expect_failure "config.env não existe" vm check "$python_version"
mv "$config.off" "$config"

echo "--- revision: banco recém-criado, sem migração"
[[ -z $(vm revision) ]] || fail "revision deveria sair vazio num banco sem alembic_version"

echo "--- rsync do backend e install"
push_backend
vm install
[[ -x $app_dir/.venv/bin/uvicorn ]] || fail ".venv sem uvicorn"
python=$(readlink -f "$app_dir/.venv/bin/python")
[[ $python == "$UV_PYTHON_INSTALL_DIR"/* ]] || fail "a .venv usa $python, fora de $UV_PYTHON_INSTALL_DIR"
[[ $("$app_dir/.venv/bin/python" --version) == "Python $python_version" ]] || fail "Python da .venv errado"
compgen -G "$app_dir/app/__pycache__/*.pyc" >/dev/null || fail "app/ sem bytecode"
compgen -G "$app_dir/migrations/versions/__pycache__/*.pyc" >/dev/null || fail "migrations/ sem bytecode"
[[ -n $(find "$app_dir/.venv/lib" -name '*.pyc' -print -quit) ]] || fail "pacotes da .venv sem bytecode"
if "$app_dir/.venv/bin/python" -c 'import pytest' 2>/dev/null; then
  fail "dependência de dev (pytest) instalada"
fi
[[ ! -e $app_dir/tests ]] || fail "tests/ foi para a VM"
writable=$(find "$app_dir" ! -type l -perm /022 -print -quit)
[[ -z $writable ]] || fail "gravável por grupo ou outros: $writable"
not_deploy=$(find "$app_dir" ! -user "$deploy_user" -print -quit)
[[ -z $not_deploy ]] || fail "sem dono $deploy_user: $not_deploy"

echo "--- migração e API como o app-ethos, como o ExecStartPre e o ExecStart da unit"
as_app env -C "$app_dir" PYTHONDONTWRITEBYTECODE=1 DATABASE_PATH="$db" .venv/bin/alembic upgrade head
head_revision=$(basename "$(find "$backend/migrations/versions" -name '[0-9]*.py' | sort | tail -n1)")
head_revision=${head_revision%%_*}
[[ $(vm revision) == "$head_revision" ]] || fail "revision: '$(vm revision)', esperado $head_revision"
# Config de dev do .env.example (email no console), com o banco do teste. Copiado para fora da
# home do runner, que o app-ethos não lê
install -m 0644 "$backend/.env.example" "$root/app.env"
# shellcheck disable=SC2016 # $1 e $2 são expandidos pelo bash -c, não aqui
as_app env -C "$app_dir" PYTHONDONTWRITEBYTECODE=1 bash -c 'set -a && source "$1" && DATABASE_PATH=$2 &&
  exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 3999 --root-path /api/ethos' \
  uvicorn "$root/app.env" "$db" >"$root/uvicorn.log" 2>&1 &
uvicorn_pid=$!
for _ in $(seq 1 40); do
  if body=$(curl -fsS --max-time 2 http://127.0.0.1:3999/health 2>/dev/null); then
    break
  fi
  sleep 0.5
done
[[ ${body:-} == '{"status":"ok"}' ]] || { cat "$root/uvicorn.log"; fail "/health não respondeu ok: '${body:-}'"; }
kill "$uvicorn_pid"
wait "$uvicorn_pid" 2>/dev/null || true
uvicorn_pid=""

echo "--- backup pré-deploy"
vm backup "$sha"
first=$backup_dir/pre-deploy-$sha.db
[[ -f $first ]] || fail "$first não existe"
[[ $(stat -c '%U %a' "$first") == "$app_user 600" ]] || fail "$first: $(stat -c '%U %a' "$first"), esperado $app_user 600"
[[ $(as_app sqlite3 "$first" 'PRAGMA integrity_check;') == ok ]] || fail "backup corrompido"
[[ $(as_app sqlite3 "$first" 'PRAGMA journal_mode;') == delete ]] || fail "backup ainda em WAL"
[[ $(as_app sqlite3 "$first" 'SELECT version_num FROM alembic_version;') == "$head_revision" ]] || fail "backup sem a revisão"
compgen -G "$backup_dir/*.partial" >/dev/null && fail "sobrou um .partial"
compgen -G "$backup_dir/*-wal" >/dev/null && fail "backup com -wal ao lado"
before=$(sha256sum "$first")

echo "--- o mesmo commit de novo: o primeiro backup fica, o novo ganha a hora no nome"
vm backup "$sha"
[[ $(sha256sum "$first") == "$before" ]] || fail "o segundo backup sobrescreveu o primeiro"
count=$(find "$backup_dir" -name "pre-deploy-$sha-*.db" | wc -l)
((count == 1)) || fail "esperado 1 backup com a hora no nome, achados $count"
expect_failure "sha inválido" vm backup "abc; rm -rf /"
expect_failure "uso:" vm backup

echo "--- deploy seguinte: .venv fica, arquivo que saiu do repo sai da VM, bytecode refeito"
runuser -u "$deploy_user" -- touch "$app_dir/app/removido.py" "$app_dir/.env"
runuser -u "$deploy_user" -- mkdir -p "$app_dir/app/__pycache__"
runuser -u "$deploy_user" -- touch "$app_dir/app/__pycache__/removido.cpython-314.pyc"
venv_before=$(stat -c %i "$app_dir/.venv/bin/python")
push_backend
[[ ! -e $app_dir/app/removido.py ]] || fail "o --delete não tirou app/removido.py"
[[ ! -e $app_dir/.env ]] || fail "o --delete não tirou o .env"
[[ ! -e $app_dir/app/__pycache__/removido.cpython-314.pyc ]] || fail "bytecode velho ficou"
[[ $(stat -c %i "$app_dir/.venv/bin/python") == "$venv_before" ]] || fail "o rsync mexeu na .venv"
vm install
compgen -G "$app_dir/app/__pycache__/*.pyc" >/dev/null || fail "bytecode não foi refeito"

echo "--- restart: unit que sobe e unit cujo ExecStartPre falha (migração quebrada)"
cat > "/etc/systemd/system/$test_unit" <<EOF
[Service]
Type=exec
ExecStartPre=/usr/bin/test -e $root/start-ok
ExecStart=/usr/bin/sleep infinity
EOF
systemctl daemon-reload
unit=$test_unit
expect_failure "$test_unit não subiu (migração ou subida falhou)" vm restart
touch "$root/start-ok"
vm restart | tee "$out"
grep -q "$test_unit reiniciada" "$out" || fail "restart sem a mensagem de sucesso"
systemctl is-active --quiet "$test_unit" || fail "$test_unit não ficou ativa"
systemctl stop "$test_unit"

# --- Restore (infra/RESTORE.md, seção das apps) com o banco populado ----------------------------

# O ambiente da unit app-ethos: o .env.example (dev, email no console) com o banco do teste, lido
# pelo systemd como EnvironmentFile=, como o /etc/infra/apps/ethos.env
env_file=$root/etc/ethos.env
sed "s|^DATABASE_PATH=.*|DATABASE_PATH=$db|" "$backend/.env.example" > "$env_file"
chmod 0644 "$env_file"
# O ethos_cli do RESTORE.md, com os caminhos do teste. Sem o --pipe (ethos_unit), a saída vai
# para o journald, como a da unit app-ethos
ethos_unit=(systemd-run --quiet --wait --collect --uid="$app_user" --gid="$app_user"
  --working-directory="$app_dir" -p EnvironmentFile="$env_file" -E PYTHONDONTWRITEBYTECODE=1)
ethos_cli=("${ethos_unit[@]}" --pipe)
python_bin=$app_dir/.venv/bin/python
sql() { as_app sqlite3 "$1" "$2"; }
user_id() { sql "$1" "SELECT id FROM users WHERE email = '$2';"; }
reapplied_events() {
  sql "$1" "SELECT count(*) FROM audit_log WHERE event = 'account_deleted'
    AND json_extract(details, '\$.account_id') = $2 AND json_extract(details, '\$.reapplied') = 1;"
}

echo "--- banco populado (seed) pelo systemd-run, como app-ethos"
"${ethos_cli[@]}" "$python_bin" -m app.cli seed | tee "$out"
grep -q "seed: 3 contas" "$out" || fail "seed não criou as contas"
bia=$(user_id "$db" bia@example.com)
[[ $bia =~ ^[0-9]+$ ]] || fail "bia@example.com não está no banco"

echo "--- backup antigo (pre-deploy) e, depois dele, a exclusão da Bia com a linha no journald"
old_sha=fedcba9876543210fedcba9876543210fedcba98
vm backup "$old_sha"
old_backup=$backup_dir/pre-deploy-$old_sha.db
delete_unit=ethos-exclusao-teste-$$
since=$(date '+%Y-%m-%d %H:%M:%S')
# A exclusão de verdade (app/auth/deletion.py), com o log configurado como no servidor
"${ethos_unit[@]}" --unit="$delete_unit" "$python_bin" -c '
import sys
from app.auth.deletion import delete_account
from app.config import load_settings
from app.db import create_db_engine, create_session_factory
from app.logs import configure_logging
settings = load_settings()
configure_logging(settings.app_env)
with create_session_factory(create_db_engine(settings.database_path))() as session:
    account_id = int(sys.argv[1])
    delete_account(session, account_id=account_id, actor_id=account_id, ip=None)
' "$bia"
[[ -z $(user_id "$db" bia@example.com) ]] || fail "a Bia não foi apagada"
journal() { journalctl -u "$delete_unit" --since "$since" -o cat --no-pager; }
for _ in $(seq 1 20); do
  journal | grep -q "conta $bia excluída" && break
  sleep 0.5
done
journal | grep -x "INFO app.auth.deletion: conta $bia excluída" || fail "a linha da exclusão não chegou ao journald"

echo "--- restore-test.sh (backup-verify.yaml) com o banco populado e um litestream falso"
for path in "${vm_paths[@]}"; do
  [[ ! -e $path ]] || fail "$path já existe: o teste do restore-test.sh só roda num runner limpo"
done
created_vm_paths=1
install -D -m 0644 "$INFRA_DIR/lib/common.sh" /usr/local/lib/infra/common.sh
install -d -m 0755 /etc/infra /var/lib/sqlite /var/backups/sqlite /etc/default
printf 'ethos\n' > /etc/infra/databases
install -d -m 0750 -o "$app_user" -g "$app_user" /var/lib/sqlite/ethos
install -d -m 0700 -o "$app_user" -g "$app_user" /var/backups/sqlite/ethos
as_app sqlite3 "$db" ".backup /var/lib/sqlite/ethos/app.db"
as_app sqlite3 /var/lib/sqlite/ethos/app.db 'PRAGMA journal_mode=WAL;' >/dev/null
: > /etc/default/litestream
printf 'dbs: []\n' > /etc/litestream.yml
# O restore do Object Storage vira uma cópia do banco vivo (ninguém escreve nele: sem -wal).
# Com LITESTREAM_FALSO=incompleto, entrega o banco sem uma tabela
cat > /usr/local/bin/litestream <<'EOF'
#!/bin/bash
set -euo pipefail
[[ $# == 6 && $1 == restore && $2 == -config && $4 == -o ]] || { echo "litestream falso: $*" >&2; exit 2; }
cp "$6" "$5"
if [[ ${LITESTREAM_FALSO:-} == incompleto ]]; then
  sqlite3 "$5" 'DROP TABLE banners;'
fi
EOF
chmod 0755 /usr/local/bin/litestream
bash "$INFRA_DIR/scripts/snapshot.sh"
bash "$INFRA_DIR/scripts/restore-test.sh" | tee "$out"
grep -q "ethos: restauração ok" "$out" || fail "restore-test.sh não validou o ethos"
expect_failure "objetos no restaurado" env LITESTREAM_FALSO=incompleto bash "$INFRA_DIR/scripts/restore-test.sh"
# Só um pre-deploy recente, sem o snapshot diário: um snapshot.sh parado não pode passar
rm /var/backups/sqlite/ethos/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].db
as_app cp "$old_backup" "/var/backups/sqlite/ethos/pre-deploy-$old_sha.db"
expect_failure "ethos: nenhum snapshot local nas últimas 26h" bash "$INFRA_DIR/scripts/restore-test.sh"

echo "--- ensaio numa cópia, com o DATABASE_PATH trocado pelo env (o EnvironmentFile= venceria o -E)"
ensaio=$root/ensaio
install -d -m 0700 -o "$app_user" -g "$app_user" "$ensaio"
as_app cp "$old_backup" "$ensaio/app.db"
[[ $(sql "$ensaio/app.db" 'PRAGMA integrity_check;') == ok ]] || fail "integrity_check da cópia"
db_before=$(sha256sum < "$db")
journal | "${ethos_cli[@]}" /usr/bin/env DATABASE_PATH="$ensaio/app.db" \
  "$python_bin" -m app.cli reapply-deletions | tee "$out"
grep -q "1 contas apagadas, 0 ignoradas" "$out" || fail "o ensaio não apagou a Bia na cópia"
[[ -z $(user_id "$ensaio/app.db" bia@example.com) ]] || fail "a Bia continua na cópia"
[[ $(sha256sum < "$db") == "$db_before" ]] || fail "o ensaio mexeu no banco em uso"

echo "--- restore do pre-deploy, na ordem do RESTORE.md"
mv "$db" "$db.quebrado"
rm -f "$db-wal" "$db-shm"
cp "$old_backup" "$db"
chown "$app_user:$app_user" "$db"
[[ $(sql "$db" 'PRAGMA integrity_check; PRAGMA journal_mode=WAL;') == $'ok\nwal' ]] || fail "integrity_check ou WAL do restaurado"
[[ -z $(sql "$db" 'PRAGMA foreign_key_check;') ]] || fail "foreign_key_check do restaurado"
[[ $(user_id "$db" bia@example.com) == "$bia" ]] || fail "o restore não trouxe a Bia de volta"
"${ethos_cli[@]}" "$app_dir/.venv/bin/alembic" upgrade head
# As linhas do journald e um id solto de uma conta que não existe
{ journal; echo 99999; } | "${ethos_cli[@]}" "$python_bin" -m app.cli reapply-deletions | tee "$out"
grep -q "1 contas apagadas, 1 ignoradas" "$out" || fail "reapply-deletions não apagou a Bia"
[[ -z $(user_id "$db" bia@example.com) ]] || fail "a Bia voltou depois do reapply-deletions"
[[ $(reapplied_events "$db" "$bia") == 1 ]] || fail "account_deleted reaplicado ausente ou repetido"

echo "--- reapply-deletions de novo: nada muda"
events=$(sql "$db" 'SELECT count(*) FROM audit_log;')
{ journal; echo 99999; } | "${ethos_cli[@]}" "$python_bin" -m app.cli reapply-deletions | tee "$out"
grep -q "0 contas apagadas, 2 ignoradas" "$out" || fail "a segunda execução mudou algo"
[[ $(sql "$db" 'SELECT count(*) FROM audit_log;') == "$events" ]] || fail "a segunda execução gravou evento"
expect_failure "entrada vazia" "${ethos_cli[@]}" "$python_bin" -m app.cli reapply-deletions < /dev/null

echo "ok"
