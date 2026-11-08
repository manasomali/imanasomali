# Uma aplicação por pasta em infra/apps/<nome>/ (ver apps/README.md). Nunca apaga dados nem código.

UNIT_DIR=/etc/systemd/system

# Nomes das aplicações em infra/apps/, um por linha. Falha em nome fora da regra do databases.txt.
read_apps() {
  local dir name
  for dir in "$INFRA_DIR"/apps/*/; do
    [[ -d $dir ]] || continue
    name=$(basename "$dir")
    [[ $name =~ $DB_NAME_RE ]] || die "nome de aplicação inválido em infra/apps/: '$name'"
    printf '%s\n' "$name"
  done
}

provision_apps() {
  local name apps reload=0
  local -A config_changed=() units_changed=()

  id "$DEPLOY_USER" >/dev/null 2>&1 || die "usuário de deploy '$DEPLOY_USER' (config.env) não existe"
  apps=$(read_apps) || exit 1
  remove_old_apps "$apps"
  [[ -n $apps ]] || return 0

  sync_dir /opt/apps 0755 root || true
  sync_dir "$INFRA_STATE_DIR/apps" 0755 root || true
  check_smtp_env "$apps"
  if sync_file "$INFRA_DIR/systemd/infra-unit-failed@.service" "$UNIT_DIR/infra-unit-failed@.service"; then
    reload=1
  fi

  while IFS= read -r name; do
    # Código do backend: o deploy grava, o app-<nome> só lê (não consegue alterar o próprio código)
    sync_dir "/opt/apps/$name" 0755 "$DEPLOY_USER" || true
    # Frontend: o deploy grava, o nginx lê. Fora de /var/www/html, que o deploy do site limpa com --delete
    sync_dir "/var/www/$name" 0755 "$DEPLOY_USER" || true
    check_deploy_sudo "$name"

    if install_app_env "$name"; then
      config_changed[$name]=1
    fi
    # Credenciais SMTP novas reiniciam só quem lê o smtp.env
    if ((${SMTP_CHANGED:-0})) && app_reads_env_file "$name" "$INFRA_STATE_DIR/smtp.env"; then
      config_changed[$name]=1
    fi
    if install_app_units "$name"; then
      units_changed[$name]=1
      reload=1
    fi
  done <<< "$apps"

  # Antes de subir as units: elas leem esses arquivos com EnvironmentFile= (sem eles, não sobem)
  install_internal_tokens "$apps"
  for name in "${TOKENS_CHANGED[@]}"; do
    if app_reads_env_file "$name" "$INTERNAL_DIR/$name.env"; then
      config_changed[$name]=1
    fi
  done

  if ((reload)); then
    systemctl daemon-reload
  fi
  while IFS= read -r name; do
    start_app_units "$name" "${config_changed[$name]:-0}" "${units_changed[$name]:-0}"
  done <<< "$apps"
}

# Config não secreta de infra/apps/<nome>/app.env em /etc/infra/apps/<nome>.env (EnvironmentFile=).
# Retorna 0 se o arquivo instalado mudou.
install_app_env() {
  local name=$1 src="$INFRA_DIR/apps/$1/app.env" line
  [[ -f $src ]] || return 1

  while IFS= read -r line || [[ -n $line ]]; do
    [[ -z $line || $line == \#* ]] && continue
    [[ $line =~ ^[A-Z][A-Z0-9_]*= ]] || die "linha inválida em $src: $line"
    # Segredos vão pelos secrets do GitHub (stdin) ou nascem na VM, nunca versionados
    [[ $line != SMTP_* ]] || die "$src não pode ter ${line%%=*}: credenciais SMTP ficam em $INFRA_STATE_DIR/smtp.env"
    if [[ $line == INTERNAL_API_TOKEN=* || $line == IMAGO_APP_TOKENS=* ]]; then
      die "$src não pode ter ${line%%=*}: os tokens da API interna são gerados na VM, em $INTERNAL_DIR"
    fi
  done < "$src"

  sync_file "$src" "$INFRA_STATE_DIR/apps/$name.env" 0644
}

# Units de infra/apps/<nome>/ (*.service, *.timer) em /etc/systemd/system, com __PORTA__ trocado
# pelo PORT do app.conf. A lista instalada fica em /etc/infra/apps/<nome>.units, para desligar as
# units se a aplicação sair do repo. Retorna 0 se alguma unit mudou.
install_app_units() {
  local name=$1 dir="$INFRA_DIR/apps/$1" file unit port list="" changed=1

  port=$(env_get "$dir/app.conf" PORT)
  # Validada antes do sed: só dígitos entram no arquivo da unit
  if [[ -n $port ]] && ! valid_port "$port"; then
    die "PORT inválido em $dir/app.conf: '$port' (1024 a 65535)"
  fi
  for file in "$dir"/*.service "$dir"/*.timer; do
    [[ -f $file ]] || continue
    unit=$(basename "$file")
    # Uma aplicação só instala units com o próprio nome, nunca uma do sistema (nginx.service...)
    if [[ $unit != "app-$name.service" && $unit != "$name"-*.service && $unit != "$name"-*.timer ]]; then
      die "$file: as units de $name se chamam app-$name.service ou $name-*.service/.timer"
    fi
    if [[ -z $port ]] && grep -q __PORTA__ "$file"; then
      die "$file usa __PORTA__, mas $dir/app.conf não tem PORT"
    fi
    if sed "s/__PORTA__/$port/g" "$file" | sync_content "$UNIT_DIR/$unit" 0644; then
      changed=0
    fi
    list+="$unit"$'\n'
  done

  printf '%s' "$list" | sync_content "$INFRA_STATE_DIR/apps/$name.units" 0644 || true
  return "$changed"
}

# is-enabled também sai com 0 para units "static" (sem [Install]), que não se ligam nem desligam
unit_enabled() { [[ $(systemctl is-enabled "$1" 2>/dev/null || true) == enabled* ]]; }

valid_port() { [[ $1 =~ ^[0-9]{4,5}$ ]] && ((10#$1 >= 1024 && 10#$1 <= 65535)); }

# Liga as units da aplicação. O serviço principal reinicia se estiver rodando e a config ($2=1) ou
# alguma unit ($3=1) mudou; os timers, só se alguma unit mudou. Parado, o serviço sobe: sem a .venv
# (antes do primeiro deploy) o ConditionPathExists o deixa parado, sem erro. Os *.service disparados
# por timer não sobem aqui.
start_app_units() {
  local name=$1 config_changed=$2 units_changed=$3 unit restart
  [[ -f $INFRA_STATE_DIR/apps/$name.units ]] || return 0

  while IFS= read -r unit; do
    if [[ $unit != *.timer && $unit != "app-$name.service" ]]; then
      continue
    fi
    if ! unit_enabled "$unit"; then
      systemctl enable "$unit" >/dev/null 2>&1
      log "ligado: $unit"
    fi
    restart=$units_changed
    if [[ $unit == "app-$name.service" ]] && ((config_changed)); then
      restart=1
    fi
    if systemctl is-active --quiet "$unit"; then
      if ((restart)); then
        systemctl restart "$unit"
        log "reiniciado: $unit"
      fi
    elif systemctl start "$unit" 2>/dev/null; then
      if systemctl is-active --quiet "$unit"; then
        log "iniciado: $unit"
      fi
    else
      warn "$unit não subiu: veja journalctl -u $unit"
    fi
  done < "$INFRA_STATE_DIR/apps/$name.units"
}

# Aplicação que saiu de infra/apps/: desliga as units e tira as rotas do nginx (a config vai para
# /var/backups/infra). Código em /opt/apps/<nome>, frontend e banco ficam. Avisa a cada provision.
# O token da API interna dela sai do imago.env em seguida (install_internal_tokens).
remove_old_apps() {
  local apps=$1 manifest name unit conf nginx_changed=0

  for manifest in "$INFRA_STATE_DIR"/apps/*.units; do
    [[ -f $manifest ]] || continue
    name=$(basename "$manifest" .units)
    if grep -qx "$name" <<< "$apps"; then
      continue
    fi

    while IFS= read -r unit; do
      [[ -n $unit ]] || continue
      if unit_enabled "$unit" || systemctl is-active --quiet "$unit"; then
        systemctl disable --now "$unit" >/dev/null 2>&1
        log "desligado: $unit"
      fi
    done < "$manifest"

    for conf in "/etc/nginx/apps.d/$name.conf" "/etc/nginx/conf.d/$name.conf"; do
      [[ -f $conf ]] || continue
      install -d -m 0700 /var/backups/infra
      mv "$conf" "/var/backups/infra/nginx-$(basename "$(dirname "$conf")")-$name.conf.$(date -u +%Y%m%dT%H%M%SZ)"
      log "removido do nginx: $conf (cópia em /var/backups/infra)"
      nginx_changed=1
    done

    warn "$name saiu de infra/apps/: units desligadas e fora do nginx; código e dados mantidos"
  done

  if ((nginx_changed)); then
    nginx -t -q || die "nginx -t falhou depois de tirar as rotas de aplicações removidas"
    # Parado, o nginx lê a config nova ao subir (o provision_nginx sobe)
    if systemctl is-active --quiet nginx; then
      systemctl reload nginx
    fi
  fi
}

# Avisa se faltar alguma credencial SMTP (o secret não foi cadastrado no GitHub), quando alguma
# aplicação lê o smtp.env
check_smtp_env() {
  local apps=$1 name key readers=""
  while IFS= read -r name; do
    if app_reads_env_file "$name" "$INFRA_STATE_DIR/smtp.env"; then
      readers+=" $name"
    fi
  done <<< "$apps"
  [[ -n $readers ]] || return 0

  for key in SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD; do
    if ! grep -q "^$key=" "$INFRA_STATE_DIR/smtp.env" 2>/dev/null; then
      warn "$INFRA_STATE_DIR/smtp.env sem $key (lido por$readers): cadastre o secret no GitHub e rode o Infra"
    fi
  done
}

# 0 se o serviço principal da aplicação $1 (infra/apps/<nome>/app-<nome>.service) lê o arquivo $2
# com EnvironmentFile= (opcional, com "-", ou não). Só ele reinicia quando o arquivo muda: os jobs
# disparados por timer leem o arquivo de novo a cada execução
app_reads_env_file() {
  local unit="$INFRA_DIR/apps/$1/app-$1.service" file=$2 line
  [[ -f $unit ]] || return 1
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line//[[:space:]]/}
    if [[ $line == "EnvironmentFile=$file" || $line == "EnvironmentFile=-$file" ]]; then
      return 0
    fi
  done < "$unit"
  return 1
}

# Tokens da API interna (imago-plan.md, "API interna"), em $INTERNAL_DIR (0700, root):
# - <app>.env para cada aplicação de infra/apps/ menos o imago, com INTERNAL_API_TOKEN (32 bytes
#   aleatórios em base64url). Criado só se não existir: o provision seguinte não muda o arquivo, e
#   uma aplicação nova ganha o dela sem mudar o das outras. Apagar o arquivo troca o token;
# - imago.env com IMAGO_APP_TOKENS=<app>:<token>,... (ordem alfabética), montado a partir deles.
#   Uma aplicação que sai de infra/apps/ sai dele, e o token dela deixa de valer (o arquivo fica).
# Todos 0600 do root: o systemd lê como root. Os tokens nunca vão para log, argumento de processo
# nem mensagem de erro, e nunca saem da VM. Preenche TOKENS_CHANGED com as aplicações cujo arquivo
# nasceu agora e com o imago, se o imago.env mudou.
install_internal_tokens() {
  local apps=$1 name file token entries=""
  TOKENS_CHANGED=()

  sync_dir "$INTERNAL_DIR" 0700 root || true
  # LC_ALL=C: a mesma ordem em qualquer locale, senão o imago.env mudaria de um provision para outro
  while IFS= read -r name; do
    [[ -n $name && $name != "$IMAGO_APP" ]] || continue
    file=$INTERNAL_DIR/$name.env
    if [[ ! -e $file && ! -L $file ]]; then
      new_token_file "$file"
      log "criado: $file (token da API interna de $name)"
      TOKENS_CHANGED+=("$name")
    fi
    [[ -f $file && ! -L $file ]] || die "$file não é um arquivo comum"
    if [[ $(stat -c '%U:%G %a' "$file") != "root:root 600" ]]; then
      chown root:root "$file"
      chmod 0600 "$file"
      log "atualizado: $file (root 600)"
    fi
    token=$(<"$file")
    if [[ ! $token =~ ^INTERNAL_API_TOKEN=([A-Za-z0-9_-]{32,})$ ]]; then
      die "$file fora do formato INTERNAL_API_TOKEN=<base64url> (conteúdo omitido): apague-o e rode o provision de novo para gerar outro"
    fi
    entries+="$name:${BASH_REMATCH[1]},"
  done < <(LC_ALL=C sort <<< "$apps")

  if printf 'IMAGO_APP_TOKENS=%s\n' "${entries%,}" | sync_content "$INTERNAL_DIR/$IMAGO_APP.env" 0600; then
    TOKENS_CHANGED+=("$IMAGO_APP")
  fi
}

# Grava em $1 (que ainda não existe) um token novo, 0600 do root. O valor passa só por pipes e pelo
# printf do bash (builtin), nunca por argumento de um processo (visível no ps)
new_token_file() {
  local file=$1 token tmp
  token=$(head -c 32 /dev/urandom | base64 -w0 | tr '+/' '-_' | tr -d '=')
  [[ $token =~ ^[A-Za-z0-9_-]{43}$ ]] || die "não foi possível gerar o token de $file"
  tmp=$(mktemp "$INTERNAL_DIR/.token.XXXXXX")
  printf 'INTERNAL_API_TOKEN=%s\n' "$token" > "$tmp"
  chown root:root "$tmp"
  chmod 0600 "$tmp"
  mv -f "$tmp" "$file"
}

# O deploy de uma aplicação roda, com sudo -n: systemctl restart app-<nome> e sqlite3 como
# app-<nome> (backup pré-deploy). Só avisa: o provision não cria nem amplia regras de sudo.
check_deploy_sudo() {
  local name=$1 user="app-$1" rules

  rules=$(sudo -l -U "$DEPLOY_USER" 2>/dev/null || true)
  if [[ $rules != *NOPASSWD* ]]; then
    warn "$DEPLOY_USER não tem regra NOPASSWD no sudo: o deploy de $name vai pedir senha"
  fi
  if ! sudo -l -U "$DEPLOY_USER" systemctl restart "$user" >/dev/null 2>&1; then
    warn "$DEPLOY_USER não pode rodar 'systemctl restart $user' com sudo"
  fi
  if id "$user" >/dev/null 2>&1 && ! sudo -l -U "$DEPLOY_USER" -u "$user" sqlite3 >/dev/null 2>&1; then
    warn "$DEPLOY_USER não pode rodar sqlite3 como $user com sudo"
  fi
}
