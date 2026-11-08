"""O .env.example tem exatamente as variáveis da config, e serve para desenvolver como está.

A comparação com o infra/apps/imago/app.env (+ smtp.env + IMAGO_APP_TOKENS) entra com a infra do
imago (ETH-57).
"""

import re
from pathlib import Path

from app.config import ENV_VARS, AppEnv, EmailBackend, load_settings

BACKEND = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = BACKEND / ".env.example"
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
        values[name] = value
    return values


def test_env_example_has_every_setting():
    assert sorted(read_env(ENV_EXAMPLE)) == sorted(ENV_VARS)


def test_env_example_is_a_valid_dev_config():
    settings = load_settings(read_env(ENV_EXAMPLE))

    assert settings.app_env is AppEnv.DEV
    assert settings.email_backend is EmailBackend.CONSOLE
    assert settings.app_names == ("ethos",)
