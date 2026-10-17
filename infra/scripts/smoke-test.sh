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
sql_is() { [[ $(runuser -u "$1" -- sqlite3 "$2" "$3") == "$4" ]]; }

check "swap ativo" grep -q '^/swapfile ' /proc/swaps
check "nginx ativo" systemctl is-active --quiet nginx
check "site responde em https://$SITE_DOMAIN/" \
  curl -fsS -o /dev/null --max-time 10 --resolve "$SITE_DOMAIN:443:127.0.0.1" "https://$SITE_DOMAIN/"
check "timer de snapshot ativo" systemctl is-active --quiet sqlite-snapshot.timer
check "timer de keep-alive ativo" systemctl is-active --quiet keepalive.timer

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

log "memória: $(free -m | awk '/^Mem:/ {print $7 " MiB disponíveis de " $2}'), swap em uso: $(free -m | awk '/^Swap:/ {print $3}') MiB"

((failures == 0)) || die "$failures checagem(ns) falharam"
