# Config do site versionada em infra/nginx/site.conf. Se nginx -t falhar, volta a anterior.

provision_nginx() {
  local dest=/etc/nginx/sites-available/default backup=""

  install -d -m 0755 -o root -g root /etc/nginx/apps.d

  if [[ -f $dest ]] && cmp -s "$INFRA_DIR/nginx/site.conf" "$dest"; then
    systemctl is-active --quiet nginx || systemctl start nginx
    return 0
  fi

  if [[ -f $dest ]]; then
    install -d -m 0700 /var/backups/infra
    backup="/var/backups/infra/nginx-default.$(date -u +%Y%m%dT%H%M%SZ)"
    cp -p "$dest" "$backup"
  fi

  install -m 0644 -o root -g root "$INFRA_DIR/nginx/site.conf" "$dest"

  if ! nginx -t -q; then
    if [[ -n $backup ]]; then
      cp -p "$backup" "$dest"
    fi
    die "nginx -t falhou com a nova config; a anterior foi restaurada"
  fi

  systemctl reload nginx
  log "nginx: config atualizada e recarregada${backup:+ (anterior em $backup)}"
}
