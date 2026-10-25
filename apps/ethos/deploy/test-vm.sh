#!/usr/bin/env bash
# Testa o vm.sh num runner Ubuntu 24.04 (o sistema da VM), sem SSH: uv e Python instalados pelas
# funções do provision (infra/lib/packages.sh), o usuário que chamou o sudo no papel do usuário de
# deploy (sudo sem senha, como o ubuntu da VM), app-ethos dono do banco e o rsync do backend com o
# mesmo backend.rsync-filter do workflow. As pastas da VM ficam numa pasta temporária.
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
cleanup() {
  if [[ -n $uvicorn_pid ]]; then
    kill "$uvicorn_pid" 2>/dev/null || true
  fi
  systemctl stop "$test_unit" 2>/dev/null || true
  rm -f "/etc/systemd/system/$test_unit"
  systemctl daemon-reload
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

expect_failure() {
  local message=$1
  shift
  if "$@" >"$out" 2>&1; then
    cat "$out"
    fail "deveria falhar: $*"
  fi
  cat "$out"
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

echo "ok"
