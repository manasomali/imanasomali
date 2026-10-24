#!/usr/bin/env bash
# Testa provision_databases e provision_apps num runner Ubuntu, como root, com o usuário do
# runner no papel do usuário de deploy (sudo total sem senha, como o ubuntu da VM).
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

echo "--- primeira execução"
provision_databases
provision_apps

echo "--- segunda execução: não pode criar nem corrigir nada, nem avisar"
{ provision_databases && provision_apps; } 2>&1 | tee "$out"
if grep -qE 'criado|atualizado|AVISO' "$out"; then
  fail "a segunda execução mudou algo ou avisou"
fi

for name in "${apps[@]}"; do
  echo "--- $name"
  stat_is /opt/apps "root 755"
  stat_is "/opt/apps/$name" "$DEPLOY_USER 755"
  stat_is "/var/www/$name" "$DEPLOY_USER 755"
  if [[ -f $INFRA_DIR/apps/$name/app.env ]]; then
    stat_is "$INFRA_STATE_DIR/apps/$name.env" "root 644"
    cmp -s "$INFRA_DIR/apps/$name/app.env" "$INFRA_STATE_DIR/apps/$name.env" \
      || fail "$INFRA_STATE_DIR/apps/$name.env diferente de infra/apps/$name/app.env"
  fi

  if ! id "app-$name" >/dev/null 2>&1; then
    echo "$name sem banco: sem app-$name para testar"
    continue
  fi
  stat_is "$BACKUP_ROOT/$name" "app-$name 700"

  if runuser -u "app-$name" -- touch "/opt/apps/$name/x" 2>/dev/null; then
    fail "app-$name conseguiu escrever em /opt/apps/$name"
  fi
  runuser -u "app-$name" -- test -r "/opt/apps/$name" -a -x "/opt/apps/$name" \
    || fail "app-$name não consegue ler /opt/apps/$name"

  # Os comandos do deploy, como o usuário de deploy e sem senha
  runuser -u "$DEPLOY_USER" -- sudo -n -l systemctl restart "app-$name" >/dev/null \
    || fail "$DEPLOY_USER não pode rodar systemctl restart app-$name com sudo -n"
  runuser -u "$DEPLOY_USER" -- sudo -n -u "app-$name" \
    sqlite3 "$SQLITE_ROOT/$name/app.db" ".backup $BACKUP_ROOT/$name/pre-deploy-teste.db" \
    || fail "backup pré-deploy como app-$name falhou"
  [[ $(stat -c %U "$BACKUP_ROOT/$name/pre-deploy-teste.db") == "app-$name" ]] \
    || fail "pre-deploy-teste.db sem dono app-$name"
done

echo "--- dono ou modo errado é corrigido"
name=${apps[0]}
chmod 0777 "/opt/apps/$name"
provision_apps 2>&1 | tee "$out"
grep -q "atualizado: /opt/apps/$name" "$out" || fail "provision não registrou a correção"
stat_is "/opt/apps/$name" "$DEPLOY_USER 755"

echo "--- restart: só quando smtp.env ou o app.env mudam, e só se a unit estiver rodando"
unit="app-$name.service"
printf '[Service]\nExecStart=/bin/sleep infinity\n' > "/etc/systemd/system/$unit"
systemctl daemon-reload
systemctl start "$unit"
pid() { systemctl show -p MainPID --value "$unit"; }
pid_before=$(pid)
provision_apps 2>&1 | tee "$out"
[[ $(pid) == "$pid_before" ]] || fail "reiniciou sem mudança"
SMTP_CHANGED=1 provision_apps 2>&1 | tee "$out"
grep -q "reiniciado: $unit" "$out" || fail "mudança no smtp.env não reiniciou $unit"
[[ $(pid) != "$pid_before" ]] || fail "$unit não foi reiniciado (mesmo PID)"
if [[ -f $INFRA_DIR/apps/$name/app.env ]]; then
  pid_before=$(pid)
  cp "$INFRA_DIR/apps/$name/app.env" "$tmp_env"
  printf 'TESTE_CI=1\n' >> "$INFRA_DIR/apps/$name/app.env"
  provision_apps 2>&1 | tee "$out"
  cp "$tmp_env" "$INFRA_DIR/apps/$name/app.env"
  grep -q "atualizado: $INFRA_STATE_DIR/apps/$name.env" "$out" || fail "app.env novo não foi instalado"
  [[ $(pid) != "$pid_before" ]] || fail "mudança no app.env não reiniciou $unit"
  provision_apps >/dev/null 2>&1
fi
systemctl stop "$unit"
SMTP_CHANGED=1 provision_apps 2>&1 | tee "$out"
if grep -q "reiniciado: $unit" "$out"; then
  fail "reiniciou uma unit parada"
fi
rm "/etc/systemd/system/$unit"
systemctl daemon-reload

echo "--- app.env com credencial SMTP para o provision; smtp.env incompleto avisa"
if [[ -f $INFRA_DIR/apps/$name/app.env ]]; then
  cp "$INFRA_DIR/apps/$name/app.env" "$tmp_env"
  printf 'SMTP_PASSWORD=nao-versionar\n' >> "$INFRA_DIR/apps/$name/app.env"
  if (provision_apps) >"$out" 2>&1; then
    fail "provision_apps aceitou SMTP_PASSWORD no app.env"
  fi
  cp "$tmp_env" "$INFRA_DIR/apps/$name/app.env"
  grep -q "não pode ter SMTP_PASSWORD" "$out" || { cat "$out"; fail "mensagem inesperada para SMTP no app.env"; }
fi
sed -i '/^SMTP_PASSWORD=/d' "$INFRA_STATE_DIR/smtp.env"
provision_apps 2>&1 | tee "$out"
grep -q "smtp.env sem SMTP_PASSWORD" "$out" || fail "smtp.env incompleto não gerou aviso"

echo "--- snapshot.sh apaga pre-deploy-*.db com mais de 7 dias e mantém os recentes"
install -D -m 0644 "$INFRA_DIR/lib/common.sh" "$INFRA_LIB_DIR/common.sh"
install -d -m 0755 "$INFRA_STATE_DIR"
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

echo "--- nome de aplicação fora da regra para o provision"
mkdir "$INFRA_DIR/apps/Nome_Ruim"
if (provision_apps) >"$out" 2>&1; then
  rmdir "$INFRA_DIR/apps/Nome_Ruim"
  fail "provision_apps aceitou infra/apps/Nome_Ruim"
fi
rmdir "$INFRA_DIR/apps/Nome_Ruim"
grep -q "nome de aplicação inválido em infra/apps/: 'Nome_Ruim'" "$out" || { cat "$out"; fail "mensagem inesperada"; }

echo "ok"
