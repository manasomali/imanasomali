#!/usr/bin/env bash
# Limpeza de /var/www/ethos/assets/ depois do deploy do front (passo 9 do deploy).
#
#   clean-assets.sh <pasta> <dias> <arquivo-do-build>...
#
# Apaga da pasta os arquivos modificados há mais de <dias> dias que não estão na lista do build
# atual (caminhos relativos à pasta). O rsync do front não usa --delete: os assets da versão anterior
# ficam, para uma aba aberta com ela não receber 404 ao carregar uma tela. O rsync atualiza a data
# de cada arquivo que continua no build, então a idade conta a partir do último deploy que o usou.
#
# Recusa rodar (sem apagar nada) com a lista vazia ou com um arquivo da lista faltando na pasta: os
# dois sinalizam que o front não foi publicado, e a limpeza apagaria a versão no ar.
#
# Roda na VM pelo SSH (bash -s -- <args> < clean-assets.sh) e no CI pelo test-deploy-scripts.sh.
set -euo pipefail

# Caminho relativo sem "..", sem "/" no início e só com os caracteres dos nomes do Vite
NAME_RE='^[A-Za-z0-9_][A-Za-z0-9._-]*(/[A-Za-z0-9_][A-Za-z0-9._-]*)*$'

die() {
  echo "::error::clean-assets: $*" >&2
  exit 1
}

main() {
  (($# >= 2)) || die "uso: clean-assets.sh <pasta> <dias> <arquivo-do-build>..."
  local dir=$1 days=$2 file removed=0
  shift 2
  local -A keep=()

  [[ $days =~ ^[1-9][0-9]{0,2}$ ]] || die "dias inválido: '$days' (1 a 999)"
  [[ -d $dir ]] || die "$dir não existe"
  (($# > 0)) || die "lista do build vazia: nada é apagado"

  for file in "$@"; do
    [[ $file =~ $NAME_RE ]] || die "nome inválido na lista do build: '$file'"
    [[ -f $dir/$file ]] || die "$file está no build, mas não em $dir: o front foi publicado?"
    keep[$file]=1
  done

  # -mmin: "mais de N dias" exato, sem o arredondamento por dia inteiro do -mtime
  while IFS= read -r -d '' file; do
    [[ -z ${keep[$file]:-} ]] || continue
    rm -f -- "${dir:?}/$file"
    echo "apagado: $file"
    removed=$((removed + 1))
  done < <(find "$dir" -type f -mmin +$((days * 24 * 60)) -printf '%P\0')

  # Subpastas que ficaram vazias (o Vite não cria, mas a regra vale para qualquer build)
  find "$dir" -mindepth 1 -type d -empty -delete

  echo "assets: $removed apagado(s) com mais de $days dias; ${#keep[@]} no build atual"
}

# stdin fechado: rodando por "bash -s", o script vem pelo stdin e nada aqui pode consumi-lo
main "$@" < /dev/null
