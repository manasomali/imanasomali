"""O .env.example e o infra/apps/ethos/app.env têm as mesmas variáveis (mais o token interno).

Lê os arquivos do repo: o workflow do ethos roda também quando o app.env muda.

O `.env.example` tem exatamente as variáveis do `app.env` (config não secreta, versionada) mais as
do `/etc/infra/internal/ethos.env` (`INTERNAL_API_TOKEN`, gerado pelo provision na VM).
"""

from pathlib import Path

import pytest

from app.config import ENV_VARS, AppEnv, load_settings

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[2]
ENV_EXAMPLE = BACKEND / ".env.example"
APP_ENV = REPO / "infra" / "apps" / "ethos" / "app.env"

# Do /etc/infra/internal/ethos.env (0600 root), fora do git
INTERNAL_ENV_VARS = frozenset({"INTERNAL_API_TOKEN"})
TOKEN = "x" * 43


def read_env(path: Path) -> dict[str, str]:
    """Lê um arquivo no formato do EnvironmentFile= (o mesmo que o .env aceita)."""
    return parse_env(path.read_text(encoding="utf-8"), path.name)


def parse_env(content: str, name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        valid = bool(separator) and key.isidentifier() and key.isupper()
        assert valid, f"{name}: linha inválida: {line}"
        assert key not in values, f"{name}: {key} repetida"
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        values[key] = value
    return values


def test_env_example_matches_app_env():
    example = set(read_env(ENV_EXAMPLE))
    expected = set(read_env(APP_ENV)) | INTERNAL_ENV_VARS

    assert sorted(example - expected) == [], "no .env.example e fora do app.env"
    assert sorted(expected - example) == [], "no app.env e fora do .env.example"


def test_env_example_has_every_setting():
    assert set(read_env(ENV_EXAMPLE)) == set(ENV_VARS)


def test_app_env_has_no_secrets():
    # Token e credenciais SMTP nunca no git: vêm de arquivos 0600 gerados na VM
    names = set(read_env(APP_ENV))
    assert not names & INTERNAL_ENV_VARS
    assert not [name for name in names if name.startswith("SMTP_")]


def test_production_config_is_valid():
    settings = load_settings(read_env(APP_ENV) | {"INTERNAL_API_TOKEN": TOKEN})

    assert settings.app_env is AppEnv.PROD
    assert settings.imago_internal_url == "http://127.0.0.1:3003"


def test_env_example_works_for_local_development():
    settings = load_settings(read_env(ENV_EXAMPLE))

    assert settings.is_dev
    assert settings.imago_internal_url == "http://127.0.0.1:3003"


@pytest.mark.parametrize(
    ("line", "value"),
    [
        ('MAIL_FROM="ethos <x@exemplo.com>"', "ethos <x@exemplo.com>"),
        ('A="aspas \\" e barra \\\\"', 'aspas " e barra \\'),
        ("VAZIA=", ""),
    ],
)
def test_parse_env_handles_quotes(line, value):
    assert list(parse_env(f"# comentário\n\n{line}\n", "x.env").values()) == [value]


@pytest.mark.parametrize("line", ["minuscula=1", "SEM_IGUAL", "COM ESPACO=1", "=1"])
def test_parse_env_refuses_invalid_lines(line):
    with pytest.raises(AssertionError, match="linha inválida"):
        parse_env(line, "x.env")
