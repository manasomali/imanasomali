#!/usr/bin/env bash
# Provisiona a VM a partir de /opt/infra. Idempotente: rodar de novo sem mudanças no repo não altera nada.
#
# CI:     printf 'CHAVE=valor\n...' | ssh vm 'sudo -n /opt/infra/provision.sh'
# Manual: sudo /opt/infra/provision.sh   (reaproveita as credenciais já gravadas na VM)
set -euo pipefail

INFRA_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib/common.sh
source "$INFRA_DIR/lib/common.sh"
# shellcheck source=lib/input.sh
source "$INFRA_DIR/lib/input.sh"
# shellcheck source=config.env
source "$INFRA_DIR/config.env"
# shellcheck source=lib/swap.sh
source "$INFRA_DIR/lib/swap.sh"
# shellcheck source=lib/packages.sh
source "$INFRA_DIR/lib/packages.sh"
# shellcheck source=lib/system.sh
source "$INFRA_DIR/lib/system.sh"
# shellcheck source=lib/databases.sh
source "$INFRA_DIR/lib/databases.sh"
# shellcheck source=lib/backups.sh
source "$INFRA_DIR/lib/backups.sh"
# shellcheck source=lib/apps.sh
source "$INFRA_DIR/lib/apps.sh"
# shellcheck source=lib/nginx.sh
source "$INFRA_DIR/lib/nginx.sh"

require_root
[[ $(uname -m) == x86_64 ]] || die "esperado x86_64 (VM.Standard.E2.1.Micro), encontrado $(uname -m)"

LOG_FILE=/var/log/infra-provision.log
touch "$LOG_FILE"
chmod 0640 "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

CREDS_CHANGED=0
SMTP_CHANGED=0
LITESTREAM_UPDATED=0

# Scripts que rodam como root via systemd/sudo ficam fora de /opt/infra, que é gravável pelo usuário de deploy.
install_runtime_files() {
  local script name
  sync_file "$INFRA_DIR/lib/common.sh" "$INFRA_LIB_DIR/common.sh" 0644 || true
  for script in snapshot restore-test smoke-test; do
    sync_file "$INFRA_DIR/scripts/$script.sh" "$INFRA_LIB_DIR/$script.sh" 0755 || true
  done
  install -d -m 0755 "$INFRA_STATE_DIR"
  sync_file "$INFRA_DIR/config.env" "$INFRA_STATE_DIR/config.env" 0644 || true
  for name in "${DATABASES[@]}"; do
    printf '%s\n' "$name"
  done | sync_content "$INFRA_STATE_DIR/databases" 0644 || true

  if write_env_file /etc/default/litestream 0600 LITESTREAM_ACCESS_KEY_ID LITESTREAM_SECRET_ACCESS_KEY; then
    CREDS_CHANGED=1
  fi
  write_env_file "$INFRA_STATE_DIR/s3.env" 0644 S3_ENDPOINT S3_BUCKET OCI_REGION || true
  # Um provedor e um domínio só: as apps dividem as credenciais (EnvironmentFile= de cada unit)
  if write_env_file "$INFRA_STATE_DIR/smtp.env" 0600 SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD; then
    SMTP_CHANGED=1
  fi
}

read_stdin_config
load_databases "$INFRA_DIR/databases.txt"
log "provision iniciado: ${#DATABASES[@]} banco(s) [${DATABASES[*]:-}]"

install_runtime_files
provision_swap
provision_packages
provision_system
provision_databases
provision_apps
provision_backups
provision_nginx

"$INFRA_LIB_DIR/smoke-test.sh"
log "provision concluído"
