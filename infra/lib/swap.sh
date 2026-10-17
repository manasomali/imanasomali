# Swapfile de 2 GB: sem ele, um pico de memória faz o kernel matar o nginx ou um backend.

provision_swap() {
  if ! grep -q '^/swapfile ' /proc/swaps; then
    if [[ ! -f /swapfile ]]; then
      fallocate -l 2G /swapfile
      chmod 600 /swapfile
      mkswap /swapfile >/dev/null
    fi
    swapon /swapfile
    log "swap ativado"
  fi

  if ! grep -qE '^/swapfile[[:space:]]' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    log "swap adicionado ao /etc/fstab"
  fi

  if sync_content /etc/sysctl.d/99-infra.conf 0644 <<'EOF'
vm.swappiness=10
EOF
  then
    sysctl -q -p /etc/sysctl.d/99-infra.conf
  fi
}
