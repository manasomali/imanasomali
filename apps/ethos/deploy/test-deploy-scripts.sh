#!/usr/bin/env bash
# Testa clean-assets.sh e keep-migrations.sh em pastas temporárias, sem root.
# Roda na raiz do repo, pelo ethos.yaml: bash apps/ethos/deploy/test-deploy-scripts.sh
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
out=$work/out

fail() {
  echo "::error::$*"
  exit 1
}

# Saída recuada: um "::error::" no começo da linha viraria anotação de erro no Actions
show() { sed 's/^/    | /' "$1"; }

# Roda o script e falha o teste se ele não falhar com a mensagem esperada
expect_failure() {
  local message=$1
  shift
  if "$@" >"$out" 2>&1; then
    fail "deveria falhar: $*"
  fi
  grep -qF -- "$message" "$out" || { show "$out"; fail "mensagem esperada: $message"; }
}

echo "=== clean-assets.sh"
assets=$work/assets
reset_assets() {
  rm -rf "$assets"
  mkdir -p "$assets/sub"
  # Fora do build, com mais de 7 dias: sai
  touch -d '8 days ago' "$assets/old-orphan.js" "$assets/sub/old-orphan.css"
  # Do build atual com mais de 7 dias (o mesmo hash em vários deploys): fica
  touch -d '30 days ago' "$assets/old-current.js"
  # Fora do build, recentes (versão anterior, de uma aba aberta): ficam
  touch -d '1 day ago' "$assets/new-orphan.js"
  touch -d "@$(( $(date +%s) - 7 * 86400 + 3600 ))" "$assets/almost-7-days.js"
  # Do build atual, novo
  touch "$assets/new-current.js"
}

echo "--- apaga só o que é velho e está fora do build"
reset_assets
bash "$here/clean-assets.sh" "$assets" 7 old-current.js new-current.js | tee "$out"
[[ ! -e $assets/old-orphan.js ]] || fail "arquivo antigo fora do build não foi apagado"
[[ ! -e $assets/sub ]] || fail "subpasta antiga fora do build não foi apagada"
[[ -e $assets/old-current.js ]] || fail "arquivo do build atual com mais de 7 dias foi apagado"
[[ -e $assets/new-orphan.js ]] || fail "arquivo recente fora do build foi apagado"
[[ -e $assets/almost-7-days.js ]] || fail "arquivo com menos de 7 dias foi apagado"
[[ -e $assets/new-current.js ]] || fail "arquivo novo do build atual foi apagado"
grep -qx 'apagado: old-orphan.js' "$out" || fail "o log não lista old-orphan.js"
grep -q '2 apagado(s)' "$out" || fail "contagem errada no log"

echo "--- segunda execução não apaga nada"
bash "$here/clean-assets.sh" "$assets" 7 old-current.js new-current.js | tee "$out"
grep -q '0 apagado(s)' "$out" || fail "a segunda execução apagou algo"

echo "--- caminho em subpasta na lista do build"
reset_assets
bash "$here/clean-assets.sh" "$assets" 7 sub/old-orphan.css new-current.js >/dev/null
[[ -e $assets/sub/old-orphan.css ]] || fail "arquivo do build em subpasta foi apagado"
[[ ! -e $assets/old-orphan.js ]] || fail "arquivo antigo fora do build não foi apagado"

echo "--- recusa sem apagar nada"
reset_assets
expect_failure "lista do build vazia" bash "$here/clean-assets.sh" "$assets" 7
expect_failure "o front foi publicado?" bash "$here/clean-assets.sh" "$assets" 7 new-current.js missing.js
expect_failure "nome inválido" bash "$here/clean-assets.sh" "$assets" 7 ../assets/new-current.js
expect_failure "nome inválido" bash "$here/clean-assets.sh" "$assets" 7 /etc/passwd
expect_failure "nome inválido" bash "$here/clean-assets.sh" "$assets" 7 'a;b.js'
expect_failure "dias inválido" bash "$here/clean-assets.sh" "$assets" 0 new-current.js
expect_failure "dias inválido" bash "$here/clean-assets.sh" "$assets" 7d new-current.js
expect_failure "não existe" bash "$here/clean-assets.sh" "$work/nada" 7 new-current.js
expect_failure "uso:" bash "$here/clean-assets.sh" "$assets"
[[ -e $assets/old-orphan.js ]] || fail "uma execução recusada apagou arquivos"

echo "=== keep-migrations.sh"
# Migração no formato do migrations/script.py.mako
migration() {
  local dir=$1 revision=$2 down=$3
  if [[ $down != None ]]; then
    down="\"$down\""
  fi
  mkdir -p "$dir"
  cat > "$dir/${revision}_m.py" <<EOF
"""Migração $revision.

Revision ID: $revision
Revises: $down
"""

from collections.abc import Sequence

revision: str = "$revision"
down_revision: str | Sequence[str] | None = $down
EOF
}

main_dir=$work/main
reset_target() {
  rm -rf "$work/target"
  mkdir -p "$work/target"
  migration "$work/target" 0001 None
  migration "$work/target" 0002 0001
}
rm -rf "$main_dir"
migration "$main_dir" 0001 None
migration "$main_dir" 0002 0001
migration "$main_dir" 0003 0002
migration "$main_dir" 0004 0003
# Nunca aplicada (ex.: a migração quebrada de um deploy que falhou)
migration "$main_dir" 0005 0004

files() { (cd "$work/target" && printf '%s ' *.py); }

echo "--- banco sem migração: nada muda"
reset_target
bash "$here/keep-migrations.sh" "$work/target" "$main_dir" ""
[[ $(files) == "0001_m.py 0002_m.py " ]] || fail "copiou com o banco vazio: $(files)"

echo "--- revisão do banco no commit (deploy normal, ou rollback de migração que falhou): nada muda"
reset_target
bash "$here/keep-migrations.sh" "$work/target" "$main_dir" 0002
[[ $(files) == "0001_m.py 0002_m.py " ]] || fail "copiou com a revisão no commit: $(files)"
bash "$here/keep-migrations.sh" "$work/target" "$main_dir" 0001
[[ $(files) == "0001_m.py 0002_m.py " ]] || fail "copiou com o banco atrás do commit: $(files)"

echo "--- banco à frente do commit (rollback): copia a cadeia até a revisão do banco, nada depois"
reset_target
bash "$here/keep-migrations.sh" "$work/target" "$main_dir" 0004 | tee "$out"
[[ $(files) == "0001_m.py 0002_m.py 0003_m.py 0004_m.py " ]] || fail "cadeia errada: $(files)"
cmp -s "$main_dir/0004_m.py" "$work/target/0004_m.py" || fail "0004 copiada com outro conteúdo"
grep -q 'mantida: 0003_m.py' "$out" || fail "o log não lista 0003"

echo "--- commit sem nenhuma migração: copia a cadeia inteira"
rm -rf "$work/target" && mkdir -p "$work/target"
bash "$here/keep-migrations.sh" "$work/target" "$main_dir" 0002 >/dev/null
[[ $(files) == "0001_m.py 0002_m.py " ]] || fail "cadeia errada sem migrações no commit: $(files)"

echo "--- recusas"
reset_target
expect_failure "não está no commit nem na main" \
  bash "$here/keep-migrations.sh" "$work/target" "$main_dir" 0009
expect_failure "revisão do banco inválida" \
  bash "$here/keep-migrations.sh" "$work/target" "$main_dir" "0004; rm -rf /"
expect_failure "uso:" bash "$here/keep-migrations.sh" "$work/target" "$main_dir"
migration "$work/merge" 0003 0002
sed -i 's/= "0002"$/= ("0002", "0001")/' "$work/merge/0003_m.py"
expect_failure "merge" bash "$here/keep-migrations.sh" "$work/target" "$work/merge" 0003
reset_target
cp "$work/target/0002_m.py" "$work/target/0002_copia.py"
expect_failure "em dois arquivos" bash "$here/keep-migrations.sh" "$work/target" "$main_dir" 0002

echo "ok"
