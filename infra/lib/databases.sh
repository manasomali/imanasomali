# Um usuário de sistema e uma pasta por banco de databases.txt. Nunca apaga nada.

provision_databases() {
  local name user dir db
  local -A wanted=()

  install -d -m 0755 -o root -g root "$SQLITE_ROOT"

  for name in "${DATABASES[@]}"; do
    wanted[$name]=1
    user="app-$name"
    dir="$SQLITE_ROOT/$name"
    db="$dir/app.db"

    if ! id "$user" >/dev/null 2>&1; then
      useradd --system --user-group --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin "$user"
      log "usuário criado: $user"
    fi

    # A pasta precisa ser gravável pelo app: o WAL cria app.db-wal e app.db-shm ao lado do banco.
    install -d -m 0750 -o "$user" -g "$user" "$dir"

    if [[ ! -f $db ]]; then
      # journal_mode=WAL fica gravado no arquivo; os apps não precisam ativar de novo
      runuser -u "$user" -- sqlite3 "$db" 'PRAGMA journal_mode=WAL;' >/dev/null
      log "banco criado: $db"
    fi
  done

  for dir in "$SQLITE_ROOT"/*/; do
    [[ -d $dir ]] || continue
    name=$(basename "$dir")
    if [[ -z ${wanted[$name]:-} ]]; then
      warn "${dir%/} não está em databases.txt: dados mantidos, mas SEM backup"
    fi
  done
}
