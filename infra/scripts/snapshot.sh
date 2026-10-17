#!/usr/bin/env bash
# Snapshot diário de cada banco em /var/backups/sqlite/<nome>/AAAA-MM-DD.db, com retenção de 7 dias.
# Roda pelo sqlite-snapshot.timer. Instalado em /usr/local/lib/infra/snapshot.sh.
set -euo pipefail
# shellcheck source=../lib/common.sh
source /usr/local/lib/infra/common.sh

KEEP_DAYS=7

require_root
load_databases "$INFRA_STATE_DIR/databases"

status=0
for name in "${DATABASES[@]}"; do
  db="$SQLITE_ROOT/$name/app.db"
  dir="$BACKUP_ROOT/$name"
  out="$dir/$(date -u +%F).db"

  if [[ ! -f $db ]]; then
    warn "$db não existe"
    status=1
    continue
  fi

  # Roda como o usuário do app: se o root abrir o banco, o -wal/-shm pode nascer com dono root
  user="app-$name"
  install -d -m 0700 -o "$user" -g "$user" "$dir"
  rm -f "$out"
  # .backup é consistente mesmo com o app escrevendo; cp do arquivo não é
  runuser -u "$user" -- sqlite3 "$db" ".backup '$out'"
  # snapshot vira arquivo único (sem -wal/-shm ao lado)
  runuser -u "$user" -- sqlite3 "$out" 'PRAGMA journal_mode=DELETE;' >/dev/null
  chmod 0600 "$out"

  result=$(runuser -u "$user" -- sqlite3 "$out" 'PRAGMA integrity_check;')
  if [[ $result != ok ]]; then
    warn "integrity_check falhou em $out: $result"
    status=1
    continue
  fi

  find "$dir" -type f -name '*.db' -mtime +$((KEEP_DAYS - 1)) -delete
  log "snapshot ok: $out ($(du -h "$out" | cut -f1))"
done

exit "$status"
