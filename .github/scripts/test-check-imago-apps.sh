#!/usr/bin/env bash
# Testa o check-imago-apps.sh num repo falso (pasta temporária): passa com tudo certo e falha, com
# a mensagem certa, com porta errada, aplicação faltando, texto faltando e os outros erros de formato.
# Roda na raiz do repo, pelo infra.yaml: bash .github/scripts/test-check-imago-apps.sh
set -euo pipefail

script=$PWD/.github/scripts/check-imago-apps.sh
repo=$(mktemp -d)
trap 'rm -rf "$repo"' EXIT
out=$repo/.saida

failures=0
fail() {
  echo "FALHOU: $*"
  failures=$((failures + 1))
}

texts() {
  local name
  printf '{\n  "apps": {\n'
  for name in "$@"; do
    printf '    "%s": {"name": "%s", "description": "d", "deletion": "x", "export_label": "e", "export_path": "/%s/relatorio"},\n' \
      "$name" "$name" "$name"
  done
  printf '    "_": {}\n  },\n  "outra": "chave"\n}\n'
}

# O repo falso no estado em que o script passa
reset() {
  rm -rf "${repo:?}/infra" "${repo:?}/apps"
  mkdir -p "$repo/infra/apps/imago" "$repo/infra/apps/ethos" "$repo/infra/apps/engrafi"
  printf 'PORT=3003\n' > "$repo/infra/apps/imago/app.conf"
  printf '# config\nPORT=3001\n' > "$repo/infra/apps/ethos/app.conf"
  printf 'PORT=3002\n' > "$repo/infra/apps/engrafi/app.conf"
  printf 'APP_ENV=prod\nIMAGO_APPS=ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002\n' \
    > "$repo/infra/apps/imago/app.env"
  for language in pt en; do
    mkdir -p "$repo/apps/imago/frontend/public/locales/$language"
    texts ethos engrafi > "$repo/apps/imago/frontend/public/locales/$language/translation.json"
  done
}
set_apps() { sed -i "s|^IMAGO_APPS=.*|IMAGO_APPS=$1|" "$repo/infra/apps/imago/app.env"; }
locale_file() { printf '%s' "$repo/apps/imago/frontend/public/locales/$1/translation.json"; }
run_check() { (cd "$repo" && bash "$script") > "$out" 2>&1; }

passes() {
  local desc=$1
  if run_check; then
    echo "ok     $desc"
  else
    cat "$out"
    fail "$desc: o script falhou"
  fi
}
fails_with() {
  local desc=$1 message=$2
  if run_check; then
    cat "$out"
    fail "$desc: o script passou"
  elif ! grep -qF -- "$message" "$out"; then
    cat "$out"
    fail "$desc: sem a mensagem '$message'"
  else
    echo "ok     $desc"
  fi
}

reset
passes "tudo certo"

set_apps '"ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002"'
passes "valor entre aspas duplas"

reset
set_apps 'ethos=http://127.0.0.1:3009,engrafi=http://127.0.0.1:3002'
fails_with "porta errada" "ethos na porta 3009, mas o PORT de infra/apps/ethos/app.conf é '3001'"

reset
set_apps 'ethos=http://127.0.0.1:3001'
fails_with "aplicação faltando" "engrafi está em infra/apps/, mas não no IMAGO_APPS"

reset
set_apps ''
fails_with "IMAGO_APPS vazio" "ethos está em infra/apps/, mas não no IMAGO_APPS"

reset
sed -i 's/"deletion": "x", //' "$(locale_file pt)"
fails_with "texto faltando em pt" "falta o texto apps.ethos.deletion"

reset
sed -i 's/"export_label": "e"/"export_label": " "/' "$(locale_file en)"
fails_with "texto vazio em en" "falta o texto apps.ethos.export_label"

reset
texts ethos > "$(locale_file en)"
fails_with "aplicação sem textos" "falta o texto apps.engrafi.name"

reset
sed -i 's|"/engrafi/relatorio"|"engrafi/relatorio"|' "$(locale_file pt)"
fails_with "export_path relativo" "apps.engrafi.export_path tem de ser um caminho do site"

reset
rm "$(locale_file en)"
fails_with "arquivo de tradução faltando" "translation.json não existe"

reset
printf '{"apps": ' > "$(locale_file pt)"
fails_with "JSON quebrado" "não é um JSON válido"

reset
set_apps 'ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002,outra=http://127.0.0.1:3004'
fails_with "aplicação fora de infra/apps/" "outra não tem infra/apps/outra/app.conf"

reset
set_apps 'ethos=http://localhost:3001,engrafi=http://127.0.0.1:3002'
fails_with "host diferente de 127.0.0.1" "ethos com 'http://localhost:3001'"

reset
set_apps 'ethos=http://127.0.0.1:3001/api,engrafi=http://127.0.0.1:3002'
fails_with "URL com caminho" "ethos com 'http://127.0.0.1:3001/api'"

reset
set_apps 'ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002,ethos=http://127.0.0.1:3001'
fails_with "aplicação repetida" "ethos aparece mais de uma vez"

reset
set_apps 'ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002,imago=http://127.0.0.1:3003'
fails_with "o imago na própria lista" "o imago não entra na própria lista"

reset
set_apps 'ethos=http://127.0.0.1:3001,Engrafi=http://127.0.0.1:3002'
fails_with "nome fora da regra" "entrada 'Engrafi=http://127.0.0.1:3002' fora do formato"

reset
rm "$repo/infra/apps/imago/app.env"
fails_with "sem o app.env do imago" "infra/apps/imago/app.env não existe"

if ((failures)); then
  echo "$failures falha(s)"
  exit 1
fi
echo "ok"
