# Pacotes do sistema, os binários do Litestream e do uv (versão fixa + checksum, de config.env)
# e o Python de cada aplicação.

provision_packages() {
  local pkg missing=()
  for pkg in sqlite3 sysbench nginx curl; do
    # shellcheck disable=SC2016  # ${Status} é formato do dpkg-query, não variável do shell
    if [[ $(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true) != 'install ok installed' ]]; then
      missing+=("$pkg")
    fi
  done

  if ((${#missing[@]})); then
    log "instalando pacotes: ${missing[*]}"
    DEBIAN_FRONTEND=noninteractive apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "${missing[@]}"
  fi

  install_litestream
  install_uv
  install_pythons
}

install_litestream() {
  local bin=/usr/local/bin/litestream tmp url found
  LITESTREAM_UPDATED=0

  if [[ -x $bin && $("$bin" version 2>/dev/null || true) == *"$LITESTREAM_VERSION"* ]]; then
    return 0
  fi

  tmp=$(mktemp -d)
  url="https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-x86_64.tar.gz"
  log "baixando litestream $LITESTREAM_VERSION"
  curl -fsSL --retry 3 -o "$tmp/litestream.tar.gz" "$url"
  echo "$LITESTREAM_SHA256  $tmp/litestream.tar.gz" | sha256sum -c --quiet - \
    || die "checksum do litestream não confere"
  tar -xzf "$tmp/litestream.tar.gz" -C "$tmp"
  found=$(find "$tmp" -type f -name litestream | head -n1)
  [[ -n $found ]] || die "binário do litestream não encontrado no tarball"
  install -m 0755 -o root -g root "$found" "$bin"
  rm -rf "$tmp"

  LITESTREAM_UPDATED=1
  log "litestream instalado: $("$bin" version)"
}

install_uv() {
  local bin=/usr/local/bin/uv tmp url found current got

  current=$("$bin" --version 2>/dev/null || true)
  if [[ $current == "uv $UV_VERSION" || $current == "uv $UV_VERSION "* ]]; then
    return 0
  fi

  tmp=$(mktemp -d)
  url="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
  log "baixando uv $UV_VERSION"
  curl -fsSL --retry 3 -o "$tmp/uv.tar.gz" "$url"
  got=$(sha256sum "$tmp/uv.tar.gz" | cut -d' ' -f1)
  if [[ $got != "$UV_SHA256" ]]; then
    rm -rf "$tmp"
    die "checksum do uv $UV_VERSION não confere com UV_SHA256 do config.env: esperado $UV_SHA256, baixado $got"
  fi
  tar -xzf "$tmp/uv.tar.gz" -C "$tmp"
  found=$(find "$tmp" -type f -name uv | head -n1)
  [[ -n $found ]] || die "binário do uv não encontrado no tarball"
  install -m 0755 -o root -g root "$found" "$bin"
  rm -rf "$tmp"

  log "uv instalado: $("$bin" --version)"
}

# uv com a pasta global de Pythons, rodado a partir de / para não achar .venv, uv.toml nem
# pyproject.toml da pasta de onde o provision foi chamado
uv_global() {
  env -C / UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" UV_NO_CONFIG=1 /usr/local/bin/uv "$@"
}

# Python de cada aplicação (PYTHON_VERSION em infra/apps/<nome>/app.conf), em UV_PYTHON_INSTALL_DIR.
# O uv baixa um build pronto (python-build-standalone) e confere o SHA256: nada é compilado na VM.
# Uma versão que sai dos app.conf continua instalada.
install_pythons() {
  local conf version python
  local -A wanted=()

  for conf in "$INFRA_DIR"/apps/*/app.conf; do
    [[ -f $conf ]] || continue
    version=$(env_get "$conf" PYTHON_VERSION)
    [[ -n $version ]] || continue
    # Só versão completa: com "3.14" o uv escolheria o patch, e um provision seguinte poderia baixar outro
    [[ $version =~ ^3\.[0-9]+\.[0-9]+$ ]] \
      || die "PYTHON_VERSION inválido em $conf: '$version' (use a versão completa, ex.: 3.14.3)"
    wanted[$version]=1
  done
  ((${#wanted[@]})) || return 0

  install -d -m 0755 -o root -g root "$(dirname "$UV_PYTHON_INSTALL_DIR")" "$UV_PYTHON_INSTALL_DIR"

  for version in "${!wanted[@]}"; do
    if uv_global python find --managed-python --no-python-downloads "$version" >/dev/null 2>&1; then
      continue
    fi

    log "instalando python $version"
    # --no-bin: sem atalhos em ~/.local/bin do root; as aplicações usam o caminho completo
    (umask 022 && uv_global python install --no-bin "$version")
    chown -R root:root "$UV_PYTHON_INSTALL_DIR"
    chmod -R go-w "$UV_PYTHON_INSTALL_DIR"

    python=$(uv_global python find --managed-python --no-python-downloads "$version") \
      || die "python $version não aparece no uv depois da instalação"
    [[ $("$python" --version) == "Python $version" ]] \
      || die "$python não é o Python $version: $("$python" --version)"
    log "python instalado: $python"
  done
}
