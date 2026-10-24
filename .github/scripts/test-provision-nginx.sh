#!/usr/bin/env bash
# Testa provision_nginx num runner Ubuntu 24.04 (o mesmo nginx 1.24 da VM), como root, com
# certificados falsos, arquivos falsos em /var/www e um upstream falso que devolve o caminho recebido.
# Roda na raiz do repo, pelo infra.yaml: sudo .github/scripts/test-provision-nginx.sh
set -euo pipefail

INFRA_DIR=$PWD/infra
# shellcheck source=infra/lib/common.sh
source "$INFRA_DIR/lib/common.sh"
# shellcheck source=infra/config.env
source "$INFRA_DIR/config.env"
# shellcheck source=infra/lib/apps.sh
source "$INFRA_DIR/lib/apps.sh"
# shellcheck source=infra/lib/nginx.sh
source "$INFRA_DIR/lib/nginx.sh"

require_root

fail() {
  echo "::error::$*"
  exit 1
}
out=$(mktemp)
headers=$(mktemp)
backup=$(mktemp)
upstream_pid=""
cleanup() {
  rm -f "$out" "$headers" "$backup"
  if [[ -n $upstream_pid ]]; then
    kill "$upstream_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# GET em https://<domínio><caminho> no nginx local: corpo em $out, cabeçalhos em $headers, imprime o status
get() {
  curl -sk -o "$out" -D "$headers" -w '%{http_code}' --resolve "$SITE_DOMAIN:443:127.0.0.1" \
    "https://$SITE_DOMAIN$1"
}
# Valor do cabeçalho $1 da última resposta (sem o \r)
header() { grep -i "^$1:" "$headers" | head -n1 | cut -d' ' -f2- | tr -d '\r'; }
expect() {
  local desc=$1 got=$2 want=$3
  [[ $got == "$want" ]] || fail "$desc: '$got', esperado '$want'"
  echo "ok     $desc"
}
csp="default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
hsts="max-age=31536000"
security_headers() {
  expect "$1: CSP" "$(header Content-Security-Policy)" "$csp"
  expect "$1: nosniff" "$(header X-Content-Type-Options)" nosniff
  expect "$1: Referrer-Policy" "$(header Referrer-Policy)" same-origin
  expect "$1: HSTS do site continua" "$(header Strict-Transport-Security)" "$hsts"
}

echo "--- certificados falsos, arquivos falsos e upstream falso na porta do ethos"
le=/etc/letsencrypt
install -d "$le/live/$SITE_DOMAIN"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$SITE_DOMAIN" \
  -keyout "$le/live/$SITE_DOMAIN/privkey.pem" -out "$le/live/$SITE_DOMAIN/fullchain.pem" 2>/dev/null
touch "$le/options-ssl-nginx.conf"
openssl dhparam -dsaparam -out "$le/ssl-dhparams.pem" 2048 2>/dev/null
printf 'site\n' > /var/www/html/index.html
install -d /var/www/ethos/assets
printf 'ethos-index\n' > /var/www/ethos/index.html
printf 'js\n' > /var/www/ethos/assets/app-abc123.js

port=$(env_get "$INFRA_DIR/apps/ethos/app.conf" PORT)
python3 - "$port" <<'EOF' &
import http.server, json, sys

class Echo(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), Echo).serve_forever()
EOF
upstream_pid=$!
for _ in $(seq 1 20); do
  curl -fs "http://127.0.0.1:$port/" >/dev/null && break
  sleep 0.25
done

echo "--- primeira execução instala o site e as rotas das apps"
provision_nginx 2>&1 | tee "$out"
grep -q "atualizado: $NGINX_SITE" "$out" || fail "site.conf não foi instalado"
grep -q "atualizado: /etc/nginx/apps.d/ethos.conf" "$out" || fail "apps.d/ethos.conf não foi instalado"
grep -q "atualizado: /etc/nginx/conf.d/ethos.conf" "$out" || fail "conf.d/ethos.conf não foi instalado"
grep -q "__PORTA__" /etc/nginx/apps.d/ethos.conf && fail "__PORTA__ não foi trocado"
grep -q "127.0.0.1:$port/" /etc/nginx/apps.d/ethos.conf || fail "porta $port não está no apps.d/ethos.conf"

echo "--- segunda execução não muda nada"
provision_nginx 2>&1 | tee "$out"
if grep -q "atualizado\|recarregada" "$out"; then
  fail "a segunda execução mexeu no nginx"
fi

echo "--- o site em / continua igual"
expect "/ status" "$(get /)" 200
expect "/ corpo" "$(cat "$out")" site
expect "/ HSTS" "$(header Strict-Transport-Security)" "$hsts"
expect "/ sem CSP do ethos" "$(header Content-Security-Policy)" ""
expect "/rota-do-site cai no index do site" "$(get /projects)" 200
expect "/rota-do-site corpo" "$(cat "$out")" site

echo "--- frontend do ethos"
expect "/ethos redireciona" "$(get /ethos)" 301
expect "/ethos Location" "$(header Location)" "https://$SITE_DOMAIN/ethos/"
expect "/ethos/ status" "$(get /ethos/)" 200
expect "/ethos/ corpo" "$(cat "$out")" ethos-index
expect "/ethos/ Cache-Control" "$(header Cache-Control)" no-cache
security_headers /ethos/
expect "rota do SPA status" "$(get /ethos/habitos/42)" 200
expect "rota do SPA cai no index.html" "$(cat "$out")" ethos-index
expect "rota do SPA Cache-Control" "$(header Cache-Control)" no-cache
expect "asset status" "$(get /ethos/assets/app-abc123.js)" 200
expect "asset corpo" "$(cat "$out")" js
expect "asset Cache-Control" "$(header Cache-Control)" "public, max-age=31536000, immutable"
security_headers /ethos/assets/
expect "asset que não existe é 404" "$(get /ethos/assets/nao-existe.js)" 404

echo "--- API do ethos"
expect "/api/ethos/x status" "$(get '/api/ethos/x?y=1')" 200
expect "/api/ethos/x chega como /x" "$(cat "$out")" '{"path": "/x?y=1"}'
security_headers /api/ethos/
expect "/api/ethos/auth/login status" "$(get /api/ethos/auth/login)" 200
expect "/api/ethos/auth/login chega como /auth/login" "$(cat "$out")" '{"path": "/auth/login"}'
security_headers /api/ethos/auth/

echo "--- rate limit do auth: 16 seguidos, os últimos 429"
codes=()
for _ in $(seq 1 16); do
  codes+=("$(get /api/ethos/auth/code)")
done
echo "status: ${codes[*]}"
expect "último pedido" "${codes[15]}" 429
rejected=$(printf '%s\n' "${codes[@]}" | grep -c '^429$' || true)
((rejected >= 9)) || fail "só $rejected de 16 pedidos receberam 429"
expect "fora do auth não tem rate limit" "$(get /api/ethos/outra)" 200

echo "--- nginx -t falhando: todos os arquivos voltam, o nginx segue no ar"
for f in "$NGINX_SITE" /etc/nginx/apps.d/ethos.conf /etc/nginx/conf.d/ethos.conf; do
  sha256sum "$f"
done > "$backup"
cp "$INFRA_DIR/apps/ethos/nginx.conf" "$out.nginx"
cp "$INFRA_DIR/apps/ethos/nginx-http.conf" "$out.http"
printf '# mudança válida\n' >> "$INFRA_DIR/apps/ethos/nginx-http.conf"
printf 'diretiva_que_nao_existe;\n' >> "$INFRA_DIR/apps/ethos/nginx.conf"
install -d "$INFRA_DIR/apps/zz-nginx"
printf 'location /zz-nginx/ { return 200; }\n' > "$INFRA_DIR/apps/zz-nginx/nginx.conf"
if (provision_nginx) > "$out" 2>&1; then
  fail "provision_nginx aceitou uma config que não passa no nginx -t"
fi
cp "$out.nginx" "$INFRA_DIR/apps/ethos/nginx.conf"
cp "$out.http" "$INFRA_DIR/apps/ethos/nginx-http.conf"
rm -r "${INFRA_DIR:?}/apps/zz-nginx" "$out.nginx" "$out.http"
grep -q "todos os arquivos anteriores foram restaurados" "$out" || { cat "$out"; fail "mensagem inesperada"; }
sha256sum -c --quiet "$backup" || fail "os arquivos do nginx não voltaram ao que eram"
[[ ! -e /etc/nginx/apps.d/zz-nginx.conf ]] || fail "arquivo novo ficou depois do rollback"
nginx -t -q || fail "nginx -t falha depois do rollback"
expect "/ethos/ depois do rollback" "$(get /ethos/)" 200

echo "ok"
