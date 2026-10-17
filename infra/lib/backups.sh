# Backup contínuo (Litestream -> Object Storage da Oracle) e snapshots locais diários.

provision_backups() {
  local reload=0 restart=0 endpoint bucket region

  if sync_file "$INFRA_DIR/systemd/sqlite-snapshot.service" /etc/systemd/system/sqlite-snapshot.service; then reload=1; fi
  if sync_file "$INFRA_DIR/systemd/sqlite-snapshot.timer" /etc/systemd/system/sqlite-snapshot.timer; then reload=1; fi
  if sync_file "$INFRA_DIR/systemd/litestream.service" /etc/systemd/system/litestream.service; then
    reload=1
    restart=1
  fi
  if ((reload)); then
    systemctl daemon-reload
  fi
  systemctl enable --now sqlite-snapshot.timer >/dev/null 2>&1

  if ((${#DATABASES[@]} == 0)); then
    if systemctl is-enabled --quiet litestream 2>/dev/null; then
      systemctl disable --now litestream >/dev/null 2>&1
      log "litestream desligado: nenhum banco em databases.txt"
    fi
    return 0
  fi

  endpoint=$(env_get "$INFRA_STATE_DIR/s3.env" S3_ENDPOINT)
  bucket=$(env_get "$INFRA_STATE_DIR/s3.env" S3_BUCKET)
  region=$(env_get "$INFRA_STATE_DIR/s3.env" OCI_REGION)

  local missing=() key
  [[ -n $endpoint ]] || missing+=("S3_ENDPOINT (variable)")
  [[ -n $bucket ]] || missing+=("S3_BUCKET (variable)")
  [[ -n $region ]] || missing+=("OCI_REGION (variable)")
  for key in LITESTREAM_ACCESS_KEY_ID LITESTREAM_SECRET_ACCESS_KEY; do
    [[ -n $(env_get /etc/default/litestream "$key") ]] || missing+=("$key (secret)")
  done
  if ((${#missing[@]})); then
    die "há bancos em databases.txt, mas faltam valores do Object Storage no GitHub: ${missing[*]}"
  fi

  if render_litestream_config "$endpoint" "$bucket" "$region" | sync_content /etc/litestream.yml 0644; then
    restart=1
  fi
  if ((LITESTREAM_UPDATED || CREDS_CHANGED)); then
    restart=1
  fi

  systemctl enable litestream >/dev/null 2>&1
  if ((restart)); then
    systemctl restart litestream
    log "litestream reiniciado"
  else
    systemctl start litestream
  fi
}

render_litestream_config() {
  local endpoint=$1 bucket=$2 region=$3 name
  cat <<EOF
# Gerado pelo provision a partir de databases.txt. Não edite na VM.
# Credenciais: LITESTREAM_ACCESS_KEY_ID e LITESTREAM_SECRET_ACCESS_KEY em /etc/default/litestream.

# Poucos níveis e intervalos longos: o Object Storage Always Free tem limite mensal de requisições.
levels:
  - interval: 1h
snapshot:
  interval: 24h
  retention: 168h

dbs:
EOF
  for name in "${DATABASES[@]}"; do
    cat <<EOF
  - path: $SQLITE_ROOT/$name/app.db
    replica:
      type: s3
      bucket: "$bucket"
      path: "$name"
      endpoint: "$endpoint"
      region: "$region"
      force-path-style: true
      sync-interval: $LITESTREAM_SYNC_INTERVAL
EOF
  done
}
