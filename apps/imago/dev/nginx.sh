#!/usr/bin/env bash
# nginx de desenvolvimento do imago e das aplicações (imago-plan.md, "desenvolvimento local"): o
# nginx:1.24 da VM, em container, como origem única http://localhost:8080, com as rotas de produção
# de cada aplicação (infra/apps/*/nginx.conf e nginx-http.conf) na frente dos backends rodando na
# máquina, nas portas de produção (o PORT de cada infra/apps/<nome>/app.conf). Como no provision,
# __PORTA__ vira o PORT; e 127.0.0.1, que no container é o próprio container, vira
# host.docker.internal (a máquina). Como usar: apps/imago/dev/README.md.
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
uso: nginx.sh up [--vite] [--host-network]   sobe o nginx em primeiro plano (Ctrl+C para)
     nginx.sh check                          nginx -t nas configs de dev (roda no CI)
     nginx.sh render <pasta> [--vite] [--host-network]   só gera a config em <pasta>

  --vite           o front de cada aplicação vem do dev server do Vite (com HMR), não do dist/
  --host-network   rede do host (Linux sem Docker Desktop): os backends ficam em 127.0.0.1
EOF
  exit 2
}

dev=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$dev/../../.." && pwd)
image=nginx:1.24
listen=8080
container=imago-dev-nginx
# Porta do dev server do Vite de cada aplicação (server.port do vite.config.js dela)
declare -A vite_port=([ethos]=5174 [imago]=5175)

die() {
  echo "erro: $*" >&2
  exit 1
}

# No Git Bash (Windows) o docker recebe os argumentos sem a conversão de caminhos do MSYS, e os
# caminhos da máquina no formato do Windows (C:/...)
if command -v cygpath >/dev/null 2>&1; then
  export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
  host_path() { cygpath -m "$1"; }
else
  host_path() { printf '%s' "$1"; }
fi

# --mount de leitura de uma pasta da máquina ($1) no container ($2)
mount_arg() { printf -- '--mount=type=bind,source=%s,target=%s,readonly' "$(host_path "$1")" "$2"; }

# Location do front da aplicação $1 pelo Vite em $2:$3
vite_location() {
  cat <<EOF
# Gerado pelo apps/imago/dev/nginx.sh --vite: o front do $1 vem do dev server do Vite, com HMR. É um
# location de regex, que vence os location /$1/ e /$1/assets/ de produção (prefixos sem ^~)
location ~ ^/$1/ {
        proxy_pass http://$2:$3;
        proxy_http_version 1.1;
        # O Vite recusa Host desconhecido; localhost:$listen ele aceita
        proxy_set_header Host \$http_host;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
}
EOF
}

# Gera em $1 o conf.d (server de dev e nginx-http.conf) e o apps.d (nginx.conf de cada aplicação).
# $2=1: front pelo Vite. $3: o endereço dos backends visto do container (127.0.0.1: rede do host)
render() {
  local out=${1:?} vite=$2 upstream=$3 dir name port file dest address=$listen
  # Com a rede do host, o nginx escuta direto na máquina: só na interface local, como o -p do up
  # faz na rede do Docker
  [[ $upstream != 127.0.0.1 ]] || address=127.0.0.1:$listen
  rm -rf "$out"
  mkdir -p "$out/conf.d" "$out/apps.d"
  sed "s/__LISTEN__/$address/" "$dev/server.conf" > "$out/conf.d/00-dev.conf"
  for dir in "$repo"/infra/apps/*/; do
    [[ -d $dir ]] || continue
    name=$(basename "$dir")
    port=$(sed -n 's/^PORT=//p' "$dir/app.conf" 2>/dev/null | tail -n1)
    [[ -z $port || $port =~ ^[0-9]{4,5}$ ]] || die "PORT inválido em infra/apps/$name/app.conf: '$port'"
    for file in nginx.conf nginx-http.conf; do
      [[ -f $dir/$file ]] || continue
      if [[ -z $port ]] && grep -q __PORTA__ "$dir/$file"; then
        die "infra/apps/$name/$file usa __PORTA__, mas infra/apps/$name/app.conf não tem PORT"
      fi
      if [[ $file == nginx.conf ]]; then
        dest=$out/apps.d/$name.conf
      else
        dest=$out/conf.d/app-$name.conf
      fi
      sed -e "s/__PORTA__/$port/g" -e "s/127\.0\.0\.1/$upstream/g" "$dir/$file" > "$dest"
    done
    if ((vite)) && [[ -n ${vite_port[$name]:-} ]]; then
      vite_location "$name" "$upstream" "${vite_port[$name]}" > "$out/apps.d/vite-$name.conf"
    fi
  done
}

# Lê as opções de up e render
parse_options() {
  vite=0
  host_network=0
  upstream=host.docker.internal
  while (($#)); do
    case $1 in
      --vite) vite=1 ;;
      --host-network)
        host_network=1
        upstream=127.0.0.1
        ;;
      *) usage ;;
    esac
    shift
  done
}

up() {
  local out=$dev/.generated dir name port
  local -a args
  parse_options "$@"
  command -v docker >/dev/null 2>&1 || die "docker não encontrado"
  render "$out" "$vite" "$upstream"

  args=(--rm --name "$container" --add-host=host.docker.internal:host-gateway
    "$(mount_arg "$out/conf.d" /etc/nginx/conf.d)" "$(mount_arg "$out/apps.d" /etc/nginx/apps.d)")
  if ((host_network)); then
    args+=(--network host)
  else
    # Só na interface local da máquina
    args+=(-p "127.0.0.1:$listen:$listen")
  fi

  echo "nginx de dev em http://localhost:$listen (Ctrl+C para). Backends esperados na máquina:"
  for dir in "$repo"/infra/apps/*/; do
    name=$(basename "$dir")
    port=$(sed -n 's/^PORT=//p' "$dir/app.conf" 2>/dev/null | tail -n1)
    [[ -z $port ]] || echo "  $name: 127.0.0.1:$port, com APP_URL=http://localhost:$listen/$name"
    # Front de produção (npm run build): o dist/ de cada aplicação em /var/www/<nome>, como na VM
    if ((vite)) && [[ -n ${vite_port[$name]:-} ]]; then
      echo "  $name: front pelo Vite em 127.0.0.1:${vite_port[$name]} (npm run dev)"
    elif [[ -f $repo/apps/$name/frontend/dist/index.html ]]; then
      args+=("$(mount_arg "$repo/apps/$name/frontend/dist" "/var/www/$name")")
    else
      echo "  $name: sem apps/$name/frontend/dist (npm run build): /$name/ dá 404" >&2
    fi
  done
  exec docker run "${args[@]}" "$image"
}

# nginx -t nas configs de dev, com o front do dist/ e com o do Vite. O host.docker.internal precisa
# existir no container (o nginx resolve os upstreams no -t): no Linux, pelo --add-host
check() {
  local tmp vite front
  command -v docker >/dev/null 2>&1 || die "docker não encontrado"
  tmp=$(mktemp -d)
  # shellcheck disable=SC2064  # o caminho é fixo a partir daqui
  trap "rm -rf '$tmp'" EXIT
  for vite in 0 1; do
    render "$tmp/$vite" "$vite" host.docker.internal
    if grep -rlE '__PORTA__|127\.0\.0\.1' "$tmp/$vite"; then
      die "sobrou __PORTA__ ou 127.0.0.1 na config gerada (arquivos acima)"
    fi
    front=dist/
    ((vite == 0)) || front=Vite
    echo "--- nginx -t (front pelo $front)"
    docker run --rm --add-host=host.docker.internal:host-gateway \
      "$(mount_arg "$tmp/$vite/conf.d" /etc/nginx/conf.d)" "$(mount_arg "$tmp/$vite/apps.d" /etc/nginx/apps.d)" \
      "$image" nginx -t
  done
}

case ${1:-} in
  up)
    shift
    up "$@"
    ;;
  check)
    (($# == 1)) || usage
    check
    ;;
  render)
    (($# >= 2)) || usage
    out=$2
    shift 2
    parse_options "$@"
    render "$out" "$vite" "$upstream"
    ;;
  *) usage ;;
esac
