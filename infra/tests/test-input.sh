#!/usr/bin/env bash
# Testa lib/input.sh: validação do stdin por chave, escrita para EnvironmentFile= e que nenhum
# valor aparece em mensagem. Roda na raiz do repo, pelo infra.yaml: sudo bash infra/tests/test-input.sh
# Como root (CI), confere cada valor gravado lendo o arquivo com o próprio systemd.
set -euo pipefail

INFRA_DIR=$PWD/infra
# shellcheck source=infra/lib/common.sh
source "$INFRA_DIR/lib/common.sh"
# shellcheck source=infra/lib/input.sh
source "$INFRA_DIR/lib/input.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
env_file=$tmp/smtp.env
all_output=$tmp/output
keys=(SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD)

failures=0
fail() {
  echo "FALHOU: $*"
  failures=$((failures + 1))
}
# assert "descrição" comando...: ok se o comando passa
assert() {
  local desc=$1
  shift
  if "$@"; then
    echo "ok     $desc"
  else
    fail "$desc"
  fi
}
not() { ! "$@"; }
# write_env_file com a saída guardada para a checagem final; status 0 se o arquivo mudou
write_smtp() { write_env_file "$env_file" 0600 "${keys[@]}" >> "$all_output" 2>&1; }
# Recomeça INPUT e lê $1 como stdin
load_input() {
  INPUT=()
  read_stdin_config < "$1"
}

# Valores difíceis e o que precisa sair do outro lado
user='app@smtp-brevo.com'
password='a b"c'"'"'d$HOME`x`\n\\fim @ #'
cat > "$tmp/in" <<EOF
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=$user
SMTP_PASSWORD=$password
LITESTREAM_ACCESS_KEY_ID=abc+/=:.-123
EOF

echo "--- valores com @, espaço, aspas, \$, crase e barra"
load_input "$tmp/in"
assert "arquivo gravado" write_smtp
assert "modo 600" test "$(stat -c '%a' "$env_file")" = 600
assert "4 chaves SMTP_" test "$(grep -c '^SMTP_' "$env_file")" = 4
assert "valor seguro gravado sem aspas" grep -qx 'SMTP_USER=app@smtp-brevo.com' "$env_file"

# O bash lê aspas duplas com os mesmos escapes do systemd (o restore-test.sh faz source)
got=$(set -a && source "$env_file" && printf '%s' "$SMTP_PASSWORD")
assert "bash lê a senha igual" test "$got" = "$password"

if [[ $EUID -eq 0 ]] && command -v systemd-run >/dev/null && [[ -d /run/systemd/system ]]; then
  declare -A want=([SMTP_HOST]=smtp-relay.brevo.com [SMTP_PORT]=587 [SMTP_USER]=$user [SMTP_PASSWORD]=$password)
  for key in "${keys[@]}"; do
    got=$(systemd-run --quiet --wait --pipe --collect -p EnvironmentFile="$env_file" /usr/bin/printenv "$key")
    assert "systemd lê $key igual" test "$got" = "${want[$key]}"
  done
else
  echo "pulado: leitura pelo systemd (precisa de root e systemd)"
fi

echo "--- valor vazio e mesmos valores não mudam o arquivo"
before=$(sha256sum "$env_file")
printf 'SMTP_HOST=\nSMTP_PORT=\nSMTP_USER=\nSMTP_PASSWORD=\n' > "$tmp/empty"
load_input "$tmp/empty"
assert "vazio não muda o arquivo" not write_smtp
assert "vazio mantém o conteúdo" test "$(sha256sum "$env_file")" = "$before"
load_input "$tmp/in"
assert "mesmos valores não mudam o arquivo" not write_smtp

echo "--- só uma chave nova: as outras continuam"
printf 'SMTP_PORT=2525\n' > "$tmp/port"
load_input "$tmp/port"
assert "porta nova muda o arquivo" write_smtp
assert "porta trocada" grep -qx 'SMTP_PORT=2525' "$env_file"
assert "as outras chaves continuam" test "$(grep -c '^SMTP_' "$env_file")" = 4

echo "--- recusados"
expect_refused() {
  local desc=$1 input=$2 msg=$3
  printf '%s' "$input" > "$tmp/bad"
  if (read_stdin_config < "$tmp/bad") > "$tmp/out" 2>&1; then
    fail "$desc foi aceito"
    return
  fi
  cat "$tmp/out" >> "$all_output"
  assert "$desc recusado" grep -q "$msg" "$tmp/out"
}
expect_refused "quebra de linha no valor" $'SMTP_PASSWORD=parte1\nsegredo-da-parte2\n' 'linha inválida no stdin'
expect_refused "\\r no valor (CRLF)" $'SMTP_PASSWORD=segredo-com-cr\r\n' 'valor inválido em SMTP_PASSWORD'
expect_refused "tab no valor" $'SMTP_USER=a\tb\n' 'valor inválido em SMTP_USER'
expect_refused "chave desconhecida" $'SMTP_SENHA=x\n' 'chave desconhecida no stdin: SMTP_SENHA'
expect_refused "chave minúscula" $'smtp_host=x\n' 'linha inválida no stdin'
expect_refused "porta com letras" $'SMTP_PORT=58a\n' 'valor inválido em SMTP_PORT'
expect_refused "porta zero" $'SMTP_PORT=0\n' 'valor inválido em SMTP_PORT'
expect_refused "porta acima de 65535" $'SMTP_PORT=70000\n' 'valor inválido em SMTP_PORT'
expect_refused "host com espaço" $'SMTP_HOST=smtp brevo.com\n' 'valor inválido em SMTP_HOST'
expect_refused "valor com mais de 1024 caracteres" "SMTP_PASSWORD=$(printf 'x%.0s' {1..1025})"$'\n' \
  'valor inválido em SMTP_PASSWORD'
expect_refused "litestream com @" $'LITESTREAM_SECRET_ACCESS_KEY=a@b\n' \
  'valor inválido em LITESTREAM_SECRET_ACCESS_KEY'

echo "--- nenhum valor aparece nas mensagens"
for secret in "$password" segredo-da-parte2 segredo-com-cr "$user"; do
  assert "valor ausente da saída" not grep -qF -- "$secret" "$all_output"
done

if ((failures)); then
  echo "$failures falha(s)"
  exit 1
fi
echo "ok"
