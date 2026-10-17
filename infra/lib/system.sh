# Enxuga a VM (1 GB de RAM) e mantém a carga diária anti-ociosidade do Always Free.

# Serviços sem uso nesta VM. iscsid/multipathd: o disco de boot é paravirtualizado (sem sessões iSCSI).
UNUSED_UNITS=(
  udisks2.service
  rpcbind.service rpcbind.socket
  iscsid.service iscsid.socket
  multipathd.service multipathd.socket
)

provision_system() {
  local unit state reload=0

  for unit in "${UNUSED_UNITS[@]}"; do
    state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
    if [[ $state == enabled || $state == enabled-runtime ]]; then
      systemctl disable --now "$unit" >/dev/null 2>&1
      log "desligado: $unit"
    elif systemctl is-active --quiet "$unit"; then
      systemctl stop "$unit"
      log "parado: $unit"
    fi
  done

  if [[ $(systemctl is-enabled packagekit.service 2>/dev/null || true) != masked ]]; then
    systemctl mask --now packagekit.service >/dev/null 2>&1
    log "mascarado: packagekit.service"
  fi

  if snap list lxd >/dev/null 2>&1; then
    snap remove --purge lxd
    log "snap lxd removido"
  fi

  if [[ $(snap get system refresh.retain 2>/dev/null || true) != 2 ]]; then
    snap set system refresh.retain=2
  fi

  if sync_content /etc/systemd/journald.conf.d/size.conf 0644 <<'EOF'
[Journal]
SystemMaxUse=100M
EOF
  then
    systemctl restart systemd-journald
  fi

  if sync_file "$INFRA_DIR/systemd/keepalive.service" /etc/systemd/system/keepalive.service; then reload=1; fi
  if sync_file "$INFRA_DIR/systemd/keepalive.timer" /etc/systemd/system/keepalive.timer; then reload=1; fi
  if ((reload)); then
    systemctl daemon-reload
  fi
  systemctl enable --now keepalive.timer >/dev/null 2>&1

  clean_legacy_crontab
}

# O keep-alive antigo ficava no crontab do ubuntu (e disparava 60 sysbench por dia).
# O certbot renew do crontab duplicava o snap.certbot.renew.timer.
clean_legacy_crontab() {
  local user=ubuntu current filtered
  id "$user" >/dev/null 2>&1 || return 0
  current=$(crontab -u "$user" -l 2>/dev/null) || return 0
  filtered=$(grep -vE 'sysbench|certbot renew' <<< "$current" || true)
  if [[ $filtered != "$current" ]]; then
    printf '%s\n' "$filtered" | crontab -u "$user" -
    log "crontab de $user: removidas as linhas antigas de sysbench e certbot renew"
  fi
}
