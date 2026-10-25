#!/usr/bin/env bash
# Passos do deploy do ethos que rodam na VM, como o usuário de deploy (DEPLOY_USER do
# infra/config.env, com sudo sem senha). O workflow manda o script pelo SSH:
#
#   ssh ... bash -s -- <comando> [args] < apps/ethos/deploy/vm.sh
#
#   check <python>  confere o que o provision instala antes de mexer em qualquer coisa: a unit,
#                   as pastas, o uv, o Python <python>, o sqlite3, o banco e a pasta de backup
#   revision        revisão do Alembic em que o banco está (vazio se nenhuma migração rodou)
#   install         uv sync da .venv e bytecode do código, depois do rsync do backend
#   backup <sha>    cópia do banco em pre-deploy-<sha>.db, antes do restart (que migra)
#   restart         reinicia a unit; o ExecStartPre roda "alembic upgrade head"
#
# Os caminhos vêm das variáveis DEPLOY_* só no teste (test-vm.sh); na VM valem os padrões.
set -euo pipefail
shopt -s inherit_errexit

APP=ethos
UNIT=${DEPLOY_UNIT:-app-$APP.service}
APP_USER=${DEPLOY_APP_USER:-app-$APP}
APP_DIR=${DEPLOY_APP_DIR:-/opt/apps/$APP}
WEB_DIR=${DEPLOY_WEB_DIR:-/var/www/$APP}
DB=${DEPLOY_DB:-/var/lib/sqlite/$APP/app.db}
BACKUP_DIR=${DEPLOY_BACKUP_DIR:-/var/backups/sqlite/$APP}
INFRA_CONFIG=${DEPLOY_INFRA_CONFIG:-/etc/infra/config.env}
UV=${DEPLOY_UV:-/usr/local/bin/uv}

RUN_INFRA="rode o workflow Infra (Actions → Infra → Run workflow) e depois este deploy de novo"

die() {
  echo "::error::$*" >&2
  exit 1
}

as_app() { sudo -n -u "$APP_USER" -- "$@"; }

# UV_PYTHON_INSTALL_DIR do config.env que o provision copia para a VM: os Pythons das aplicações,
# instalados pelo provision (root, só leitura para os outros)
python_install_dir() {
  local value
  [[ -f $INFRA_CONFIG ]] || die "$INFRA_CONFIG não existe: $RUN_INFRA"
  value=$(sed -n 's/^UV_PYTHON_INSTALL_DIR=//p' "$INFRA_CONFIG" | tail -n1)
  [[ $value == /* ]] || die "UV_PYTHON_INSTALL_DIR ausente em $INFRA_CONFIG: $RUN_INFRA"
  printf '%s\n' "$value"
}

# uv só com o Python que o provision instalou: nunca baixa um (a pasta é do root) nem usa o do
# sistema. A .venv copia os pacotes do cache (em ~/.cache/uv do usuário de deploy) em vez de
# criar hard links, para não depender da home, que a unit nem enxerga (ProtectHome=true)
run_uv() {
  local python_dir
  python_dir=$(python_install_dir)
  UV_PYTHON_INSTALL_DIR=$python_dir UV_LINK_MODE=copy \
    "$UV" --managed-python --no-python-downloads --no-progress "$@"
}

check() {
  (($# == 1)) || die "uso: vm.sh check <versão do Python>"
  local version=$1
  [[ $version =~ ^3\.[0-9]+\.[0-9]+$ ]] || die "versão do Python inválida: '$version'"

  # A unit vem do provision (infra/apps/ethos/). Sem ela, o restart não teria o que reiniciar
  systemctl cat "$UNIT" >/dev/null 2>&1 \
    || die "$UNIT não está instalada na VM: $RUN_INFRA"
  sudo -n true 2>/dev/null || die "o usuário de deploy precisa de sudo sem senha (ver infra/PLANO.md)"

  local dir python_dir
  for dir in "$APP_DIR" "$WEB_DIR"; do
    [[ -d $dir && -w $dir ]] || die "$dir não existe ou não é gravável pelo usuário de deploy: $RUN_INFRA"
  done
  [[ -x $UV ]] || die "$UV não existe: $RUN_INFRA"
  python_dir=$(python_install_dir)
  # A partir de /: o uv não pode achar um projeto (nem uma .venv) na pasta atual
  (cd / && run_uv python find "$version" >/dev/null 2>&1) \
    || die "Python $version não está instalado em $python_dir: confira o PYTHON_VERSION de infra/apps/$APP/app.conf e $RUN_INFRA"
  command -v sqlite3 >/dev/null || die "sqlite3 não está instalado: $RUN_INFRA"
  as_app test -f "$DB" || die "$DB não existe: $RUN_INFRA"
  as_app test -w "$BACKUP_DIR" || die "$BACKUP_DIR não existe ou não é gravável por $APP_USER: $RUN_INFRA"

  echo "VM pronta: $UNIT, pastas, uv, Python $version, sqlite3, banco e backup"
}

revision() {
  (($# == 0)) || die "uso: vm.sh revision"
  local table
  table=$(as_app sqlite3 "$DB" \
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version';")
  if [[ -n $table ]]; then
    as_app sqlite3 "$DB" "SELECT version_num FROM alembic_version;"
  fi
}

install_venv() {
  (($# == 0)) || die "uso: vm.sh install"
  cd "$APP_DIR"
  [[ -f uv.lock && -f .python-version ]] || die "$APP_DIR sem uv.lock ou .python-version: o rsync do backend falhou?"
  # O app-<nome> lê o código e a .venv, mas não grava
  umask 022
  # --frozen: exatamente o uv.lock; --no-build: só wheels prontas (nada compila com 1 GB de RAM).
  # O --compile-bytecode só compila os pacotes da .venv: o projeto não é instalado (não tem
  # build-system), então o bytecode de app/ e migrations/ sai do compileall logo abaixo. A unit roda
  # com PYTHONDONTWRITEBYTECODE e o app-<nome> não grava aqui: sem isto, o bytecode seria refeito em
  # memória a cada subida
  run_uv sync --frozen --no-dev --no-build --compile-bytecode
  # O uv cria a .venv/.lock gravável por todos, ignorando o umask: o app-<nome> não grava nada aqui
  chmod -R go-w .venv
  .venv/bin/python -m compileall -q app migrations
  echo "dependências instaladas: $(.venv/bin/python --version)"
}

backup() {
  (($# == 1)) || die "uso: vm.sh backup <sha>"
  local sha=$1 out tmp result
  [[ $sha =~ ^[0-9a-f]{40}$ ]] || die "sha inválido: '$sha'"

  out=$BACKUP_DIR/pre-deploy-$sha.db
  # Mesmo commit de novo (re-run, rollback para um commit já publicado): o primeiro backup é o de
  # antes da migração desse commit e fica; este ganha a hora no nome
  if as_app test -e "$out"; then
    out=$BACKUP_DIR/pre-deploy-$sha-$(date -u +%Y%m%dT%H%M%SZ).db
  fi
  # Nome temporário fora do padrão *.db: um backup pela metade nunca parece pronto
  tmp=$out.partial
  as_app rm -f "$tmp"

  # .backup é consistente com o app escrevendo (WAL); cp do arquivo não é. Como o snapshot.sh:
  # roda como o app (o -wal/-shm do banco nunca nasce com outro dono) e vira arquivo único
  if ! as_app sqlite3 "$DB" ".backup '$tmp'" \
    || ! as_app sqlite3 "$tmp" 'PRAGMA journal_mode=DELETE;' >/dev/null \
    || ! result=$(as_app sqlite3 "$tmp" 'PRAGMA integrity_check;') \
    || [[ $result != ok ]]; then
    as_app rm -f "$tmp"
    die "backup pré-deploy falhou (integrity_check: ${result:-não rodou}); nada foi reiniciado"
  fi
  as_app chmod 0600 "$tmp"
  as_app mv -f "$tmp" "$out"

  # Retenção: o snapshot.sh diário apaga os *.db com mais de 7 dias desta pasta, estes inclusive
  echo "backup: $(basename "$out") ($(as_app du -h "$out" | cut -f1))"
}

restart() {
  (($# == 0)) || die "uso: vm.sh restart"
  # Um deploy anterior com migração quebrada pode ter esgotado o StartLimitBurst da unit
  sudo -n systemctl reset-failed "$UNIT" 2>/dev/null || true
  # Type=exec: volta depois do ExecStartPre (migração) e do exec do uvicorn; falha se a migração
  # falhar. Nada do journal vai para o log do Actions (o repositório é público)
  if ! sudo -n systemctl restart "$UNIT"; then
    systemctl show "$UNIT" -p ActiveState -p SubState -p Result >&2 || true
    die "$UNIT não subiu (migração ou subida falhou). O front anterior continua no ar. Na VM: journalctl -u $UNIT -n 50 --no-pager"
  fi
  echo "$UNIT reiniciada"
}

main() {
  (($# >= 1)) || die "uso: vm.sh <check|revision|install|backup|restart> [args]"
  local command=$1
  shift
  case $command in
    check | revision | backup | restart) "$command" "$@" ;;
    install) install_venv "$@" ;;
    *) die "comando desconhecido: $command" ;;
  esac
}

# stdin fechado: por "bash -s", o script chega pelo stdin, e um comando que lesse o stdin (sudo,
# sqlite3, uv) consumiria o resto dele
main "$@" < /dev/null
