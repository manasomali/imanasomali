#!/usr/bin/env bash
# Confere o IMAGO_APPS de infra/apps/imago/app.env, a lista de aplicações que usam a conta (ver
# imago-plan.md, "API interna"): cada entrada é <nome>=http://127.0.0.1:<porta>, com a porta igual ao
# PORT do infra/apps/<nome>/app.conf; toda pasta de infra/apps/ (menos o imago) está lá; e cada
# aplicação tem os textos dela no front do imago (apps.<nome>.name, description, deletion,
# export_label e export_path, em pt e en). Roda na raiz do repo, pelo infra.yaml e pelo imago.yaml.
set -euo pipefail

imago=imago
imago_env=infra/apps/$imago/app.env
locales=apps/$imago/frontend/public/locales
name_re='^[a-z][a-z0-9-]{1,26}$'
status=0
error() {
  echo "::error file=$1::$2"
  status=1
}

[[ -f $imago_env ]] || {
  echo "::error::$imago_env não existe"
  exit 1
}

value=$(sed -n 's/^IMAGO_APPS=//p' "$imago_env" | tail -n1)
# O valor pode vir entre aspas duplas (formato do EnvironmentFile=)
if [[ $value == \"*\" ]]; then
  value=${value:1:${#value}-2}
fi

declare -A listed=()
names=()
if [[ -n $value ]]; then
  IFS=, read -r -a entries <<< "$value"
  for entry in "${entries[@]}"; do
    name=${entry%%=*}
    url=${entry#*=}
    if [[ $entry != *=* || ! $name =~ $name_re ]]; then
      error "$imago_env" "IMAGO_APPS: entrada '$entry' fora do formato <nome>=http://127.0.0.1:<porta>"
      continue
    fi
    if [[ -n ${listed[$name]:-} ]]; then
      error "$imago_env" "IMAGO_APPS: $name aparece mais de uma vez"
      continue
    fi
    listed[$name]=1
    names+=("$name")

    if [[ $name == "$imago" ]]; then
      error "$imago_env" "IMAGO_APPS: o $imago não entra na própria lista"
      continue
    fi
    if [[ ! $url =~ ^http://127\.0\.0\.1:([0-9]{1,5})$ ]]; then
      error "$imago_env" "IMAGO_APPS: $name com '$url'; use http://127.0.0.1:<porta>, sem caminho"
      continue
    fi
    port=${BASH_REMATCH[1]}
    conf=infra/apps/$name/app.conf
    if [[ ! -f $conf ]]; then
      error "$imago_env" "IMAGO_APPS: $name não tem $conf (a aplicação não está em infra/apps/)"
      continue
    fi
    want=$(sed -n 's/^PORT=//p' "$conf" | tail -n1)
    if [[ $port != "$want" ]]; then
      error "$imago_env" "IMAGO_APPS: $name na porta $port, mas o PORT de $conf é '$want'"
    else
      echo "$name: porta $port no IMAGO_APPS e no app.conf"
    fi
  done
fi

for dir in infra/apps/*/; do
  [[ -d $dir ]] || continue
  name=$(basename "$dir")
  [[ $name != "$imago" ]] || continue
  if [[ -z ${listed[$name]:-} ]]; then
    error "$imago_env" "$name está em infra/apps/, mas não no IMAGO_APPS: o imago não apagaria os dados dela na exclusão de conta"
  fi
done

# Textos de cada aplicação no front do imago, em pt e en
for language in pt en; do
  file=$locales/$language/translation.json
  if [[ ! -f $file ]]; then
    error "$file" "$file não existe: os textos das aplicações do IMAGO_APPS (apps.<nome>.*) ficam nele"
    continue
  fi
  ((${#names[@]})) || continue
  # -I: o Python não importa nada da pasta de onde roda
  if ! problems=$(python3 -I - "$file" "${names[@]}" <<'EOF'
import json, sys

sys.stdout.reconfigure(encoding="utf-8")
path, names = sys.argv[1], sys.argv[2:]
keys = ("name", "description", "deletion", "export_label", "export_path")
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except (OSError, ValueError) as exc:
    print(f"não é um JSON válido: {exc}")
    sys.exit(1)

problems = []
apps = data.get("apps") if isinstance(data, dict) else None
apps = apps if isinstance(apps, dict) else {}
for name in names:
    texts = apps.get(name)
    texts = texts if isinstance(texts, dict) else {}
    for key in keys:
        value = texts.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"falta o texto apps.{name}.{key}")
        elif key == "export_path" and (not value.startswith("/") or value.startswith("//")):
            problems.append(f"apps.{name}.export_path tem de ser um caminho do site, começando com uma /")
print("\n".join(problems))
sys.exit(1 if problems else 0)
EOF
  ); then
    while IFS= read -r line; do
      error "$file" "$line"
    done <<< "$problems"
  else
    echo "$file: textos de ${names[*]}"
  fi
done

exit "$status"
