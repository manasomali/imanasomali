"""O .env.example, o infra/apps/imago/app.env, o smtp.env e o internal/imago.env do provision têm
as mesmas variáveis, e o .env.example serve para desenvolver como está.

Lê os arquivos do repo: o workflow do imago roda também quando o app.env ou o provision.sh mudam.
"""

import re
from pathlib import Path

from app.config import ENV_VARS, AppEnv, EmailBackend, load_settings

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[2]
ENV_EXAMPLE = BACKEND / ".env.example"
APP_ENV = REPO / "infra" / "apps" / "imago" / "app.env"
PROVISION = REPO / "infra" / "provision.sh"

# Linha do provision.sh que grava o /etc/infra/smtp.env com as variáveis listadas no fim
SMTP_LINE = re.compile(r'write_env_file "\$INFRA_STATE_DIR/smtp\.env" \d+ ([A-Z_ ]+)')
LINE = re.compile(r"([A-Z][A-Z0-9_]*)=(.*)")
# O /etc/infra/internal/imago.env, montado pelo provision na VM (infra/lib/apps.sh), só tem esta
INTERNAL_TOKENS = "IMAGO_APP_TOKENS"


def read_env(path: Path) -> dict[str, str]:
    """Lê um arquivo no formato do EnvironmentFile= (o mesmo que o .env aceita)."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = LINE.fullmatch(line)
        assert match, f"{path.name}: linha inválida: {line}"
        name, value = match.groups()
        assert name not in values, f"{path.name}: {name} repetida"
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        values[name] = value
    return values


def smtp_names() -> set[str]:
    match = SMTP_LINE.search(PROVISION.read_text(encoding="utf-8"))
    assert match, "provision.sh: não achei a linha que grava o smtp.env"
    return set(match.group(1).split())


def test_smtp_env_has_the_credentials():
    assert smtp_names() == {"SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD"}


def test_env_example_matches_app_env_smtp_env_and_tokens():
    example = set(read_env(ENV_EXAMPLE))
    production = set(read_env(APP_ENV)) | smtp_names() | {INTERNAL_TOKENS}

    assert sorted(example - production) == [], "no .env.example e fora do app.env/smtp.env/tokens"
    assert sorted(production - example) == [], "no app.env/smtp.env/tokens e fora do .env.example"


def test_app_env_has_no_secrets():
    # O provision recusa SMTP_* e os tokens no app.env: credenciais pelos secrets, tokens na VM
    names = read_env(APP_ENV)
    assert not [name for name in names if name.startswith("SMTP_")]
    assert INTERNAL_TOKENS not in names


def test_production_config_is_valid():
    app_env = read_env(APP_ENV)
    environ = app_env | {
        "SMTP_HOST": "smtp.exemplo.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "usuario",
        "SMTP_PASSWORD": "senha",
    }
    # Um token por aplicação do IMAGO_APPS, como o provision monta (valores só do teste)
    apps = [entry.split("=", 1)[0] for entry in app_env["IMAGO_APPS"].split(",")]
    environ[INTERNAL_TOKENS] = ",".join(
        f"{name}:{name}-token-de-teste-{index:02d}-0000000000000000"
        for index, name in enumerate(apps)
    )

    settings = load_settings(environ)

    assert settings.app_env is AppEnv.PROD
    assert settings.email_backend is EmailBackend.SMTP
    assert settings.app_names == tuple(apps)


def test_env_example_has_every_setting():
    assert sorted(read_env(ENV_EXAMPLE)) == sorted(ENV_VARS)


def test_env_example_is_a_valid_dev_config():
    settings = load_settings(read_env(ENV_EXAMPLE))

    assert settings.app_env is AppEnv.DEV
    assert settings.email_backend is EmailBackend.CONSOLE
    assert settings.app_names == ("ethos",)
