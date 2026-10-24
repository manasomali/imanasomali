# Config recebida pelo stdin (KEY=VALUE, uma por linha, enviada pelo CI) e gravada em arquivos
# de ambiente. Os valores nunca aparecem em log nem em mensagem de erro: muitos são segredos.

declare -A INPUT=()

# Regra de cada chave aceita no stdin. Retorna 2 para chave desconhecida, 1 para valor inválido.
input_valid() {
  local key=$1 value=$2
  ((${#value} <= 1024)) || return 1
  case $key in
    LITESTREAM_ACCESS_KEY_ID | LITESTREAM_SECRET_ACCESS_KEY | S3_ENDPOINT | S3_BUCKET | OCI_REGION)
      [[ $value =~ ^[A-Za-z0-9._:/+=-]+$ ]]
      ;;
    SMTP_HOST)
      [[ $value =~ ^[A-Za-z0-9.-]+$ ]]
      ;;
    SMTP_PORT)
      [[ $value =~ ^[0-9]{1,5}$ ]] && ((10#$value >= 1 && 10#$value <= 65535))
      ;;
    SMTP_USER | SMTP_PASSWORD)
      # Qualquer caractere visível, inclusive espaço, aspas, $ e @. Controle (tab, \r) não
      [[ -n $value && $value != *[[:cntrl:]]* ]]
      ;;
    *)
      return 2
      ;;
  esac
}

# Lê o stdin para INPUT. Valor vazio é ignorado: o arquivo mantém o valor atual.
read_stdin_config() {
  local line key value rc
  [[ -t 0 ]] && return 0
  while IFS= read -r line || [[ -n $line ]]; do
    [[ -z $line ]] && continue
    key=${line%%=*}
    # Sem "=" ou com chave fora do padrão, a linha pode ser o resto de um segredo que tinha
    # quebra de linha: não mostra o conteúdo
    if [[ $line != *=* || ! $key =~ ^[A-Z][A-Z0-9_]*$ ]]; then
      die "linha inválida no stdin (conteúdo omitido): algum valor tem quebra de linha?"
    fi
    value=${line#*=}
    rc=0
    input_valid "$key" "$value" || rc=$?
    ((rc != 2)) || die "chave desconhecida no stdin: $key"
    [[ -n $value ]] || continue
    ((rc == 0)) || die "valor inválido em $key (conteúdo omitido)"
    INPUT[$key]=$value
  done
}

# Valor no formato do EnvironmentFile= do systemd. Só com caracteres seguros, vai sem aspas
# (o formato que o provision sempre gravou); senão, entre aspas duplas com \ " $ ` escapados.
# O systemd não expande variáveis nesses arquivos, e o bash lê as aspas duplas do mesmo jeito.
env_quote() {
  local v=$1
  if [[ $v =~ ^[A-Za-z0-9._:/+=@,-]+$ ]]; then
    printf '%s' "$v"
    return
  fi
  v=${v//\\/\\\\}
  v=${v//\"/\\\"}
  v=${v//\$/\\\$}
  v=${v//\`/\\\`}
  printf '"%s"' "$v"
}

# Grava as chaves dadas em $1 (modo $2), com o valor do stdin ou, sem ele, a linha atual do
# arquivo como está. Retorna 0 se o arquivo mudou, 1 se ficou igual ou não há nenhum valor.
write_env_file() {
  local dest=$1 mode=$2 key line content=""
  shift 2
  for key in "$@"; do
    if [[ -n ${INPUT[$key]:-} ]]; then
      line="$key=$(env_quote "${INPUT[$key]}")"
    else
      line=$(grep "^$key=" "$dest" 2>/dev/null | tail -n1 || true)
    fi
    if [[ -n $line ]]; then
      content+="$line"$'\n'
    fi
  done
  [[ -n $content ]] || return 1
  printf '%s' "$content" | sync_content "$dest" "$mode"
}
