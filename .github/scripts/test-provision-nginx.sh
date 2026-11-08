#!/usr/bin/env bash
# Testa provision_nginx num runner Ubuntu 24.04 (o mesmo nginx 1.24 da VM), como root, com
# certificados falsos, arquivos falsos em /var/www e um upstream falso, na porta de cada aplicação,
# que devolve o caminho recebido (no imago, o /internal/session dele responde 200 sem X-User-*: o
# auth_request das aplicações passa, sem usuário). O auth_request em si é testado no
# .github/scripts/test-nginx-auth.sh. Roda na raiz do repo, pelo infra.yaml:
# sudo .github/scripts/test-provision-nginx.sh
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

# Request em https://<domínio><caminho> no nginx local, com os argumentos extras do curl: corpo em
# $out, cabeçalhos em $headers, imprime o status
get() {
  local path=$1
  shift
  curl -sk -o "$out" -D "$headers" -w '%{http_code}' --resolve "$SITE_DOMAIN:443:127.0.0.1" "$@" \
    "https://$SITE_DOMAIN$path"
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
# 0 se infra/apps/$1/nginx.conf tem um location cujo caminho é $2
has_location() {
  grep -qE "^[[:space:]]*location[[:space:]]+(=[[:space:]]*)?$2[[:space:]]*\{" "$INFRA_DIR/apps/$1/nginx.conf" 2>/dev/null
}

mapfile -t apps < <(read_apps)
((${#apps[@]})) || fail "nenhuma aplicação em infra/apps/"

echo "--- certificados falsos, arquivos falsos e upstream falso na porta de cada aplicação"
le=/etc/letsencrypt
install -d "$le/live/$SITE_DOMAIN"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$SITE_DOMAIN" \
  -keyout "$le/live/$SITE_DOMAIN/privkey.pem" -out "$le/live/$SITE_DOMAIN/fullchain.pem" 2>/dev/null
touch "$le/options-ssl-nginx.conf"
openssl dhparam -dsaparam -out "$le/ssl-dhparams.pem" 2048 2>/dev/null
printf 'site\n' > /var/www/html/index.html
install -d /var/www/html/assets
printf 'site-js\n' > /var/www/html/assets/index-abc123.js
ports=()
for name in "${apps[@]}"; do
  install -d "/var/www/$name/assets"
  printf '%s-index\n' "$name" > "/var/www/$name/index.html"
  printf 'js\n' > "/var/www/$name/assets/app-abc123.js"
  port=$(env_get "$INFRA_DIR/apps/$name/app.conf" PORT)
  [[ -z $port ]] || ports+=("$port")
done

python3 -I - "${ports[@]}" <<'EOF' &
import http.server, json, sys, threading

class Echo(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = json.dumps({"path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *args):
        pass

servers = [http.server.ThreadingHTTPServer(("127.0.0.1", int(port)), Echo) for port in sys.argv[1:]]
threads = [threading.Thread(target=server.serve_forever) for server in servers]
for thread in threads:
    thread.start()
EOF
upstream_pid=$!
for port in "${ports[@]}"; do
  for _ in $(seq 1 20); do
    curl -fs "http://127.0.0.1:$port/" >/dev/null && break
    sleep 0.25
  done
  curl -fs "http://127.0.0.1:$port/" >/dev/null || fail "upstream falso não escuta em 127.0.0.1:$port"
done

echo "--- primeira execução instala o site e as rotas das apps"
provision_nginx 2>&1 | tee "$out"
grep -q "atualizado: $NGINX_SITE" "$out" || fail "site.conf não foi instalado"
for name in "${apps[@]}"; do
  port=$(env_get "$INFRA_DIR/apps/$name/app.conf" PORT)
  if [[ -f $INFRA_DIR/apps/$name/nginx.conf ]]; then
    grep -q "atualizado: /etc/nginx/apps.d/$name.conf" "$out" || fail "apps.d/$name.conf não foi instalado"
    grep -q "__PORTA__" "/etc/nginx/apps.d/$name.conf" && fail "__PORTA__ não foi trocado em apps.d/$name.conf"
    grep -q "127.0.0.1:$port/" "/etc/nginx/apps.d/$name.conf" || fail "porta $port não está no apps.d/$name.conf"
  fi
  if [[ -f $INFRA_DIR/apps/$name/nginx-http.conf ]]; then
    grep -q "atualizado: /etc/nginx/conf.d/$name.conf" "$out" || fail "conf.d/$name.conf não foi instalado"
  fi
done

echo "--- segunda execução não muda nada"
provision_nginx 2>&1 | tee "$out"
if grep -q "atualizado\|recarregada\|removido" "$out"; then
  fail "a segunda execução mexeu no nginx"
fi

echo "--- o site em /"
expect "/ status" "$(get /)" 200
expect "/ corpo" "$(cat "$out")" site
expect "/ HSTS" "$(header Strict-Transport-Security)" "$hsts"
expect "/ Cache-Control" "$(header Cache-Control)" no-cache
expect "/ sem a CSP das apps" "$(header Content-Security-Policy)" ""
expect "/rota-do-site cai no index do site" "$(get /projects)" 200
expect "/rota-do-site corpo" "$(cat "$out")" site
expect "/rota-do-site Cache-Control" "$(header Cache-Control)" no-cache
expect "asset do site status" "$(get /assets/index-abc123.js)" 200
expect "asset do site corpo" "$(cat "$out")" site-js
expect "asset do site Cache-Control" "$(header Cache-Control)" "public, max-age=31536000, immutable"
expect "asset do site HSTS" "$(header Strict-Transport-Security)" "$hsts"
expect "asset do site que não existe é 404, não o index.html" "$(get /assets/index-antigo.js)" 404

for name in "${apps[@]}"; do
  if has_location "$name" "/$name/"; then
    echo "--- frontend do $name"
    expect "/$name redireciona" "$(get "/$name")" 301
    expect "/$name Location" "$(header Location)" "https://$SITE_DOMAIN/$name/"
    expect "/$name/ status" "$(get "/$name/")" 200
    expect "/$name/ corpo" "$(cat "$out")" "$name-index"
    expect "/$name/ Cache-Control" "$(header Cache-Control)" no-cache
    security_headers "/$name/"
    expect "$name: rota do SPA status" "$(get "/$name/alguma/tela/42")" 200
    expect "$name: rota do SPA cai no index.html" "$(cat "$out")" "$name-index"
    expect "$name: rota do SPA Cache-Control" "$(header Cache-Control)" no-cache
    expect "$name: asset status" "$(get "/$name/assets/app-abc123.js")" 200
    expect "$name: asset corpo" "$(cat "$out")" js
    expect "$name: asset Cache-Control" "$(header Cache-Control)" "public, max-age=31536000, immutable"
    security_headers "/$name/assets/"
    expect "$name: asset que não existe é 404" "$(get "/$name/assets/nao-existe.js")" 404
    mv "/var/www/$name/index.html" "/var/www/$name/index.html.fora"
    expect "$name: sem index.html (antes do primeiro deploy) é 404, não 500" "$(get "/$name/")" 404
    expect "$name: rota do SPA sem index.html é 404" "$(get "/$name/alguma/tela/42")" 404
    mv "/var/www/$name/index.html.fora" "/var/www/$name/index.html"
  fi

  if has_location "$name" "/api/$name/"; then
    echo "--- API do $name"
    expect "/api/$name/x status" "$(get "/api/$name/x?y=1")" 200
    expect "/api/$name/x chega como /x" "$(cat "$out")" '{"path": "/x?y=1"}'
    security_headers "/api/$name/"
  fi
  if has_location "$name" "/api/$name/health"; then
    expect "/api/$name/health status" "$(get "/api/$name/health")" 200
    expect "/api/$name/health chega como /health" "$(cat "$out")" '{"path": "/health"}'
    security_headers "/api/$name/health"
  fi
  if has_location "$name" "/api/$name/internal/"; then
    expect "/api/$name/internal/x de fora" "$(get "/api/$name/internal/x")" 404
  fi

  if has_location "$name" "/api/$name/auth/"; then
    echo "--- $name: login e rate limit: 16 seguidos em /api/$name/auth/, os últimos 429"
    expect "/api/$name/auth/login status" "$(get "/api/$name/auth/login")" 200
    expect "/api/$name/auth/login chega como /auth/login" "$(cat "$out")" '{"path": "/auth/login"}'
    security_headers "/api/$name/auth/"
    codes=()
    for _ in $(seq 1 16); do
      codes+=("$(get "/api/$name/auth/code" -X POST --data '{}')")
    done
    echo "status: ${codes[*]}"
    expect "$name: último pedido" "${codes[15]}" 429
    rejected=$(printf '%s\n' "${codes[@]}" | grep -c '^429$' || true)
    ((rejected >= 9)) || fail "$name: só $rejected de 16 pedidos receberam 429"
    expect "$name: fora do auth não tem rate limit" "$(get "/api/$name/outra")" 200
  fi
done

echo "--- nginx -t falhando: todos os arquivos voltam, o nginx segue no ar"
# Uma app com nginx.conf e nginx-http.conf: a mudança válida no nginx-http.conf também volta
victim=""
for name in "${apps[@]}"; do
  if [[ -f $INFRA_DIR/apps/$name/nginx.conf && -f $INFRA_DIR/apps/$name/nginx-http.conf ]]; then
    victim=$name
    break
  fi
done
[[ -n $victim ]] || fail "nenhuma app com nginx.conf e nginx-http.conf para o teste de rollback"
installed=("$NGINX_SITE" /etc/nginx/apps.d/*.conf /etc/nginx/conf.d/*.conf)
sha256sum "${installed[@]}" > "$backup"
cp "$INFRA_DIR/apps/$victim/nginx.conf" "$out.nginx"
cp "$INFRA_DIR/apps/$victim/nginx-http.conf" "$out.http"
printf '# mudança válida\n' >> "$INFRA_DIR/apps/$victim/nginx-http.conf"
printf 'diretiva_que_nao_existe;\n' >> "$INFRA_DIR/apps/$victim/nginx.conf"
install -d "$INFRA_DIR/apps/zz-nginx"
printf 'location /zz-nginx/ { return 200; }\n' > "$INFRA_DIR/apps/zz-nginx/nginx.conf"
if (provision_nginx) > "$out" 2>&1; then
  fail "provision_nginx aceitou uma config que não passa no nginx -t"
fi
cp "$out.nginx" "$INFRA_DIR/apps/$victim/nginx.conf"
cp "$out.http" "$INFRA_DIR/apps/$victim/nginx-http.conf"
rm -r "${INFRA_DIR:?}/apps/zz-nginx" "$out.nginx" "$out.http"
grep -q "todos os arquivos anteriores foram restaurados" "$out" || { cat "$out"; fail "mensagem inesperada"; }
sha256sum -c --quiet "$backup" || fail "os arquivos do nginx não voltaram ao que eram"
[[ ! -e /etc/nginx/apps.d/zz-nginx.conf ]] || fail "arquivo novo ficou depois do rollback"
nginx -t -q || fail "nginx -t falha depois do rollback"
expect "/$victim/ depois do rollback" "$(get "/$victim/")" 200

echo "ok"
