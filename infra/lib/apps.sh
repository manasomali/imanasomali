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
  check_smtp_env
  if sync_file "$INFRA_DIR/systemd/infra-unit-failed@.service" "$UNIT_DIR/infra-unit-failed@.service"; then
    reload=1
  fi

  while IFS= read -r name; do
    # Código do backend: o deploy grava, o app-<nome> só lê (não consegue alterar o próprio código)
    sync_dir "/opt/apps/$name" 0755 "$DEPLOY_USER" || true
    # Frontend: o deploy grava, o nginx lê. Fora de /var/www/html, que o deploy do site limpa com --delete
    sync_dir "/var/www/$name" 0755 "$DEPLOY_USER" || true
    check_deploy_sudo "$name"

    if install_app_env "$name" || ((${SMTP_CHANGED:-0})); then
      config_changed[$name]=1
    fi
    if install_app_units "$name"; then
      units_changed[$name]=1
      reload=1
    fi
  done <<< "$apps"

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
    # Segredos vão pelos secrets do GitHub (stdin), nunca versionados
    [[ $line != SMTP_* ]] || die "$src não pode ter ${line%%=*}: credenciais SMTP ficam em $INFRA_STATE_DIR/smtp.env"
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

# As apps mandam email: avisa se faltar alguma credencial (o secret não foi cadastrado no GitHub)
check_smtp_env() {
  local key
  for key in SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD; do
    if ! grep -q "^$key=" "$INFRA_STATE_DIR/smtp.env" 2>/dev/null; then
      warn "$INFRA_STATE_DIR/smtp.env sem $key: cadastre o secret no GitHub e rode o Infra"
    fi
  done
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
