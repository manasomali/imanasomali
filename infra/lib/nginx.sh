# Config do site (infra/nginx/site.conf) e as rotas de cada aplicação: infra/apps/<nome>/nginx.conf
# em /etc/nginx/apps.d/<nome>.conf (dentro do server 443) e nginx-http.conf, se existir, em
# /etc/nginx/conf.d/<nome>.conf (contexto http), com __PORTA__ trocado pelo PORT do app.conf.
# Tudo de uma vez: se o nginx -t falhar, todos os arquivos voltam ao que eram e o provision para.
# Usa read_apps e valid_port de lib/apps.sh.

NGINX_SITE=/etc/nginx/sites-available/default

provision_nginx() {
  local tmp apps name file dir port i ts
  local -a srcs=() dests=() changed=()

  install -d -m 0755 -o root -g root /etc/nginx/apps.d
  tmp=$(mktemp -d)

  srcs+=("$INFRA_DIR/nginx/site.conf")
  dests+=("$NGINX_SITE")

  apps=$(read_apps) || exit 1
  while IFS= read -r name; do
    [[ -n $name ]] || continue
    port=$(env_get "$INFRA_DIR/apps/$name/app.conf" PORT)
    # Validada antes do sed: só dígitos entram na config do nginx
    if [[ -n $port ]] && ! valid_port "$port"; then
      die "PORT inválido em infra/apps/$name/app.conf: '$port' (1024 a 65535)"
    fi
    for file in nginx.conf nginx-http.conf; do
      [[ -f $INFRA_DIR/apps/$name/$file ]] || continue
      if [[ -z $port ]] && grep -q __PORTA__ "$INFRA_DIR/apps/$name/$file"; then
        die "infra/apps/$name/$file usa __PORTA__, mas infra/apps/$name/app.conf não tem PORT"
      fi
      dir=/etc/nginx/apps.d
      [[ $file == nginx-http.conf ]] && dir=/etc/nginx/conf.d
      sed "s/__PORTA__/$port/g" "$INFRA_DIR/apps/$name/$file" > "$tmp/$name-$file"
      srcs+=("$tmp/$name-$file")
      dests+=("$dir/$name.conf")
    done
  done <<< "$apps"

  for i in "${!dests[@]}"; do
    if [[ -f ${dests[$i]} ]] && cmp -s "${srcs[$i]}" "${dests[$i]}"; then
      continue
    fi
    if [[ -f ${dests[$i]} ]]; then
      cp -p "${dests[$i]}" "$tmp/anterior-$i"
    fi
    install -m 0644 -o root -g root "${srcs[$i]}" "${dests[$i]}"
    changed+=("$i")
  done

  if ((${#changed[@]} == 0)); then
    rm -rf "$tmp"
    systemctl is-active --quiet nginx || systemctl start nginx
    return 0
  fi

  if ! nginx -t -q; then
    for i in "${changed[@]}"; do
      if [[ -f $tmp/anterior-$i ]]; then
        cp -p "$tmp/anterior-$i" "${dests[$i]}"
      else
        rm -f "${dests[$i]}"
      fi
    done
    rm -rf "$tmp"
    die "nginx -t falhou com a config nova; todos os arquivos anteriores foram restaurados"
  fi

  # Cópia de cada arquivo substituído, para comparar ou voltar à mão
  install -d -m 0700 /var/backups/infra
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  for i in "${changed[@]}"; do
    if [[ -f $tmp/anterior-$i ]]; then
      cp -p "$tmp/anterior-$i" \
        "/var/backups/infra/nginx-$(basename "$(dirname "${dests[$i]}")")-$(basename "${dests[$i]}").$ts"
    fi
    log "atualizado: ${dests[$i]}"
  done
  rm -rf "$tmp"

  if systemctl is-active --quiet nginx; then
    systemctl reload nginx
  else
    systemctl start nginx
  fi
  log "nginx: config recarregada (anteriores em /var/backups/infra)"
}
