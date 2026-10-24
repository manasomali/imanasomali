# Funções compartilhadas pelo provision.sh e pelos scripts que rodam na VM.
# Também é instalado em /usr/local/lib/infra/common.sh.

INFRA_STATE_DIR=/etc/infra
INFRA_LIB_DIR=/usr/local/lib/infra
SQLITE_ROOT=/var/lib/sqlite
BACKUP_ROOT=/var/backups/sqlite
# app-<nome> precisa caber no limite de 32 caracteres de usuário do Linux
DB_NAME_RE='^[a-z][a-z0-9-]{1,26}$'

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"; }
warn() { log "AVISO: $*" >&2; }
die() { log "ERRO: $*" >&2; exit 1; }

require_root() { [[ $EUID -eq 0 ]] || die "rode como root (sudo)"; }

# Imprime os nomes de banco válidos de um arquivo (um por linha, # comenta). Falha em nome inválido.
read_databases() {
  local file=$1 line name
  local -A seen=()
  [[ -f $file ]] || return 0
  while IFS= read -r line || [[ -n $line ]]; do
    name=${line%%#*}
    name=${name//[[:space:]]/}
    [[ -z $name ]] && continue
    [[ $name =~ $DB_NAME_RE ]] || die "nome de banco inválido em $file: '$name'"
    [[ -n ${seen[$name]:-} ]] && continue
    seen[$name]=1
    printf '%s\n' "$name"
  done < "$file"
}

# Preenche o array global DATABASES a partir de um arquivo.
load_databases() {
  local list
  list=$(read_databases "$1") || exit 1
  DATABASES=()
  if [[ -n $list ]]; then
    mapfile -t DATABASES <<< "$list"
  fi
}

# Lê KEY de um arquivo KEY=VALUE sem executá-lo. Imprime vazio se não existir.
env_get() {
  if [[ -f $1 ]]; then
    sed -n "s/^$2=//p" "$1" | tail -n1
  fi
  return 0
}

# Instala $1 em $2 (dono root) se o conteúdo mudou. Retorna 0 se mudou, 1 se já estava igual.
sync_file() {
  local src=$1 dest=$2 mode=${3:-0644}
  if [[ -f $dest ]] && cmp -s "$src" "$dest"; then
    chmod "$mode" "$dest"
    chown root:root "$dest"
    return 1
  fi
  install -D -m "$mode" -o root -g root "$src" "$dest"
  log "atualizado: $dest"
}

# Como sync_file, mas o conteúdo vem do stdin.
sync_content() {
  local dest=$1 mode=${2:-0644} tmp rc=0
  tmp=$(mktemp)
  cat > "$tmp"
  sync_file "$tmp" "$dest" "$mode" || rc=$?
  rm -f "$tmp"
  return "$rc"
}

# Garante a pasta $1 com modo $2 e dono $3 (grupo de mesmo nome). Não mexe no conteúdo.
# Retorna 0 se criou ou corrigiu, 1 se já estava certa.
sync_dir() {
  local dir=$1 mode=$2 owner=$3
  if [[ ! -d $dir ]]; then
    install -d -m "$mode" -o "$owner" -g "$owner" "$dir"
    log "criado: $dir ($owner $mode)"
    return 0
  fi
  if [[ $(stat -c '%U:%G %a' "$dir") == "$owner:$owner ${mode#0}" ]]; then
    return 1
  fi
  chown "$owner:$owner" "$dir"
  chmod "$mode" "$dir"
  log "atualizado: $dir ($owner $mode)"
}
