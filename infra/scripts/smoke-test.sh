#!/usr/bin/env bash
# Checagens rodadas no fim de cada provision. Sai com erro se alguma falhar.
# Instalado em /usr/local/lib/infra/smoke-test.sh.
set -euo pipefail
# shellcheck source=../lib/common.sh
source /usr/local/lib/infra/common.sh
# shellcheck source=../config.env
source "$INFRA_STATE_DIR/config.env"

require_root
load_databases "$INFRA_STATE_DIR/databases"

failures=0
check() {
  local desc=$1
  shift
  if "$@" >/dev/null 2>&1; then
    log "ok     $desc"
  else
    log "FALHOU $desc"
    failures=$((failures + 1))
  fi
}

owner_is() { [[ $(stat -c %U "$1") == "$2" ]]; }
secret_file_ok() { [[ -f $1 && ! -L $1 && $(stat -c '%U:%G %a' "$1") == "root:root 600" ]]; }
sql_is() { [[ $(runuser -u "$1" -- sqlite3 "$2" "$3") == "$4" ]]; }
site_get() { curl -fsS --max-time 10 --resolve "$SITE_DOMAIN:443:127.0.0.1" "$@"; }
app_serves_index() { [[ $(site_get "https://$SITE_DOMAIN/$1/") == "$(cat "/var/www/$1/index.html")" ]]; }
app_health_ok() {
  [[ $(site_get -o /dev/null -w '%{http_code} %{content_type}' "https://$SITE_DOMAIN/api/$1/health") \
    == "200 application/json"* ]]
}
uv_is() {
  local v
  v=$(/usr/local/bin/uv --version) && [[ $v == "uv $1" || $v == "uv $1 "* ]]
}

check "swap ativo" grep -q '^/swapfile ' /proc/swaps
check "nginx ativo" systemctl is-active --quiet nginx
check "site responde em https://$SITE_DOMAIN/" \
  curl -fsS -o /dev/null --max-time 10 --resolve "$SITE_DOMAIN:443:127.0.0.1" "https://$SITE_DOMAIN/"
check "timer de snapshot ativo" systemctl is-active --quiet sqlite-snapshot.timer
check "timer de keep-alive ativo" systemctl is-active --quiet keepalive.timer
check "uv $UV_VERSION instalado" uv_is "$UV_VERSION"

if ((${#DATABASES[@]})); then
  check "litestream ativo" systemctl is-active --quiet litestream
fi

for name in "${DATABASES[@]}"; do
  user="app-$name"
  db="$SQLITE_ROOT/$name/app.db"
  check "$name: app.db pertence a $user" owner_is "$db" "$user"
  check "$name: journal_mode=wal" sql_is "$user" "$db" 'PRAGMA journal_mode;' wal
  check "$name: integrity_check" sql_is "$user" "$db" 'PRAGMA integrity_check;' ok
  check "$name: está no /etc/litestream.yml" grep -qF "path: $db" /etc/litestream.yml
  # se o root criar o -wal/-shm, o app perde permissão de escrita
  for f in "$db-wal" "$db-shm"; do
    if [[ -e $f ]]; then
      check "$name: $(basename "$f") pertence a $user" owner_is "$f" "$user"
    fi
  done
done

# Aplicações publicadas (rotas no nginx e frontend no ar), o imago inclusive. O location / do site
# devolve o index.html com 200 para qualquer caminho, então não basta o status: o frontend tem de
# ser o da aplicação e o health tem de responder 200 com JSON
for manifest in "$INFRA_STATE_DIR"/apps/*.units; do
  [[ -f $manifest ]] || continue
  name=$(basename "$manifest" .units)
  [[ -f /etc/nginx/apps.d/$name.conf && -f /var/www/$name/index.html ]] || continue
  check "$name: /$name/ serve o frontend da aplicação" app_serves_index "$name"
  check "$name: /api/$name/health responde 200 com JSON" app_health_ok "$name"
done

# A API das aplicações com auth_request pergunta ao imago quem é o usuário: sem ele no ar, responde
# 500 (menos o /health). Antes do primeiro deploy do imago (VM nova), só avisa
for conf in /etc/nginx/apps.d/*.conf; do
  [[ -f $conf ]] || continue
  grep -qE '^[[:space:]]*auth_request[[:space:]]+/_imago/session;' "$conf" || continue
  name=$(basename "$conf" .conf)
  if [[ -e /opt/apps/$IMAGO_APP/.venv/bin/uvicorn ]]; then
    check "$name: app-$IMAGO_APP no ar (auth_request da API)" systemctl is-active --quiet "app-$IMAGO_APP"
  else
    warn "$name: a API pergunta ao $IMAGO_APP quem é o usuário, mas ele ainda não foi publicado: responde 500 até o deploy dele"
  fi
done

# Tokens da API interna: só o root lê (os valores nunca são lidos aqui)
if [[ -f $INFRA_STATE_DIR/apps/$IMAGO_APP.units ]]; then
  check "$INTERNAL_DIR/$IMAGO_APP.env existe" test -f "$INTERNAL_DIR/$IMAGO_APP.env"
fi
for token_file in "$INTERNAL_DIR"/*.env; do
  [[ -e $token_file ]] || continue
  check "$token_file: root 600" secret_file_ok "$token_file"
done

log "memória: $(free -m | awk '/^Mem:/ {print $7 " MiB disponíveis de " $2}'), swap em uso: $(free -m | awk '/^Swap:/ {print $3}') MiB"

((failures == 0)) || die "$failures checagem(ns) falharam"
