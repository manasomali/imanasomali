#!/usr/bin/env bash
# Rollback para um commit anterior a uma migração já aplicada (roda no runner, antes do rsync).
#
#   keep-migrations.sh <versions-do-commit> <versions-da-main> <revisão-do-banco>
#
# O ExecStartPre da unit roda "alembic upgrade head". Com o código de um commit antigo, o banco
# pode estar numa revisão que esse commit não conhece, e o Alembic para com "Can't locate
# revision": o serviço não subiria. Como as migrações são só aditivas, o código antigo funciona
# com o banco novo; falta só o arquivo da migração. Este script copia da main para o commit do
# deploy a revisão do banco e as anteriores a ela que faltam (seguindo o down_revision), até
# encontrar uma que o commit já tem. O head passa a ser a revisão do banco e o upgrade não faz nada.
#
# Não copia nada quando o banco não tem migração aplicada (primeiro deploy) ou quando a revisão
# dele já está no commit (deploy normal, ou rollback que não passa por migração aplicada; uma
# migração que falhou não fica aplicada, porque cada upgrade roda numa transação só). Falha se a
# revisão não estiver na main (um arquivo de migração publicado foi apagado ou renomeado).
set -euo pipefail
# Um die dentro de $(...) também para o script
shopt -s inherit_errexit

REVISION_RE='^[A-Za-z0-9_]+$'

die() {
  echo "::error::keep-migrations: $*" >&2
  exit 1
}

# Valor de uma linha "<nome>: <tipo> = "<valor>"" (ou sem o tipo) de um arquivo de migração.
# Vazio para None; "?" para o que não for uma string só (merge de revisões, com tupla)
field() {
  local name=$1 file=$2 line value
  line=$(grep -E "^$name(:[^=]*)? *=" "$file" | head -n1 || true)
  [[ -n $line ]] || die "$file sem $name"
  value=${line#*=}
  value=${value//[[:space:]]/}
  if [[ $value == None ]]; then
    return 0
  fi
  if [[ $value =~ ^[\"\']([A-Za-z0-9_]+)[\"\']$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  else
    printf '?\n'
  fi
}

# Arquivo da pasta que define a revisão; vazio se nenhum define. Chamado como "x=$(...)": a falha
# de um die aqui dentro só sai do subshell, e é a atribuição que para o script (set -e)
find_revision() {
  local dir=$1 revision=$2 file found="" current
  for file in "$dir"/*.py; do
    [[ -f $file ]] || continue
    current=$(field revision "$file")
    if [[ $current == "$revision" ]]; then
      [[ -z $found ]] || die "revisão $revision em dois arquivos: $found e $file"
      found=$file
    fi
  done
  printf '%s\n' "$found"
}

main() {
  (($# == 3)) || die "uso: keep-migrations.sh <versions-do-commit> <versions-da-main> <revisão-do-banco>"
  local target=$1 source=$2 revision=$3 file name present

  [[ -d $target ]] || die "$target não existe"
  [[ -d $source ]] || die "$source não existe"
  if [[ -z $revision ]]; then
    echo "banco sem migração aplicada: nada a manter"
    return 0
  fi
  [[ $revision =~ $REVISION_RE ]] || die "revisão do banco inválida: '$revision'"

  while :; do
    present=$(find_revision "$target" "$revision")
    if [[ -n $present ]]; then
      echo "banco: a revisão $revision está no commit do deploy"
      return 0
    fi
    file=$(find_revision "$source" "$revision")
    [[ -n $file ]] || die "a revisão $revision do banco não está no commit nem na main. Um arquivo de migração publicado foi apagado? Restaure o pre-deploy-<sha>.db (infra/RESTORE.md) ou devolva o arquivo"
    name=$(basename "$file")
    [[ ! -e $target/$name ]] || die "$name existe no commit com outra revisão"
    cp -- "$file" "$target/$name"
    echo "mantida: $name (revisão $revision, já aplicada no banco)"

    revision=$(field down_revision "$file")
    if [[ -z $revision ]]; then
      return 0
    fi
    [[ $revision =~ $REVISION_RE ]] \
      || die "$name tem down_revision com mais de uma revisão (merge): resolva o rollback à mão"
  done
}

main "$@" < /dev/null
