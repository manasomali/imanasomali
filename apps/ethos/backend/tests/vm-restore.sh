# shellcheck shell=bash
# Ensaio do infra/RESTORE.md ("Restaurar o banco de uma app") com o ethos, num runner Ubuntu 24.04.
# Não roda sozinho: o packages/deploy/test-vm.sh lê este arquivo com "source" depois dos passos do
# deploy, com a .venv instalada e o banco migrado, e usa as variáveis e funções que ele documenta
# no cabeçalho. O ethos.yaml roda:
#
#   sudo bash packages/deploy/test-vm.sh ethos apps/ethos/backend/tests/vm-restore.sh
#
# Com o banco populado pelo seed: backup, uma exclusão de verdade com a linha no journald, o ensaio
# numa cópia, o restore do pre-deploy-<sha>.db e o reapply-deletions pelo systemd-run, duas vezes.
# Fica em tests/ porque ensaia o CLI do backend; o rsync do deploy não leva tests/ para a VM.

# O ambiente da unit app-ethos: o .env.example (dev, email no console) com o banco do teste, lido
# pelo systemd como EnvironmentFile=, como o /etc/infra/apps/ethos.env
env_file=$TEST_ROOT/etc/ethos.env
sed "s|^DATABASE_PATH=.*|DATABASE_PATH=$DB|" "$BACKEND/.env.example" > "$env_file"
chmod 0644 "$env_file"
# O ethos_cli do RESTORE.md, com os caminhos do teste. Sem o --pipe (ethos_unit), a saída vai
# para o journald, como a da unit app-ethos
ethos_unit=(systemd-run --quiet --wait --collect --uid="$APP_USER" --gid="$APP_USER"
  --working-directory="$APP_DIR" -p EnvironmentFile="$env_file" -E PYTHONDONTWRITEBYTECODE=1)
ethos_cli=("${ethos_unit[@]}" --pipe)
python_bin=$APP_DIR/.venv/bin/python
sql() { as_app sqlite3 "$1" "$2"; }
user_id() { sql "$1" "SELECT id FROM users WHERE email = '$2';"; }
reapplied_events() {
  sql "$1" "SELECT count(*) FROM audit_log WHERE event = 'account_deleted'
    AND json_extract(details, '\$.account_id') = $2 AND json_extract(details, '\$.reapplied') = 1;"
}

echo "--- banco populado (seed) pelo systemd-run, como app-ethos"
"${ethos_cli[@]}" "$python_bin" -m app.cli seed | tee "$OUT"
grep -q "seed: 3 contas" "$OUT" || fail "seed não criou as contas"
bia=$(user_id "$DB" bia@example.com)
[[ $bia =~ ^[0-9]+$ ]] || fail "bia@example.com não está no banco"

echo "--- backup antigo (pre-deploy) e, depois dele, a exclusão da Bia com a linha no journald"
old_sha=fedcba9876543210fedcba9876543210fedcba98
vm backup "$old_sha"
old_backup=$BACKUP_DIR/pre-deploy-$old_sha.db
delete_unit=ethos-exclusao-teste-$$
since=$(date '+%Y-%m-%d %H:%M:%S')
# A exclusão de verdade (app/auth/deletion.py), com o log configurado como no servidor
"${ethos_unit[@]}" --unit="$delete_unit" "$python_bin" -c '
import sys
from app.auth.deletion import delete_account
from app.config import load_settings
from app.db import create_db_engine, create_session_factory
from app.logs import configure_logging
settings = load_settings()
configure_logging(settings.app_env)
with create_session_factory(create_db_engine(settings.database_path))() as session:
    account_id = int(sys.argv[1])
    delete_account(session, account_id=account_id, actor_id=account_id, ip=None)
' "$bia"
[[ -z $(user_id "$DB" bia@example.com) ]] || fail "a Bia não foi apagada"
journal() { journalctl -u "$delete_unit" --since "$since" -o cat --no-pager; }
for _ in $(seq 1 20); do
  journal | grep -q "conta $bia excluída" && break
  sleep 0.5
done
journal | grep -x "INFO app.auth.deletion: conta $bia excluída" || fail "a linha da exclusão não chegou ao journald"

echo "--- ensaio numa cópia, com o DATABASE_PATH trocado pelo env (o EnvironmentFile= venceria o -E)"
ensaio_dir=$TEST_ROOT/ensaio
install -d -m 0700 -o "$APP_USER" -g "$APP_USER" "$ensaio_dir"
as_app cp "$old_backup" "$ensaio_dir/app.db"
[[ $(sql "$ensaio_dir/app.db" 'PRAGMA integrity_check;') == ok ]] || fail "integrity_check da cópia"
db_before=$(sha256sum < "$DB")
journal | "${ethos_cli[@]}" /usr/bin/env DATABASE_PATH="$ensaio_dir/app.db" \
  "$python_bin" -m app.cli reapply-deletions | tee "$OUT"
grep -q "1 contas apagadas, 0 ignoradas" "$OUT" || fail "o ensaio não apagou a Bia na cópia"
[[ -z $(user_id "$ensaio_dir/app.db" bia@example.com) ]] || fail "a Bia continua na cópia"
[[ $(sha256sum < "$DB") == "$db_before" ]] || fail "o ensaio mexeu no banco em uso"

echo "--- restore do pre-deploy, na ordem do RESTORE.md"
mv "$DB" "$DB.quebrado"
rm -f "$DB-wal" "$DB-shm"
cp "$old_backup" "$DB"
chown "$APP_USER:$APP_USER" "$DB"
[[ $(sql "$DB" 'PRAGMA integrity_check; PRAGMA journal_mode=WAL;') == $'ok\nwal' ]] || fail "integrity_check ou WAL do restaurado"
[[ -z $(sql "$DB" 'PRAGMA foreign_key_check;') ]] || fail "foreign_key_check do restaurado"
[[ $(user_id "$DB" bia@example.com) == "$bia" ]] || fail "o restore não trouxe a Bia de volta"
"${ethos_cli[@]}" "$APP_DIR/.venv/bin/alembic" upgrade head
# As linhas do journald e um id solto de uma conta que não existe
{ journal; echo 99999; } | "${ethos_cli[@]}" "$python_bin" -m app.cli reapply-deletions | tee "$OUT"
grep -q "1 contas apagadas, 1 ignoradas" "$OUT" || fail "reapply-deletions não apagou a Bia"
[[ -z $(user_id "$DB" bia@example.com) ]] || fail "a Bia voltou depois do reapply-deletions"
[[ $(reapplied_events "$DB" "$bia") == 1 ]] || fail "account_deleted reaplicado ausente ou repetido"

echo "--- reapply-deletions de novo: nada muda"
events=$(sql "$DB" 'SELECT count(*) FROM audit_log;')
{ journal; echo 99999; } | "${ethos_cli[@]}" "$python_bin" -m app.cli reapply-deletions | tee "$OUT"
grep -q "0 contas apagadas, 2 ignoradas" "$OUT" || fail "a segunda execução mudou algo"
[[ $(sql "$DB" 'SELECT count(*) FROM audit_log;') == "$events" ]] || fail "a segunda execução gravou evento"
expect_failure "entrada vazia" "${ethos_cli[@]}" "$python_bin" -m app.cli reapply-deletions < /dev/null
