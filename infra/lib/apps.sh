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
  local name apps

  id "$DEPLOY_USER" >/dev/null 2>&1 || die "usuário de deploy '$DEPLOY_USER' (config.env) não existe"
  apps=$(read_apps) || exit 1
  [[ -n $apps ]] || return 0

  sync_dir /opt/apps 0755 root || true

  while IFS= read -r name; do
    # Código do backend: o deploy grava, o app-<nome> só lê (não consegue alterar o próprio código)
    sync_dir "/opt/apps/$name" 0755 "$DEPLOY_USER" || true
    # Frontend: o deploy grava, o nginx lê. Fora de /var/www/html, que o deploy do site limpa com --delete
    sync_dir "/var/www/$name" 0755 "$DEPLOY_USER" || true
    check_deploy_sudo "$name"
  done <<< "$apps"
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
