#!/usr/bin/env bash
# Testa provision_databases e provision_apps num runner Ubuntu com systemd, como root, com o usuário
# do runner no papel do usuário de deploy (sudo total sem senha, como o ubuntu da VM). O código das
# apps é trocado por stubs em /opt/apps/<nome>/.venv/bin (uvicorn, alembic, python).
# Roda na raiz do repo, pelo infra.yaml: sudo DEPLOY_USER=runner .github/scripts/test-provision-apps.sh
set -euo pipefail

deploy_user=${DEPLOY_USER:?defina DEPLOY_USER}
INFRA_DIR=$PWD/infra
# shellcheck source=infra/lib/common.sh
source "$INFRA_DIR/lib/common.sh"
# shellcheck source=infra/config.env
source "$INFRA_DIR/config.env"
# shellcheck source=infra/lib/databases.sh
source "$INFRA_DIR/lib/databases.sh"
# shellcheck source=infra/lib/apps.sh
source "$INFRA_DIR/lib/apps.sh"
DEPLOY_USER=$deploy_user

require_root

fail() {
  echo "::error::$*"
  exit 1
}
stat_is() {
  local got
  got=$(stat -c '%U %a' "$1")
  [[ $got == "$2" ]] || fail "$1: $got, esperado $2"
}
# Roda provision_apps guardando a saída em $out
run_apps() { provision_apps 2>&1 | tee "$out"; }
log_has() { grep -qE "$1" "$out"; }
quiet_run() {
  run_apps
  if log_has 'criado|atualizado|ligado|iniciado|reiniciado|desligado|removido|AVISO'; then
    fail "$1: o provision mudou algo ou avisou"
  fi
}
units_of() { cat "$INFRA_STATE_DIR/apps/$1.units"; }
pid() { systemctl show -p MainPID --value "$1"; }

out=$(mktemp)
tmp_env=$(mktemp)
trap 'rm -f "$out" "$tmp_env"' EXIT

load_databases "$INFRA_DIR/databases.txt"
mapfile -t apps < <(read_apps)
((${#apps[@]})) || fail "nenhuma aplicação em infra/apps/"

# smtp.env completo (valores falsos), como o provision grava a partir dos secrets
install -d -m 0755 "$INFRA_STATE_DIR"
printf 'SMTP_HOST=smtp.exemplo\nSMTP_PORT=587\nSMTP_USER=u\nSMTP_PASSWORD=p\n' > "$INFRA_STATE_DIR/smtp.env"
chmod 0600 "$INFRA_STATE_DIR/smtp.env"
SMTP_CHANGED=0

echo "--- primeira execução (sem código: os serviços ficam parados pelo ConditionPathExists)"
provision_databases
run_apps

echo "--- segunda execução: não muda nem avisa nada"
provision_databases
quiet_run "segunda execução"

for name in "${apps[@]}"; do
  echo "--- $name: pastas, config e sudo"
  stat_is /opt/apps "root 755"
  stat_is "/opt/apps/$name" "$DEPLOY_USER 755"
  stat_is "/var/www/$name" "$DEPLOY_USER 755"
  if [[ -f $INFRA_DIR/apps/$name/app.env ]]; then
    stat_is "$INFRA_STATE_DIR/apps/$name.env" "root 644"
    cmp -s "$INFRA_DIR/apps/$name/app.env" "$INFRA_STATE_DIR/apps/$name.env" \
      || fail "$INFRA_STATE_DIR/apps/$name.env diferente de infra/apps/$name/app.env"
  fi

  if id "app-$name" >/dev/null 2>&1; then
    stat_is "$BACKUP_ROOT/$name" "app-$name 700"
    if runuser -u "app-$name" -- touch "/opt/apps/$name/x" 2>/dev/null; then
      fail "app-$name conseguiu escrever em /opt/apps/$name"
    fi
    runuser -u "app-$name" -- test -r "/opt/apps/$name" -a -x "/opt/apps/$name" \
      || fail "app-$name não consegue ler /opt/apps/$name"
    runuser -u "$DEPLOY_USER" -- sudo -n -l systemctl restart "app-$name" >/dev/null \
      || fail "$DEPLOY_USER não pode rodar systemctl restart app-$name com sudo -n"
    runuser -u "$DEPLOY_USER" -- sudo -n -u "app-$name" \
      sqlite3 "$SQLITE_ROOT/$name/app.db" ".backup $BACKUP_ROOT/$name/pre-deploy-teste.db" \
      || fail "backup pré-deploy como app-$name falhou"
    [[ $(stat -c %U "$BACKUP_ROOT/$name/pre-deploy-teste.db") == "app-$name" ]] \
      || fail "pre-deploy-teste.db sem dono app-$name"
  fi

  echo "--- $name: units instaladas"
  [[ -s $INFRA_STATE_DIR/apps/$name.units ]] || continue
  port=$(env_get "$INFRA_DIR/apps/$name/app.conf" PORT)
  while IFS= read -r unit; do
    [[ -f $UNIT_DIR/$unit ]] || fail "$unit não foi instalada"
    cmp -s <(sed "s/__PORTA__/$port/g" "$INFRA_DIR/apps/$name/$unit") "$UNIT_DIR/$unit" \
      || fail "$UNIT_DIR/$unit diferente do repo com a porta trocada"
    if [[ $unit == *.timer || $unit == "app-$name.service" ]]; then
      systemctl is-enabled --quiet "$unit" || fail "$unit não está habilitada"
    fi
  done < <(units_of "$name")
  if systemctl is-active --quiet "app-$name.service"; then
    fail "app-$name.service subiu sem código (ConditionPathExists)"
  fi

  echo "--- $name: stubs no lugar do código e systemd-analyze verify"
  # O teste reinicia o serviço muitas vezes seguidas: sem o StartLimitBurst só aqui (drop-in)
  install -d "$UNIT_DIR/app-$name.service.d"
  printf '[Unit]\nStartLimitIntervalSec=0\n' > "$UNIT_DIR/app-$name.service.d/teste-ci.conf"
  systemctl daemon-reload
  bin=/opt/apps/$name/.venv/bin
  install -d -m 0755 "$bin"
  cat > "$bin/uvicorn" <<'EOF'
#!/bin/bash
# Stub do uvicorn: escuta onde o uvicorn escutaria (--host, --port)
while (($#)); do
  case $1 in
    --host) host=$2; shift ;;
    --port) port=$2; shift ;;
  esac
  shift
done
exec /usr/bin/python3 -m http.server --bind "$host" "$port"
EOF
  cat > "$bin/alembic" <<EOF
#!/bin/bash
# Stub do alembic: falha se existir o arquivo QUEBRAR_MIGRACAO
[[ ! -e /opt/apps/$name/QUEBRAR_MIGRACAO ]]
EOF
  cat > "$bin/python" <<EOF
#!/bin/bash
# Stub do python da .venv: registra o comando e falha se existir QUEBRAR_JOB
echo "stub python: \$*"
[[ ! -e /opt/apps/$name/QUEBRAR_JOB ]]
EOF
  chmod 0755 "$bin"/*
  mapfile -t unit_files < <(units_of "$name" | sed "s|^|$UNIT_DIR/|")
  systemd-analyze verify "${unit_files[@]}" || fail "systemd-analyze verify falhou para $name"

  if [[ -f $UNIT_DIR/app-$name.service ]]; then
    service=app-$name.service
    echo "--- $name: com código, o provision sobe o serviço"
    run_apps
    log_has "iniciado: $service" || fail "$service não foi iniciado"
    systemctl is-active --quiet "$service" || fail "$service não está ativo"
    quiet_run "execução com o serviço no ar"

    echo "--- $name: escuta só em 127.0.0.1:$port, MemoryMax de 150M"
    for _ in $(seq 1 20); do
      ss -ltnH "sport = :$port" | grep -q . && break
      sleep 0.5
    done
    listening=$(ss -ltnH "sport = :$port" | awk '{print $4}')
    [[ $listening == "127.0.0.1:$port" ]] || fail "$service escuta em '$listening', esperado só 127.0.0.1:$port"
    [[ $(systemctl show -p MemoryMax --value "$service") == 157286400 ]] || fail "MemoryMax diferente de 150M"
    grep -qx "EnvironmentFile=$INFRA_STATE_DIR/smtp.env" "$UNIT_DIR/$service" || fail "$service sem smtp.env"
    grep -qx "EnvironmentFile=$INFRA_STATE_DIR/apps/$name.env" "$UNIT_DIR/$service" || fail "$service sem $name.env"

    echo "--- $name: restart só quando a config muda"
    pid_before=$(pid "$service")
    SMTP_CHANGED=1 run_apps
    log_has "reiniciado: $service" || fail "mudança no smtp.env não reiniciou $service"
    if log_has 'reiniciado: .*\.timer'; then
      fail "mudança no smtp.env reiniciou timer"
    fi
    [[ $(pid "$service") != "$pid_before" ]] || fail "$service não foi reiniciado (mesmo PID)"
    if [[ -f $INFRA_DIR/apps/$name/app.env ]]; then
      pid_before=$(pid "$service")
      cp "$INFRA_DIR/apps/$name/app.env" "$tmp_env"
      printf 'TESTE_CI=1\n' >> "$INFRA_DIR/apps/$name/app.env"
      run_apps
      cp "$tmp_env" "$INFRA_DIR/apps/$name/app.env"
      log_has "atualizado: $INFRA_STATE_DIR/apps/$name.env" || fail "app.env novo não foi instalado"
      [[ $(pid "$service") != "$pid_before" ]] || fail "mudança no app.env não reiniciou $service"
      run_apps >/dev/null
    fi
    systemctl stop "$service"
    SMTP_CHANGED=1 run_apps
    log_has "iniciado: $service" || fail "serviço parado não foi iniciado"
    if log_has "reiniciado: $service"; then
      fail "serviço parado foi 'reiniciado'"
    fi

    echo "--- $name: migração quebrada impede o serviço de subir"
    touch "/opt/apps/$name/QUEBRAR_MIGRACAO"
    if systemctl restart "$service"; then
      fail "$service subiu com a migração quebrada"
    fi
    systemctl is-active --quiet "$service" && fail "$service ativo com a migração quebrada"
    rm "/opt/apps/$name/QUEBRAR_MIGRACAO"
    systemctl reset-failed "$service"
    systemctl start "$service" || fail "$service não voltou depois de consertar a migração"
  fi

  while IFS= read -r timer; do
    [[ $timer == *.timer ]] || continue
    job=${timer%.timer}.service
    echo "--- $name: $timer agendado; $job roda os comandos e registra falha"
    systemctl is-active --quiet "$timer" || fail "$timer não está ativo"
    systemctl list-timers --all "$timer" | grep -q "$timer" || fail "$timer fora do list-timers"
    since=$(date '+%Y-%m-%d %H:%M:%S')
    systemctl start "$job" || fail "$job falhou com os stubs"
    journalctl -u "$job" --since "$since" -o cat | grep 'stub python' || true
    touch "/opt/apps/$name/QUEBRAR_JOB"
    if systemctl start "$job"; then
      fail "$job não falhou com o comando quebrado"
    fi
    rm "/opt/apps/$name/QUEBRAR_JOB"
    for _ in $(seq 1 20); do
      journalctl -t infra -p err --since "$since" -o cat | grep -q "$job falhou" && break
      sleep 0.5
    done
    journalctl -t infra -p err --since "$since" -o cat | grep "$job falhou" \
      || fail "OnFailure de $job não gravou erro no journald"
    systemctl reset-failed "$job"
  done < <(units_of "$name")
done

# O ethos: alertas e depois limpeza, nessa ordem, como app-ethos
if [[ -f $UNIT_DIR/ethos-alerts.service ]]; then
  echo "--- ethos-alerts.service roda run-alerts e depois cleanup"
  # O --since tem resolução de segundo: separa das execuções anteriores
  sleep 1.1
  since=$(date '+%Y-%m-%d %H:%M:%S')
  systemctl start ethos-alerts.service
  ran=$(journalctl -u ethos-alerts.service --since "$since" -o cat | grep 'stub python' | tr '\n' '|')
  [[ $ran == "stub python: -m app.cli run-alerts|stub python: -m app.cli cleanup|" ]] \
    || fail "ethos-alerts.service rodou: $ran"
  [[ $(systemctl show -p User --value ethos-alerts.service) == app-ethos ]] || fail "ethos-alerts não roda como app-ethos"
  [[ $(systemctl show -p TimersCalendar --value ethos-alerts.timer) == *"*-*-* *:00:00"* ]] \
    || fail "ethos-alerts.timer não é de hora em hora"
fi

echo "--- dono ou modo errado é corrigido"
name=${apps[0]}
chmod 0777 "/opt/apps/$name"
run_apps
log_has "atualizado: /opt/apps/$name" || fail "provision não registrou a correção"
stat_is "/opt/apps/$name" "$DEPLOY_USER 755"

echo "--- unit mudada no repo: reinstalada, daemon-reload e restart"
first_unit=$(units_of "$name" | head -n1)
pid_before=$(pid "app-$name.service")
cp "$INFRA_DIR/apps/$name/$first_unit" "$tmp_env"
printf '# mudança de teste\n' >> "$INFRA_DIR/apps/$name/$first_unit"
run_apps
cp "$tmp_env" "$INFRA_DIR/apps/$name/$first_unit"
log_has "atualizado: $UNIT_DIR/$first_unit" || fail "unit mudada não foi reinstalada"
[[ $(pid "app-$name.service") != "$pid_before" ]] || fail "unit mudada não reiniciou app-$name.service"
run_apps >/dev/null
quiet_run "depois de desfazer a mudança na unit"

echo "--- recusados: unit com nome de outra coisa, PORT inválido, SMTP no app.env"
touch "$INFRA_DIR/apps/$name/nginx.service"
if (provision_apps) >"$out" 2>&1; then
  fail "provision_apps aceitou infra/apps/$name/nginx.service"
fi
rm "$INFRA_DIR/apps/$name/nginx.service"
log_has "as units de $name se chamam" || { cat "$out"; fail "mensagem inesperada para unit fora do padrão"; }

cp "$INFRA_DIR/apps/$name/app.conf" "$tmp_env"
sed -i 's/^PORT=.*/PORT=80/' "$INFRA_DIR/apps/$name/app.conf"
if (provision_apps) >"$out" 2>&1; then
  fail "provision_apps aceitou PORT=80"
fi
cp "$tmp_env" "$INFRA_DIR/apps/$name/app.conf"
log_has "PORT inválido" || { cat "$out"; fail "mensagem inesperada para PORT inválido"; }

if [[ -f $INFRA_DIR/apps/$name/app.env ]]; then
  cp "$INFRA_DIR/apps/$name/app.env" "$tmp_env"
  printf 'SMTP_PASSWORD=nao-versionar\n' >> "$INFRA_DIR/apps/$name/app.env"
  if (provision_apps) >"$out" 2>&1; then
    fail "provision_apps aceitou SMTP_PASSWORD no app.env"
  fi
  cp "$tmp_env" "$INFRA_DIR/apps/$name/app.env"
  log_has "não pode ter SMTP_PASSWORD" || { cat "$out"; fail "mensagem inesperada para SMTP no app.env"; }
fi

echo "--- app removida do repo: units desligadas, fora do nginx, código e dados intactos"
old=zz-teste
install -d "$INFRA_DIR/apps/$old"
printf 'PORT=3999\n' > "$INFRA_DIR/apps/$old/app.conf"
printf '[Service]\nExecStart=/bin/sleep infinity\n\n[Install]\nWantedBy=multi-user.target\n' \
  > "$INFRA_DIR/apps/$old/app-$old.service"
printf '[Service]\nType=oneshot\nExecStart=/bin/true\n' > "$INFRA_DIR/apps/$old/$old-job.service"
printf '[Timer]\nOnCalendar=daily\n\n[Install]\nWantedBy=timers.target\n' > "$INFRA_DIR/apps/$old/$old-job.timer"
run_apps
systemctl is-active --quiet "app-$old.service" || fail "app-$old.service não subiu"
systemctl is-active --quiet "$old-job.timer" || fail "$old-job.timer não subiu"
printf 'codigo\n' > "/opt/apps/$old/codigo.txt"
printf 'front\n' > "/var/www/$old/index.html"
install -d /etc/nginx/apps.d
printf '# rotas de %s\n' "$old" > "/etc/nginx/apps.d/$old.conf"
printf '# limit_req_zone de %s\n' "$old" > "/etc/nginx/conf.d/$old.conf"

rm -r "${INFRA_DIR:?}/apps/$old"
run_apps
for unit in "app-$old.service" "$old-job.timer"; do
  log_has "desligado: $unit" || fail "$unit não foi desligada"
  systemctl is-active --quiet "$unit" && fail "$unit continua ativa"
  systemctl is-enabled --quiet "$unit" && fail "$unit continua habilitada"
  [[ -f $UNIT_DIR/$unit ]] || fail "o arquivo de $unit foi apagado"
done
for conf in "/etc/nginx/apps.d/$old.conf" "/etc/nginx/conf.d/$old.conf"; do
  [[ ! -e $conf ]] || fail "$conf continua no nginx"
done
ls /var/backups/infra/nginx-*-"$old".conf.* >/dev/null || fail "cópia da config do nginx não ficou em /var/backups/infra"
[[ $(cat "/opt/apps/$old/codigo.txt") == codigo ]] || fail "código de $old foi mexido"
[[ $(cat "/var/www/$old/index.html") == front ]] || fail "frontend de $old foi mexido"
log_has "AVISO: $old saiu de infra/apps/" || fail "remoção sem aviso no log"
run_apps
if log_has "desligado|removido"; then
  fail "segunda execução depois da remoção mexeu de novo"
fi

echo "--- snapshot.sh apaga pre-deploy-*.db com mais de 7 dias e mantém os recentes"
install -D -m 0644 "$INFRA_DIR/lib/common.sh" "$INFRA_LIB_DIR/common.sh"
printf '%s\n' "${DATABASES[@]}" > "$INFRA_STATE_DIR/databases"
for db in "${DATABASES[@]}"; do
  runuser -u "app-$db" -- sqlite3 "$SQLITE_ROOT/$db/app.db" ".backup $BACKUP_ROOT/$db/pre-deploy-velho.db"
  touch -d '8 days ago' "$BACKUP_ROOT/$db/pre-deploy-velho.db"
  runuser -u "app-$db" -- sqlite3 "$SQLITE_ROOT/$db/app.db" ".backup $BACKUP_ROOT/$db/pre-deploy-novo.db"
done
bash "$INFRA_DIR/scripts/snapshot.sh"
for db in "${DATABASES[@]}"; do
  [[ ! -e $BACKUP_ROOT/$db/pre-deploy-velho.db ]] || fail "$db: pre-deploy de 8 dias não foi apagado"
  [[ -e $BACKUP_ROOT/$db/pre-deploy-novo.db ]] || fail "$db: pre-deploy recente foi apagado"
done

echo "--- smtp.env incompleto avisa"
sed -i '/^SMTP_PASSWORD=/d' "$INFRA_STATE_DIR/smtp.env"
run_apps
log_has "smtp.env sem SMTP_PASSWORD" || fail "smtp.env incompleto não gerou aviso"

echo "--- nome de aplicação fora da regra para o provision"
mkdir "$INFRA_DIR/apps/Nome_Ruim"
if (provision_apps) >"$out" 2>&1; then
  rmdir "$INFRA_DIR/apps/Nome_Ruim"
  fail "provision_apps aceitou infra/apps/Nome_Ruim"
fi
rmdir "$INFRA_DIR/apps/Nome_Ruim"
log_has "nome de aplicação inválido em infra/apps/: 'Nome_Ruim'" || { cat "$out"; fail "mensagem inesperada"; }

echo "ok"
