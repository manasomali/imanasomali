#!/usr/bin/env bash
# Testa o vm.sh com o backend de uma aplicação num runner Ubuntu 24.04 (o sistema da VM), sem SSH:
# uv e Python instalados pelas funções do provision (infra/lib/packages.sh), o usuário que chamou o
# sudo no papel do usuário de deploy (sudo sem senha, como o ubuntu da VM), app-<nome> dono do
# banco e o rsync do backend com o mesmo backend.rsync-filter do workflow. As pastas da VM ficam
# numa pasta temporária. No fim, o restore-test.sh do backup-verify.yaml com o banco da aplicação e
# um litestream falso. Este último usa os caminhos fixos da VM (/var/lib/sqlite, /etc/infra...) e,
# por isso, só roda num runner limpo.
#
#   sudo bash packages/deploy/test-vm.sh <nome> [<ensaio>]
#
# Roda pelo workflow da aplicação, com sudo a partir do usuário que faz o papel do usuário de
# deploy. <nome> é a aplicação, com o backend em apps/<nome>/backend/ (contrato em
# packages/deploy/README.md). <ensaio>, opcional, é um script da aplicação lido com "source" depois
# dos passos do deploy e antes do restore-test.sh, para o que só ela tem (o do ethos ensaia o
# infra/RESTORE.md com o CLI dele). Ele roda com set -euo pipefail, deixa o $DB íntegro (o
# restore-test.sh copia esse banco depois) e pode usar:
#   APP, APP_USER (app-<nome>), BACKEND (apps/<nome>/backend), APP_DIR, DB, BACKUP_DIR (os da VM,
#   dentro de TEST_ROOT), TEST_ROOT (pasta temporária, apagada no fim) e OUT (arquivo para saídas);
#   vm <comando> [args]                         o vm.sh pelo stdin, como o usuário de deploy
#   as_app <comando> [args]                     o comando como app-<nome>
#   expect_failure <mensagem> <comando> [args]  falha se o comando não falhar com a mensagem
#   fail <mensagem>                             para o teste com um erro
set -euo pipefail
shopt -s inherit_errexit

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
INFRA_DIR=$(cd "$here/../../infra" && pwd)
# shellcheck source=infra/lib/common.sh
source "$INFRA_DIR/lib/common.sh"
# shellcheck source=infra/config.env
source "$INFRA_DIR/config.env"
# shellcheck source=infra/lib/packages.sh
source "$INFRA_DIR/lib/packages.sh"

(($# == 1 || $# == 2)) || die "uso: test-vm.sh <nome> [<ensaio>]"
# Antes de qualquer outra coisa, como no vm.sh: o nome vira usuário, caminhos e unit. Com LC_ALL=C,
# [a-z] é só a-z em qualquer locale
(LC_ALL=C && [[ $1 =~ $DB_NAME_RE ]]) || die "nome da aplicação inválido: '$1' (regra do infra/databases.txt)"
APP=$1
ensaio=${2:-}
if [[ -n $ensaio && ! -f $ensaio ]]; then
  die "ensaio $ensaio não existe"
fi
BACKEND=$(cd "$here/../.." && pwd)/apps/$APP/backend
[[ -f $BACKEND/.python-version ]] || die "$BACKEND/.python-version não existe"

require_root
deploy_user=${SUDO_USER:?rode com sudo, a partir do usuário que faz o papel do usuário de deploy}
[[ $deploy_user != root ]] || die "rode com sudo a partir de um usuário comum"

APP_USER=app-$APP
test_unit=$APP-deploy-test.service
sha=0123456789abcdef0123456789abcdef01234567

fail() {
  echo "::error::$*"
  exit 1
}

TEST_ROOT=$(mktemp -d)
OUT=$TEST_ROOT/out
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
  rm -rf "$TEST_ROOT"
}
trap cleanup EXIT
# Percorrível pelo app-<nome> e pelo usuário de deploy, como /opt, /var/www e /var/lib na VM
chmod 0755 "$TEST_ROOT"

APP_DIR=$TEST_ROOT/opt/apps/$APP
web_dir=$TEST_ROOT/www/$APP
DB=$TEST_ROOT/sqlite/$APP/app.db
BACKUP_DIR=$TEST_ROOT/backups/$APP
config=$TEST_ROOT/etc/config.env

# vm.sh pelo stdin, como o workflow manda pelo SSH, rodado pelo usuário de deploy, com o nome de
# aplicação $1
vm_named() {
  local name=$1
  shift
  runuser -u "$deploy_user" -- env \
    DEPLOY_UNIT="${unit:-app-$APP.service}" DEPLOY_APP_DIR="$APP_DIR" DEPLOY_WEB_DIR="$web_dir" \
    DEPLOY_DB="$DB" DEPLOY_BACKUP_DIR="$BACKUP_DIR" DEPLOY_INFRA_CONFIG="$config" \
    bash -s -- "$name" "$@" < "$here/vm.sh"
}
vm() { vm_named "$APP" "$@"; }

# Saída de uma falha esperada, recuada: um "::error::" no começo da linha viraria anotação de erro
# no Actions, num job que passou
show() { sed 's/^/    | /' "$1"; }

expect_failure() {
  local message=$1
  shift
  if "$@" >"$OUT" 2>&1; then
    show "$OUT"
    fail "deveria falhar: $*"
  fi
  show "$OUT"
  grep -qF -- "$message" "$OUT" || fail "mensagem esperada: $message"
}

# Mesmas opções do passo "Enviar o backend" do workflow da aplicação
push_backend() {
  runuser -u "$deploy_user" -- rsync -rlpt --chmod=D0755,F0644 --delete \
    --filter="merge $here/backend.rsync-filter" "$BACKEND/" "$APP_DIR/"
}

as_app() { runuser -u "$APP_USER" -- "$@"; }

echo "=== vm.sh com $APP"
echo "--- uv e Python como o provision instala"
install_uv
install_pythons
python_version=$(<"$BACKEND/.python-version")

echo "--- pastas e banco como o provision cria"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -m 0755 "$TEST_ROOT/opt" "$TEST_ROOT/opt/apps" "$TEST_ROOT/www" "$TEST_ROOT/sqlite" \
  "$TEST_ROOT/backups" "$TEST_ROOT/etc"
install -d -m 0755 -o "$deploy_user" -g "$deploy_user" "$APP_DIR" "$web_dir"
install -d -m 0750 -o "$APP_USER" -g "$APP_USER" "$(dirname "$DB")"
install -d -m 0700 -o "$APP_USER" -g "$APP_USER" "$BACKUP_DIR"
as_app sqlite3 "$DB" 'PRAGMA journal_mode=WAL;' >/dev/null
cp "$INFRA_DIR/config.env" "$config"

echo "--- nome da aplicação inválido: recusa antes de qualquer passo"
expect_failure "nome da aplicação inválido" vm_named "../$APP" backup "$sha"
expect_failure "nome da aplicação inválido" vm_named "${APP^}" check "$python_version"
expect_failure "uso:" vm_named "$APP"
[[ -z $(find "$BACKUP_DIR" -mindepth 1 -print -quit) ]] || fail "um nome recusado gravou em $BACKUP_DIR"

echo "--- check: sem a unit, falha pedindo o Infra"
expect_failure "app-$APP.service não está instalada na VM: rode o workflow Infra" vm check "$python_version"

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
[[ -x $APP_DIR/.venv/bin/uvicorn ]] || fail ".venv sem uvicorn"
python=$(readlink -f "$APP_DIR/.venv/bin/python")
[[ $python == "$UV_PYTHON_INSTALL_DIR"/* ]] || fail "a .venv usa $python, fora de $UV_PYTHON_INSTALL_DIR"
[[ $("$APP_DIR/.venv/bin/python" --version) == "Python $python_version" ]] || fail "Python da .venv errado"
compgen -G "$APP_DIR/app/__pycache__/*.pyc" >/dev/null || fail "app/ sem bytecode"
compgen -G "$APP_DIR/migrations/versions/__pycache__/*.pyc" >/dev/null || fail "migrations/ sem bytecode"
[[ -n $(find "$APP_DIR/.venv/lib" -name '*.pyc' -print -quit) ]] || fail "pacotes da .venv sem bytecode"
if "$APP_DIR/.venv/bin/python" -c 'import pytest' 2>/dev/null; then
  fail "dependência de dev (pytest) instalada"
fi
[[ ! -e $APP_DIR/tests ]] || fail "tests/ foi para a VM"
writable=$(find "$APP_DIR" ! -type l -perm /022 -print -quit)
[[ -z $writable ]] || fail "gravável por grupo ou outros: $writable"
not_deploy=$(find "$APP_DIR" ! -user "$deploy_user" -print -quit)
[[ -z $not_deploy ]] || fail "sem dono $deploy_user: $not_deploy"

echo "--- migração e API como o $APP_USER, como o ExecStartPre e o ExecStart da unit"
as_app env -C "$APP_DIR" PYTHONDONTWRITEBYTECODE=1 DATABASE_PATH="$DB" .venv/bin/alembic upgrade head
head_revision=$(basename "$(find "$BACKEND/migrations/versions" -name '[0-9]*.py' | sort | tail -n1)")
head_revision=${head_revision%%_*}
[[ $(vm revision) == "$head_revision" ]] || fail "revision: '$(vm revision)', esperado $head_revision"
# Config de dev do .env.example, com o banco do teste. Copiado para fora da home do runner, que o
# app-<nome> não lê
install -m 0644 "$BACKEND/.env.example" "$TEST_ROOT/app.env"
# shellcheck disable=SC2016 # $1, $2 e $3 são expandidos pelo bash -c, não aqui
as_app env -C "$APP_DIR" PYTHONDONTWRITEBYTECODE=1 bash -c 'set -a && source "$1" && DATABASE_PATH=$2 &&
  exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 3999 --root-path "/api/$3"' \
  uvicorn "$TEST_ROOT/app.env" "$DB" "$APP" >"$TEST_ROOT/uvicorn.log" 2>&1 &
uvicorn_pid=$!
for _ in $(seq 1 40); do
  if body=$(curl -fsS --max-time 2 http://127.0.0.1:3999/health 2>/dev/null); then
    break
  fi
  sleep 0.5
done
[[ ${body:-} == '{"status":"ok"}' ]] || { cat "$TEST_ROOT/uvicorn.log"; fail "/health não respondeu ok: '${body:-}'"; }
kill "$uvicorn_pid"
wait "$uvicorn_pid" 2>/dev/null || true
uvicorn_pid=""

echo "--- backup pré-deploy"
vm backup "$sha"
first=$BACKUP_DIR/pre-deploy-$sha.db
[[ -f $first ]] || fail "$first não existe"
[[ $(stat -c '%U %a' "$first") == "$APP_USER 600" ]] || fail "$first: $(stat -c '%U %a' "$first"), esperado $APP_USER 600"
[[ $(as_app sqlite3 "$first" 'PRAGMA integrity_check;') == ok ]] || fail "backup corrompido"
[[ $(as_app sqlite3 "$first" 'PRAGMA journal_mode;') == delete ]] || fail "backup ainda em WAL"
[[ $(as_app sqlite3 "$first" 'SELECT version_num FROM alembic_version;') == "$head_revision" ]] || fail "backup sem a revisão"
compgen -G "$BACKUP_DIR/*.partial" >/dev/null && fail "sobrou um .partial"
compgen -G "$BACKUP_DIR/*-wal" >/dev/null && fail "backup com -wal ao lado"
before=$(sha256sum "$first")

echo "--- o mesmo commit de novo: o primeiro backup fica, o novo ganha a hora no nome"
vm backup "$sha"
[[ $(sha256sum "$first") == "$before" ]] || fail "o segundo backup sobrescreveu o primeiro"
count=$(find "$BACKUP_DIR" -name "pre-deploy-$sha-*.db" | wc -l)
((count == 1)) || fail "esperado 1 backup com a hora no nome, achados $count"
expect_failure "sha inválido" vm backup "abc; rm -rf /"
expect_failure "uso:" vm backup

echo "--- deploy seguinte: .venv fica, arquivo que saiu do repo sai da VM, bytecode refeito"
runuser -u "$deploy_user" -- touch "$APP_DIR/app/removido.py" "$APP_DIR/.env"
runuser -u "$deploy_user" -- mkdir -p "$APP_DIR/app/__pycache__"
runuser -u "$deploy_user" -- touch "$APP_DIR/app/__pycache__/removido.cpython-314.pyc"
venv_before=$(stat -c %i "$APP_DIR/.venv/bin/python")
push_backend
[[ ! -e $APP_DIR/app/removido.py ]] || fail "o --delete não tirou app/removido.py"
[[ ! -e $APP_DIR/.env ]] || fail "o --delete não tirou o .env"
[[ ! -e $APP_DIR/app/__pycache__/removido.cpython-314.pyc ]] || fail "bytecode velho ficou"
[[ $(stat -c %i "$APP_DIR/.venv/bin/python") == "$venv_before" ]] || fail "o rsync mexeu na .venv"
vm install
compgen -G "$APP_DIR/app/__pycache__/*.pyc" >/dev/null || fail "bytecode não foi refeito"

echo "--- restart: unit que sobe e unit cujo ExecStartPre falha (migração quebrada)"
cat > "/etc/systemd/system/$test_unit" <<EOF
[Service]
Type=exec
ExecStartPre=/usr/bin/test -e $TEST_ROOT/start-ok
ExecStart=/usr/bin/sleep infinity
EOF
systemctl daemon-reload
unit=$test_unit
expect_failure "$test_unit não subiu (migração ou subida falhou)" vm restart
touch "$TEST_ROOT/start-ok"
vm restart | tee "$OUT"
grep -q "$test_unit reiniciada" "$OUT" || fail "restart sem a mensagem de sucesso"
systemctl is-active --quiet "$test_unit" || fail "$test_unit não ficou ativa"
systemctl stop "$test_unit"

if [[ -n $ensaio ]]; then
  echo "=== ensaio de $APP: $ensaio"
  # shellcheck source=/dev/null
  source "$ensaio"
fi

echo "=== restore-test.sh (backup-verify.yaml) com o banco de $APP e um litestream falso"
for path in "${vm_paths[@]}"; do
  [[ ! -e $path ]] || fail "$path já existe: o teste do restore-test.sh só roda num runner limpo"
done
created_vm_paths=1
install -D -m 0644 "$INFRA_DIR/lib/common.sh" /usr/local/lib/infra/common.sh
install -d -m 0755 /etc/infra /var/lib/sqlite /var/backups/sqlite /etc/default
printf '%s\n' "$APP" > /etc/infra/databases
install -d -m 0750 -o "$APP_USER" -g "$APP_USER" "/var/lib/sqlite/$APP"
install -d -m 0700 -o "$APP_USER" -g "$APP_USER" "/var/backups/sqlite/$APP"
as_app sqlite3 "$DB" ".backup /var/lib/sqlite/$APP/app.db"
as_app sqlite3 "/var/lib/sqlite/$APP/app.db" 'PRAGMA journal_mode=WAL;' >/dev/null
: > /etc/default/litestream
printf 'dbs: []\n' > /etc/litestream.yml
# O restore do Object Storage vira uma cópia do banco vivo (ninguém escreve nele: sem -wal).
# Com LITESTREAM_FALSO=incompleto, entrega o banco sem a tabela do Alembic, que toda aplicação tem
cat > /usr/local/bin/litestream <<'EOF'
#!/bin/bash
set -euo pipefail
[[ $# == 6 && $1 == restore && $2 == -config && $4 == -o ]] || { echo "litestream falso: $*" >&2; exit 2; }
cp "$6" "$5"
if [[ ${LITESTREAM_FALSO:-} == incompleto ]]; then
  sqlite3 "$5" 'DROP TABLE alembic_version;'
fi
EOF
chmod 0755 /usr/local/bin/litestream
bash "$INFRA_DIR/scripts/snapshot.sh"
bash "$INFRA_DIR/scripts/restore-test.sh" | tee "$OUT"
grep -qF "$APP: restauração ok" "$OUT" || fail "restore-test.sh não validou $APP"
expect_failure "objetos no restaurado" env LITESTREAM_FALSO=incompleto bash "$INFRA_DIR/scripts/restore-test.sh"
# Só um pre-deploy recente, sem o snapshot diário: um snapshot.sh parado não pode passar
rm "/var/backups/sqlite/$APP/"[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].db
as_app cp "$first" "/var/backups/sqlite/$APP/pre-deploy-$sha.db"
expect_failure "$APP: nenhum snapshot local nas últimas 26h" bash "$INFRA_DIR/scripts/restore-test.sh"

echo "ok"
