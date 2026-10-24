#!/usr/bin/env bash
# Confere se o PYTHON_VERSION de cada infra/apps/<nome>/app.conf é igual ao
# apps/<nome>/backend/.python-version. Roda na raiz do repo, pelo infra.yaml e pelo ethos.yaml.
set -euo pipefail

status=0
for conf in infra/apps/*/app.conf; do
  [[ -f $conf ]] || continue
  name=$(basename "$(dirname "$conf")")
  infra=$(sed -n 's/^PYTHON_VERSION=//p' "$conf" | tail -n1)
  [[ -n $infra ]] || continue
  pin="apps/$name/backend/.python-version"

  if [[ ! -f $pin ]]; then
    echo "::error file=$conf::$name: PYTHON_VERSION=$infra no app.conf, mas $pin não existe"
    status=1
    continue
  fi

  app=$(tr -d '[:space:]' < "$pin")
  if [[ $infra != "$app" ]]; then
    echo "::error file=$conf::$name: PYTHON_VERSION=$infra no app.conf e $app em $pin"
    status=1
  else
    echo "$name: Python $infra nos dois lugares"
  fi
done

exit "$status"
