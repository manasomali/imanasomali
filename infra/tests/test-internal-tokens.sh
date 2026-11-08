#!/usr/bin/env bash
# Testa os tokens da API interna (install_internal_tokens, lib/apps.sh) e a leitura das units que
# decide quem reinicia quando o smtp.env ou um token muda (app_reads_env_file). Os tokens nascem uma
# vez, uma aplicação nova entra no imago.env sem mudar os existentes, a segunda execução não muda
# nada e nenhum token aparece em log ou mensagem. O restart em si (systemd) fica no
# .github/scripts/test-provision-apps.sh. Roda na raiz do repo, como root (os arquivos são do root),
# pelo infra.yaml: sudo bash infra/tests/test-internal-tokens.sh
set -euo pipefail

INFRA_DIR=$PWD/infra
# shellcheck source=infra/lib/common.sh
source "$INFRA_DIR/lib/common.sh"
# shellcheck source=infra/lib/apps.sh
source "$INFRA_DIR/lib/apps.sh"

require_root

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# Os arquivos do teste numa pasta temporária, nunca no /etc/infra/internal da máquina
INTERNAL_DIR=$tmp/internal
out=$tmp/out
all_output=$tmp/all-output
touch "$all_output"

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

# install_internal_tokens com as aplicações dadas (uma por argumento), saída em $out
run_tokens() {
  install_internal_tokens "$(printf '%s\n' "$@")" > "$out" 2>&1
  cat "$out" >> "$all_output"
}
# O mesmo, numa subshell: para os casos em que o provision tem de parar (die)
run_tokens_fails() {
  if (install_internal_tokens "$(printf '%s\n' "$@")") > "$out" 2>&1; then
    cat "$out" >> "$all_output"
    return 1
  fi
  cat "$out" >> "$all_output"
}
changed() { printf '%s\n' "${TOKENS_CHANGED[@]}" | LC_ALL=C sort | paste -sd' ' -; }
token_of() { sed -n 's/^INTERNAL_API_TOKEN=//p' "$INTERNAL_DIR/$1.env"; }
imago_env() { cat "$INTERNAL_DIR/imago.env"; }
owner_mode() { stat -c '%U:%G %a' "$1"; }
snapshot() { (cd "$INTERNAL_DIR" && sha256sum -- * | sort); }
quiet() { not grep -qE 'criado|atualizado' "$out"; }
no_temp_files() { [[ -z $(find "$INTERNAL_DIR" -name '.token.*') ]]; }

echo "--- primeira execução: token do ethos e o imago.env"
run_tokens ethos imago
ethos_token=$(token_of ethos)
assert "pasta root 700" test "$(owner_mode "$INTERNAL_DIR")" = "root:root 700"
assert "ethos.env root 600" test "$(owner_mode "$INTERNAL_DIR/ethos.env")" = "root:root 600"
assert "ethos.env com uma linha só" test "$(wc -l < "$INTERNAL_DIR/ethos.env")" = 1
assert "token de 32 bytes em base64url (43 caracteres, sem =)" \
  grep -qxE 'INTERNAL_API_TOKEN=[A-Za-z0-9_-]{43}' "$INTERNAL_DIR/ethos.env"
assert "imago.env root 600" test "$(owner_mode "$INTERNAL_DIR/imago.env")" = "root:root 600"
assert "imago.env com o token do ethos" test "$(imago_env)" = "IMAGO_APP_TOKENS=ethos:$ethos_token"
assert "o imago não ganha token para ele mesmo" not grep -q 'imago:' "$INTERNAL_DIR/imago.env"
assert "mudaram: ethos e imago" test "$(changed)" = "ethos imago"
assert "log diz que criou" grep -q "criado: $INTERNAL_DIR/ethos.env" "$out"
assert "sem arquivo temporário sobrando" no_temp_files

echo "--- segunda execução: nada muda"
before=$(snapshot)
run_tokens ethos imago
assert "mesmos arquivos" test "$(snapshot)" = "$before"
assert "nada mudou" test -z "$(changed)"
assert "nada no log" quiet

echo "--- aplicação nova: ganha o token dela, o do ethos fica"
run_tokens engrafi ethos imago
engrafi_token=$(token_of engrafi)
assert "token do ethos igual" test "$(token_of ethos)" = "$ethos_token"
assert "engrafi.env root 600" test "$(owner_mode "$INTERNAL_DIR/engrafi.env")" = "root:root 600"
assert "tokens diferentes" test "$engrafi_token" != "$ethos_token"
assert "imago.env em ordem alfabética" \
  test "$(imago_env)" = "IMAGO_APP_TOKENS=engrafi:$engrafi_token,ethos:$ethos_token"
assert "mudaram: engrafi e imago" test "$(changed)" = "engrafi imago"

echo "--- a ordem de entrada não importa"
before=$(snapshot)
run_tokens imago ethos engrafi
assert "mesmos arquivos" test "$(snapshot)" = "$before"
assert "nada mudou" test -z "$(changed)"

echo "--- ordem do C, em qualquer locale: a-b antes de ab"
run_tokens ab a-b imago
assert "a-b antes de ab" grep -qE '^IMAGO_APP_TOKENS=a-b:[^,]+,ab:[^,]+$' "$INTERNAL_DIR/imago.env"
rm "$INTERNAL_DIR/ab.env" "$INTERNAL_DIR/a-b.env"
run_tokens engrafi ethos imago
assert "volta ao imago.env anterior" test "$(snapshot)" = "$before"

echo "--- aplicação que sai de infra/apps/: sai do imago.env, o arquivo dela fica"
run_tokens ethos imago
assert "imago.env só com o ethos" test "$(imago_env)" = "IMAGO_APP_TOKENS=ethos:$ethos_token"
assert "engrafi.env continua" test "$(token_of engrafi)" = "$engrafi_token"
assert "mudou: imago" test "$(changed)" = "imago"
run_tokens engrafi ethos imago
assert "a volta reusa o mesmo token" test "$(token_of engrafi)" = "$engrafi_token"
assert "e só o imago.env muda" test "$(changed)" = "imago"

echo "--- dono e modo errados são corrigidos, sem mudar o token"
chmod 0644 "$INTERNAL_DIR/ethos.env"
run_tokens engrafi ethos imago
assert "volta a 600" test "$(owner_mode "$INTERNAL_DIR/ethos.env")" = "root:root 600"
assert "mesmo token" test "$(token_of ethos)" = "$ethos_token"
assert "log diz que corrigiu" grep -q "atualizado: $INTERNAL_DIR/ethos.env (root 600)" "$out"
assert "nenhuma aplicação reinicia" test -z "$(changed)"
chmod 0755 "$INTERNAL_DIR"
run_tokens engrafi ethos imago
assert "pasta volta a 700" test "$(owner_mode "$INTERNAL_DIR")" = "root:root 700"

echo "--- apagar o arquivo troca o token"
rm "$INTERNAL_DIR/engrafi.env"
run_tokens engrafi ethos imago
assert "token novo" test "$(token_of engrafi)" != "$engrafi_token"
assert "mudaram: engrafi e imago" test "$(changed)" = "engrafi imago"
engrafi_token=$(token_of engrafi)

echo "--- recusados: o provision para sem mostrar o conteúdo"
cp -p "$INTERNAL_DIR/ethos.env" "$tmp/ethos.env"
printf 'INTERNAL_API_TOKEN=segredo-curto\n' > "$INTERNAL_DIR/ethos.env"
assert "token curto recusado" run_tokens_fails engrafi ethos imago
assert "mensagem do formato" grep -q 'fora do formato' "$out"
printf 'INTERNAL_API_TOKEN=%s\nOUTRA=segredo-extra\n' "$ethos_token" > "$INTERNAL_DIR/ethos.env"
assert "segunda linha recusada" run_tokens_fails engrafi ethos imago
printf 'INTERNAL_API_TOKEN=%s\r\n' "$ethos_token" > "$INTERNAL_DIR/ethos.env"
assert "CRLF recusado" run_tokens_fails engrafi ethos imago
rm "$INTERNAL_DIR/ethos.env"
ln -s "$tmp/ethos.env" "$INTERNAL_DIR/ethos.env"
assert "link simbólico recusado" run_tokens_fails engrafi ethos imago
assert "mensagem do link" grep -q 'não é um arquivo comum' "$out"
rm "$INTERNAL_DIR/ethos.env"
cp -p "$tmp/ethos.env" "$INTERNAL_DIR/ethos.env"
run_tokens engrafi ethos imago
assert "de volta ao normal" test "$(token_of ethos)" = "$ethos_token"

echo "--- app.env com token é recusado (segredo não se versiona)"
fake_infra=$tmp/infra
for key in INTERNAL_API_TOKEN IMAGO_APP_TOKENS; do
  install -d "$fake_infra/apps/teste"
  printf 'APP_ENV=prod\n%s=segredo-versionado\n' "$key" > "$fake_infra/apps/teste/app.env"
  if (INFRA_DIR=$fake_infra install_app_env teste) > "$out" 2>&1; then
    fail "$key no app.env foi aceito"
  else
    assert "$key no app.env recusado" grep -q "não pode ter $key" "$out"
  fi
  cat "$out" >> "$all_output"
done

echo "--- quem lê um arquivo de ambiente (decide quem reinicia)"
unit=$fake_infra/apps/teste/app-teste.service
reads() {
  printf '[Service]\n%s\n' "$1" > "$unit"
  INFRA_DIR=$fake_infra app_reads_env_file teste /etc/infra/smtp.env
}
assert "EnvironmentFile=" reads 'EnvironmentFile=/etc/infra/smtp.env'
assert "EnvironmentFile=- (opcional)" reads 'EnvironmentFile=-/etc/infra/smtp.env'
assert "com espaços em volta" reads '  EnvironmentFile = /etc/infra/smtp.env  '
assert "comentário não conta" not reads '# EnvironmentFile=/etc/infra/smtp.env'
assert "outro arquivo não conta" not reads 'EnvironmentFile=/etc/infra/smtp.env.antigo'
assert "outra diretiva não conta" not reads 'Environment=/etc/infra/smtp.env'
rm "$unit"
reads_without_unit() { INFRA_DIR=$fake_infra app_reads_env_file teste /etc/infra/smtp.env; }
assert "sem app-<nome>.service, não lê" not reads_without_unit

echo "--- nenhum token aparece nas mensagens"
for secret in "$ethos_token" "$engrafi_token" segredo-curto segredo-extra segredo-versionado; do
  assert "valor ausente da saída" not grep -qF -- "$secret" "$all_output"
done
assert "sem arquivo temporário sobrando" no_temp_files

if ((failures)); then
  echo "$failures falha(s)"
  exit 1
fi
echo "ok"
