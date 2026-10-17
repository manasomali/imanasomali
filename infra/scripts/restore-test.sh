#!/usr/bin/env bash
# Restaura cada banco do Object Storage para uma pasta temporária e valida o resultado.
# Roda pelo workflow backup-verify.yaml. Instalado em /usr/local/lib/infra/restore-test.sh.
set -euo pipefail
# shellcheck source=../lib/common.sh
source /usr/local/lib/infra/common.sh

SNAPSHOT_MAX_AGE_MIN=$((26 * 60))

require_root
load_databases "$INFRA_STATE_DIR/databases"

if ((${#DATABASES[@]} == 0)); then
  log "nenhum banco em databases.txt; nada para verificar"
  exit 0
fi

set -a
# shellcheck source=/dev/null
source /etc/default/litestream
set +a

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

status=0
fail() {
  warn "$*"
  status=1
}

for name in "${DATABASES[@]}"; do
  db="$SQLITE_ROOT/$name/app.db"
  out="$workdir/$name.db"

  live_tables=$(runuser -u "app-$name" -- sqlite3 "$db" 'SELECT count(*) FROM sqlite_master;')
  if ((live_tables == 0)); then
    log "$name: banco ainda vazio, nada para restaurar"
    continue
  fi

  if ! /usr/local/bin/litestream restore -config /etc/litestream.yml -o "$out" "$db"; then
    fail "$name: litestream restore falhou"
    continue
  fi

  check=$(sqlite3 "$out" 'PRAGMA integrity_check;')
  restored_tables=$(sqlite3 "$out" 'SELECT count(*) FROM sqlite_master;')
  if [[ $check != ok ]]; then
    fail "$name: integrity_check do restaurado = $check"
  elif ((restored_tables != live_tables)); then
    fail "$name: $restored_tables objetos no restaurado, $live_tables no banco vivo"
  else
    log "$name: restauração ok ($restored_tables objetos, $(du -h "$out" | cut -f1))"
  fi

  latest=$(find "$BACKUP_ROOT/$name" -type f -name '*.db' -mmin -"$SNAPSHOT_MAX_AGE_MIN" 2>/dev/null | head -n1 || true)
  if [[ -z $latest ]]; then
    fail "$name: nenhum snapshot local nas últimas 26h"
  fi
done

exit "$status"
