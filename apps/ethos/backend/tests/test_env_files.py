"""O .env.example, o infra/apps/ethos/app.env e o smtp.env do provision têm as mesmas variáveis.

Lê os arquivos do repo: o workflow do ethos roda também quando o app.env ou o provision.sh mudam.
"""

import re
from pathlib import Path

import pytest

from app.config import ENV_VARS, AppEnv, EmailBackend, load_settings

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[2]
ENV_EXAMPLE = BACKEND / ".env.example"
APP_ENV = REPO / "infra" / "apps" / "ethos" / "app.env"
PROVISION = REPO / "infra" / "provision.sh"

# Linha do provision.sh que grava o /etc/infra/smtp.env com as variáveis listadas no fim
SMTP_LINE = re.compile(r'write_env_file "\$INFRA_STATE_DIR/smtp\.env" \d+ ([A-Z_ ]+)')
LINE = re.compile(r"([A-Z][A-Z0-9_]*)=(.*)")


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


def test_env_example_matches_app_env_and_smtp_env():
    example = set(read_env(ENV_EXAMPLE))
    production = set(read_env(APP_ENV)) | smtp_names()

    assert sorted(example - production) == [], "no .env.example e fora do app.env/smtp.env"
    assert sorted(production - example) == [], "no app.env/smtp.env e fora do .env.example"


def test_env_example_has_every_setting():
    assert set(read_env(ENV_EXAMPLE)) == set(ENV_VARS)


def test_app_env_has_no_smtp_credentials():
    # O provision recusa SMTP_* no app.env: credenciais só pelos secrets
    assert not [name for name in read_env(APP_ENV) if name.startswith("SMTP_")]


def test_production_config_is_valid():
    environ = read_env(APP_ENV) | {
        "SMTP_HOST": "smtp.exemplo.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "usuario",
        "SMTP_PASSWORD": "senha",
    }

    settings = load_settings(environ)

    assert settings.app_env is AppEnv.PROD
    assert settings.email_backend is EmailBackend.SMTP


def test_env_example_works_for_local_development():
    settings = load_settings(read_env(ENV_EXAMPLE))

    assert settings.is_dev
    assert settings.email_backend is EmailBackend.CONSOLE


@pytest.mark.parametrize(
    ("line", "value"),
    [
        ('MAIL_FROM="ethos <x@exemplo.com>"', "ethos <x@exemplo.com>"),
        ('A="aspas \\" e barra \\\\"', 'aspas " e barra \\'),
        ("VAZIA=", ""),
    ],
)
def test_read_env_parses_quotes(tmp_path, line, value):
    path = tmp_path / "x.env"
    path.write_text(f"# comentário\n\n{line}\n", encoding="utf-8")

    assert list(read_env(path).values()) == [value]
