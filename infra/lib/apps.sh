# Uma aplicação por pasta em infra/apps/<nome>/ (ver apps/README.md). Nunca apaga nada.

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
  local name apps env_changed

  id "$DEPLOY_USER" >/dev/null 2>&1 || die "usuário de deploy '$DEPLOY_USER' (config.env) não existe"
  apps=$(read_apps) || exit 1
  [[ -n $apps ]] || return 0

  sync_dir /opt/apps 0755 root || true
  sync_dir "$INFRA_STATE_DIR/apps" 0755 root || true
  check_smtp_env

  while IFS= read -r name; do
    # Código do backend: o deploy grava, o app-<nome> só lê (não consegue alterar o próprio código)
    sync_dir "/opt/apps/$name" 0755 "$DEPLOY_USER" || true
    # Frontend: o deploy grava, o nginx lê. Fora de /var/www/html, que o deploy do site limpa com --delete
    sync_dir "/var/www/$name" 0755 "$DEPLOY_USER" || true
    check_deploy_sudo "$name"

    env_changed=0
    if install_app_env "$name"; then
      env_changed=1
    fi
    if ((env_changed || ${SMTP_CHANGED:-0})); then
      restart_app "$name"
    fi
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

# As apps mandam email: avisa se faltar alguma credencial (o secret não foi cadastrado no GitHub)
check_smtp_env() {
  local key
  for key in SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD; do
    if ! grep -q "^$key=" "$INFRA_STATE_DIR/smtp.env" 2>/dev/null; then
      warn "$INFRA_STATE_DIR/smtp.env sem $key: cadastre o secret no GitHub e rode o Infra"
    fi
  done
}

# Reinicia app-<nome> para ler a config nova, só se a unit existir e estiver rodando
restart_app() {
  local unit="app-$1.service"
  if systemctl is-active --quiet "$unit"; then
    systemctl restart "$unit"
    log "reiniciado: $unit"
  fi
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
