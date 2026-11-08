#!/usr/bin/env bash
# Monta em <pasta> a config do nginx como o provision instala na VM, para o container nginx:1.24 (o
# mesmo nginx da VM): certificados falsos em le/, o infra/nginx/site.conf em conf.d/default.conf e,
# de cada infra/apps/<nome>/, o nginx.conf em apps.d/<nome>.conf e o nginx-http.conf em
# conf.d/<nome>.conf, com __PORTA__ trocado pelo PORT do app.conf. No container:
#   -v <pasta>/conf.d:/etc/nginx/conf.d:ro -v <pasta>/le:/etc/letsencrypt:ro
#   -v <pasta>/apps.d:/etc/nginx/apps.d:ro
# Roda na raiz do repo, pelo infra.yaml: bash .github/scripts/nginx-stub-config.sh <pasta>
set -euo pipefail

out=${1:?uso: nginx-stub-config.sh <pasta>}
# shellcheck source=infra/config.env
source infra/config.env

mkdir -p "$out/le/live/$SITE_DOMAIN" "$out/apps.d" "$out/conf.d"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$SITE_DOMAIN" \
  -keyout "$out/le/live/$SITE_DOMAIN/privkey.pem" \
  -out "$out/le/live/$SITE_DOMAIN/fullchain.pem" 2>/dev/null
touch "$out/le/options-ssl-nginx.conf"
openssl dhparam -dsaparam -out "$out/le/ssl-dhparams.pem" 2048 2>/dev/null
cp infra/nginx/site.conf "$out/conf.d/default.conf"

for dir in infra/apps/*/; do
  [[ -d $dir ]] || continue
  name=$(basename "$dir")
  port=$(sed -n 's/^PORT=//p' "$dir/app.conf" 2>/dev/null | tail -n1)
  # Como o provision: só dígitos entram na config
  if [[ -n $port && ! $port =~ ^[0-9]{4,5}$ ]]; then
    echo "::error file=$dir/app.conf::PORT inválido: '$port'"
    exit 1
  fi
  if [[ -f $dir/nginx.conf ]]; then
    sed "s/__PORTA__/$port/g" "$dir/nginx.conf" > "$out/apps.d/$name.conf"
  fi
  if [[ -f $dir/nginx-http.conf ]]; then
    sed "s/__PORTA__/$port/g" "$dir/nginx-http.conf" > "$out/conf.d/$name.conf"
  fi
done
