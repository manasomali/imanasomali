#!/usr/bin/env bash
# Confere se o PORT de cada infra/apps/<nome>/app.conf é único e aparece na tabela
# "Portas em uso" do infra/README.md, na linha da aplicação. Roda na raiz do repo, pelo infra.yaml.
set -euo pipefail

readme=infra/README.md
status=0
declare -A owner=()

for conf in infra/apps/*/app.conf; do
  [[ -f $conf ]] || continue
  name=$(basename "$(dirname "$conf")")
  port=$(sed -n 's/^PORT=//p' "$conf" | tail -n1)
  [[ -n $port ]] || continue

  if [[ -n ${owner[$port]:-} ]]; then
    echo "::error file=$conf::porta $port de $name já é usada por ${owner[$port]}"
    status=1
  fi
  owner[$port]=$name

  # Linha "| <nome> | <porta> | ..." da tabela
  if ! grep -Eq "^\|[[:space:]]*$name[[:space:]]*\|[[:space:]]*$port[[:space:]]*\|" "$readme"; then
    echo "::error file=$readme::$name usa a porta $port (infra/apps/$name/app.conf), mas a tabela de portas não tem essa linha"
    status=1
  else
    echo "$name: porta $port, única e na tabela"
  fi
done

exit "$status"
