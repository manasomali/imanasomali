#!/usr/bin/env bash
# Testa install_uv e install_pythons de infra/lib/packages.sh num runner Ubuntu, como root.
# Roda na raiz do repo, pelo infra.yaml: sudo .github/scripts/test-install-uv.sh
set -euo pipefail

INFRA_DIR=$PWD/infra
# shellcheck source=infra/lib/common.sh
source "$INFRA_DIR/lib/common.sh"
# shellcheck source=infra/config.env
source "$INFRA_DIR/config.env"
# shellcheck source=infra/lib/packages.sh
source "$INFRA_DIR/lib/packages.sh"

require_root

fail() {
  echo "::error::$*"
  exit 1
}

out=$(mktemp)
trap 'rm -f "$out"' EXIT

echo "--- primeira instalação"
install_uv
install_pythons

echo "--- segunda execução: não pode baixar nem instalar nada"
{ install_uv && install_pythons; } 2>&1 | tee "$out"
if grep -qE 'baixando|instalando|instalado' "$out"; then
  fail "a segunda execução baixou ou instalou de novo"
fi

echo "--- permissões de $UV_PYTHON_INSTALL_DIR"
[[ $(stat -c '%U %a' "$UV_PYTHON_INSTALL_DIR") == "root 755" ]] \
  || fail "$UV_PYTHON_INSTALL_DIR: $(stat -c '%U %a' "$UV_PYTHON_INSTALL_DIR"), esperado root 755"
writable=$(find "$UV_PYTHON_INSTALL_DIR" ! -type l \( -perm -g+w -o -perm -o+w \) | head -n5)
[[ -z $writable ]] || fail "arquivos graváveis por outros usuários: $writable"
not_root=$(find "$UV_PYTHON_INSTALL_DIR" ! -user root | head -n5)
[[ -z $not_root ]] || fail "arquivos sem dono root: $not_root"

echo "--- Python de cada app.conf, rodado por um usuário sem home (como app-<nome>)"
# Sem home, o uv não cria ~/.cache/uv: UV_NO_CACHE usa um cache temporário
for conf in "$INFRA_DIR"/apps/*/app.conf; do
  version=$(env_get "$conf" PYTHON_VERSION)
  [[ -n $version ]] || continue
  python=$(runuser -u nobody -- env UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" UV_NO_CONFIG=1 UV_NO_CACHE=1 \
    /usr/local/bin/uv python find --managed-python --no-python-downloads "$version") \
    || fail "nobody não encontra o Python $version"
  [[ $python == "$UV_PYTHON_INSTALL_DIR"/* ]] || fail "$python fora de $UV_PYTHON_INSTALL_DIR"
  got=$(runuser -u nobody -- "$python" --version)
  [[ $got == "Python $version" ]] || fail "$python --version: $got"
  echo "$conf: $python ($got)"
done

echo "--- checksum errado: o provision precisa parar com mensagem clara"
rm -f /usr/local/bin/uv
if (UV_SHA256=$(printf '0%.0s' {1..64}) install_uv) >"$out" 2>&1; then
  fail "install_uv aceitou um checksum errado"
fi
cat "$out"
grep -q 'checksum do uv .* não confere com UV_SHA256 do config.env' "$out" \
  || fail "mensagem de checksum errado diferente da esperada"
[[ ! -e /usr/local/bin/uv ]] || fail "uv instalado mesmo com checksum errado"

echo "ok"
