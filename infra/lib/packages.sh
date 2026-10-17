# Pacotes do sistema e o binário do Litestream (versão fixa + checksum, de config.env).

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
