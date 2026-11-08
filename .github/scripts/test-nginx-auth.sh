#!/usr/bin/env bash
# Testa como as aplicações sabem quem é o usuário (imago-plan.md): o auth_request de /api/<app>/
# para o /_imago/session do imago, no container nginx:1.24 (o nginx da VM), com a config de produção
# do site e de infra/apps/ (.github/scripts/nginx-stub-config.sh) e upstreams falsos em 127.0.0.1
# (.github/scripts/nginx-auth/upstreams.py): um imago que devolve X-User-* fixos para os cookies
# "admin" e "comum" e aplicações que ecoam os headers recebidos. A aplicação de teste
# (nginx-auth/teste.conf, o modelo do plano) e toda aplicação de infra/apps/ cujo nginx.conf usa o
# auth_request passam pelos mesmos casos: com cookie, os cinco X-User-* do imago chegam; os mandados
# pelo cliente não chegam em nenhuma rota; com o imago fora, o /health responde e o resto dá 500.
# Também confere as rotas do próprio imago: API interna e /_imago/session de fora (404) e o rate
# limit do login. Roda na raiz do repo, pelo infra.yaml, num Linux com docker (o container usa a
# rede do host para alcançar os upstreams): bash .github/scripts/test-nginx-auth.sh
set -euo pipefail

# shellcheck source=infra/config.env
source infra/config.env

here=$PWD/.github/scripts/nginx-auth
test_port=3998
imago_port=$(sed -n 's/^PORT=//p' infra/apps/imago/app.conf | tail -n1)
tmp=$(mktemp -d)
body=$tmp/body
container=nginx-auth-teste-$$
pids=()
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  if ((${#pids[@]})); then
    kill "${pids[@]}" 2>/dev/null || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

failures=0
fail() {
  echo "::error::$*"
  failures=$((failures + 1))
}
expect() {
  local desc=$1 got=$2 want=$3
  if [[ $got == "$want" ]]; then
    echo "ok     $desc"
  else
    fail "$desc: '$got', esperado '$want'"
  fi
}

# Request em https://<domínio>$1 no nginx do container, com os argumentos extras do curl. Corpo em
# $body; imprime o status (000 se a conexão falhou)
req() {
  local path=$1
  shift
  curl -sk -o "$body" -w '%{http_code}' --resolve "$SITE_DOMAIN:443:127.0.0.1" "$@" \
    "https://$SITE_DOMAIN$path" || true
}
# Os X-User-* que a aplicação recebeu (o eco tem os nomes em minúsculas), em ordem
user_lines() { { grep -iE '^x[-_]user' "$body" || true; } | LC_ALL=C sort; }
first_line() { head -n1 "$body"; }
sorted() { printf '%s\n' "$@" | LC_ALL=C sort; }
# Os paths de location de um arquivo de config do nginx
locations() { sed -nE 's/^[[:space:]]*location[[:space:]]+(=[[:space:]]*)?(\/[^[:space:]{]*).*$/\2/p' "$1"; }
wait_port() {
  local _
  for _ in $(seq 1 40); do
    curl -s -o /dev/null "http://127.0.0.1:$1/" && return 0
    sleep 0.25
  done
  echo "::error::nada escuta em 127.0.0.1:$1"
  exit 1
}

cookie_admin=(-H 'Cookie: outro=1; __Host-imago_session=admin')
cookie_comum=(-H 'Cookie: __Host-imago_session=comum')
cookie_invalid=(-H 'Cookie: __Host-imago_session=vencido')
# O que o imago falso manda para cada cookie (upstreams.py)
admin_lines=$(sorted 'x-user-id: 42' 'x-user-email: ana@example.com' 'x-user-locale: pt' \
  'x-user-timezone: America/Sao_Paulo' 'x-user-admin: 1')
comum_lines=$(sorted 'x-user-id: 43' 'x-user-email: bia@example.com' 'x-user-locale: en' \
  'x-user-timezone: Europe/Lisbon')
# O que o cliente forja: outros valores, o admin, o nome repetido em minúsculas e com _ no lugar de -
forged=(-H 'X-User-Id: 666' -H 'X-User-Email: intruso@example.com' -H 'X-User-Locale: xx'
  -H 'X-User-Timezone: Asia/Tokyo' -H 'X-User-Admin: 1' -H 'x-user-id: 667' -H 'X_User_Admin: 1')

echo "--- config de produção, a aplicação de teste e os upstreams falsos"
bash .github/scripts/nginx-stub-config.sh "$tmp/nginx"
sed "s/__PORTA__/$test_port/g" "$here/teste.conf" > "$tmp/nginx/apps.d/zz-teste.conf"

# Aplicações com auth_request: a de teste e as de infra/apps/ que já usam (conf em apps.d)
declare -A conf_of=([teste]="$tmp/nginx/apps.d/zz-teste.conf")
auth_apps=(teste)
echo_ports=("$test_port")
for dir in infra/apps/*/; do
  name=$(basename "$dir")
  [[ $name != imago ]] || continue
  port=$(sed -n 's/^PORT=//p' "$dir/app.conf" | tail -n1)
  echo_ports+=("$port")
  if grep -qE '^[[:space:]]*auth_request[[:space:]]+/_imago/session;' "$tmp/nginx/apps.d/$name.conf" 2>/dev/null; then
    auth_apps+=("$name")
    conf_of[$name]=$tmp/nginx/apps.d/$name.conf
  fi
done
echo "aplicações com auth_request: ${auth_apps[*]}"

python3 -I "$here/upstreams.py" echo "${echo_ports[@]}" &
pids+=("$!")
python3 -I "$here/upstreams.py" imago "$imago_port" "$tmp/session" &
imago_pid=$!
pids+=("$imago_pid")
for port in "${echo_ports[@]}" "$imago_port"; do
  wait_port "$port"
done

docker run -d --name "$container" --network host \
  -v "$tmp/nginx/conf.d:/etc/nginx/conf.d:ro" \
  -v "$tmp/nginx/le:/etc/letsencrypt:ro" \
  -v "$tmp/nginx/apps.d:/etc/nginx/apps.d:ro" \
  nginx:1.24 >/dev/null
for _ in $(seq 1 40); do
  [[ $(req /api/teste/health) == 200 ]] && break
  sleep 0.25
done
if [[ $(req /api/teste/health) != 200 ]]; then
  docker logs "$container"
  echo "::error::o nginx do container não subiu"
  exit 1
fi

for name in "${auth_apps[@]}"; do
  prefix=/api/$name
  echo "--- $name: com cookie, os cinco X-User-* do imago chegam; os do cliente, nunca"
  expect "$name: GET com cookie de admin" "$(req "$prefix/x?y=1" "${cookie_admin[@]}" "${forged[@]}")" 200
  expect "$name: chega sem o prefixo" "$(first_line)" "GET /x?y=1"
  expect "$name: os cinco do imago, só uma vez cada" "$(user_lines)" "$admin_lines"
  expect "$name: POST com cookie de admin" \
    "$(req "$prefix/x" -X POST --data 'corpo' "${cookie_admin[@]}" "${forged[@]}")" 200
  expect "$name: POST chega como POST" "$(first_line)" "POST /x"
  expect "$name: POST com os cinco do imago" "$(user_lines)" "$admin_lines"
  expect "$name: cookie de quem não é admin" "$(req "$prefix/x" "${cookie_comum[@]}" "${forged[@]}")" 200
  expect "$name: sem X-User-Admin, nem o forjado" "$(user_lines)" "$comum_lines"
  expect "$name: cookie que não vale" "$(req "$prefix/x" "${cookie_invalid[@]}" "${forged[@]}")" 200
  expect "$name: cookie que não vale, nenhum X-User-*" "$(user_lines)" ""
  expect "$name: sem cookie" "$(req "$prefix/x" "${forged[@]}")" 200
  expect "$name: sem cookie, nenhum X-User-*" "$(user_lines)" ""
  expect "$name: sem cookie nem forjados" "$(req "$prefix/x")" 200
  expect "$name: sem cookie nem forjados, nenhum X-User-*" "$(user_lines)" ""

  echo "--- $name: /health fora do auth_request, sem X-User-*"
  expect "$name: /health com cookie" "$(req "$prefix/health" "${cookie_admin[@]}" "${forged[@]}")" 200
  expect "$name: /health chega como /health" "$(first_line)" "GET /health"
  expect "$name: /health com cookie, nenhum X-User-*" "$(user_lines)" ""
  expect "$name: /health sem cookie" "$(req "$prefix/health" "${forged[@]}")" 200
  expect "$name: /health sem cookie, nenhum X-User-*" "$(user_lines)" ""

  echo "--- $name: API interna fora do nginx"
  expect "$name: /internal/x" "$(req "$prefix/internal/x" "${cookie_admin[@]}")" 404
  expect "$name: /%69nternal/x" "$(req "$prefix/%69nternal/x" --path-as-is)" 404
  expect "$name: //internal/x" "$(req "$prefix//internal/x" --path-as-is)" 404
  expect "$name: /x/../internal/x" "$(req "$prefix/x/../internal/x" --path-as-is)" 404

  echo "--- $name: nenhum X-User-* do cliente em nenhuma rota"
  while IFS= read -r route; do
    [[ $route == "$prefix"* ]] || continue
    path=$route
    [[ $path != */ ]] || path+=rota
    status=$(req "$path" "${cookie_comum[@]}" "${forged[@]}")
    case $status in
      200)
        lines=$(user_lines)
        if [[ -n $lines && $lines != "$comum_lines" ]]; then
          fail "$name: $path com cookie recebeu: $(tr '\n' '|' <<< "$lines")"
        else
          echo "ok     $name: $path com cookie e forjados"
        fi
        ;;
      404 | 429) echo "ok     $name: $path com cookie e forjados ($status, não chega ao backend)" ;;
      *) fail "$name: $path com cookie respondeu $status" ;;
    esac
    status=$(req "$path" "${forged[@]}")
    if [[ $status == 200 && -n $(user_lines) ]]; then
      fail "$name: $path sem cookie recebeu X-User-*: $(user_lines | tr '\n' '|')"
    else
      echo "ok     $name: $path sem cookie ($status)"
    fi
  done < <(locations "${conf_of[$name]}")
done

echo "--- o subrequest para o imago: GET, sem corpo, com o cookie e o IP de quem chamou"
expect "POST com corpo e IP forjado" "$(req /api/teste/x -X POST --data 'corpo' "${cookie_admin[@]}" \
  -H 'X-Forwarded-For: 6.6.6.6' -H 'X-Real-IP: 6.6.6.6')" 200
expect "imago recebe GET /internal/session" "$(head -n1 "$tmp/session")" "GET /internal/session"
expect "imago recebe o cookie" "$(grep -c '^cookie: .*__Host-imago_session=admin' "$tmp/session" || true)" 1
expect "imago recebe o X-Real-IP do nginx" "$(sed -n 's/^x-real-ip: //p' "$tmp/session")" 127.0.0.1
expect "imago recebe só o IP de quem chamou no X-Forwarded-For" \
  "$(sed -n 's/^x-forwarded-for: //p' "$tmp/session")" 127.0.0.1
expect "imago não recebe o corpo" "$(grep -ci '^content-length: [1-9]' "$tmp/session" || true)" 0

echo "--- rotas do imago"
expect "/api/imago/x" "$(req /api/imago/x)" 200
expect "/api/imago/x chega como /x" "$(first_line)" "GET /x"
expect "/api/imago/internal/session de fora" "$(req /api/imago/internal/session "${cookie_admin[@]}")" 404
expect "/api/imago/%69nternal/session" "$(req /api/imago/%69nternal/session --path-as-is)" 404
expect "/api/imago//internal/session" "$(req /api/imago//internal/session --path-as-is)" 404
expect "/_imago/session de fora" "$(req /_imago/session "${cookie_admin[@]}")" 404
expect "/_imago/session de fora, POST" "$(req /_imago/session -X POST --data '' "${cookie_admin[@]}")" 404

echo "--- rate limit do login: 16 seguidos em /api/imago/auth/, os últimos 429"
expect "/api/imago/auth/ chega como /auth/" "$(req /api/imago/auth/code/request -X POST --data '{}')" 200
expect "/api/imago/auth/code/request" "$(first_line)" "POST /auth/code/request"
codes=()
for _ in $(seq 1 16); do
  codes+=("$(req /api/imago/auth/code/request -X POST --data '{}')")
done
echo "status: ${codes[*]}"
expect "último pedido" "${codes[15]}" 429
rejected=$(printf '%s\n' "${codes[@]}" | grep -c '^429$' || true)
((rejected >= 9)) || fail "só $rejected de 16 pedidos receberam 429"
expect "fora do /auth/ não tem rate limit" "$(req /api/imago/me)" 200

echo "--- com o imago fora: /health responde, o resto dá 500"
kill "$imago_pid"
wait "$imago_pid" 2>/dev/null || true
for name in "${auth_apps[@]}"; do
  expect "$name: /health sem o imago" "$(req "/api/$name/health")" 200
  expect "$name: /x sem o imago" "$(req "/api/$name/x" "${cookie_admin[@]}")" 500
  # Login próprio de uma aplicação que ainda não passou para o imago: não depende dele
  if grep -qE "^[[:space:]]*location[[:space:]]+/api/$name/auth/[[:space:]]*\{" "${conf_of[$name]}"; then
    expect "$name: /api/$name/auth/ (login próprio) sem o imago" "$(req "/api/$name/auth/x")" 200
    expect "$name: /api/$name/auth/ chega como /auth/x" "$(first_line)" "GET /auth/x"
  fi
done

if ((failures)); then
  echo "$failures falha(s)"
  exit 1
fi
echo "ok"
