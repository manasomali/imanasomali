"""O CLI (`app/cli.py`): uso, config, erros e a saída. Os comandos têm os testes deles:
`run-alerts` em `test_alerts.py`, `reapply-deletions` em `test_reapply_deletions.py` e `seed` em
`test_seed.py`."""

import os
import re
import subprocess
import sys

import pytest

from app import cli
from app.cli import CommandError, main
from app.config import ENV_VARS, Settings
from tests.conftest import BACKEND_DIR

RUN_ALERTS_EMPTY = (
    "run-alerts: 0 alertas avaliados, 0 emails enviados, 0 recusados pelo teto de envio, 0 falhas\n"
)


def env_for(settings: Settings) -> dict[str, str]:
    """Variáveis de ambiente equivalentes à `settings` dos testes."""
    return {
        "APP_ENV": settings.app_env.value,
        "APP_URL": settings.app_url,
        "DATABASE_PATH": str(settings.database_path),
        "IMAGO_INTERNAL_URL": settings.imago_internal_url,
        "INTERNAL_API_TOKEN": settings.internal_api_token.get_secret_value(),
    }


@pytest.fixture
def env(settings, database) -> dict[str, str]:
    return env_for(settings)


def test_runs_as_a_module(settings, env):
    # Ambiente do processo sem as variáveis do app que porventura existam aqui. Sem alertas, o
    # run-alerts não chama o imago
    environ = {key: value for key, value in os.environ.items() if key not in ENV_VARS}
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "run-alerts"],
        cwd=BACKEND_DIR,
        env=environ | env | {"PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert (result.returncode, result.stderr, result.stdout) == (0, "", RUN_ALERTS_EMPTY)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["nao-existe"],
        ["run-alerts", "--sobra"],
        ["seed", "a"],
        # Comandos do login próprio, de antes do imago: não existem mais
        ["cleanup"],
        ["create-admin", "ana@example.com"],
        ["export-users"],
    ],
)
def test_wrong_usage_exits_with_2(env, argv, capsys):
    with pytest.raises(SystemExit) as raised:
        main(argv, env)
    assert raised.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_help_lists_the_commands(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["--help"], {})
    assert raised.value.code == 0
    out = capsys.readouterr().out
    for command in ("run-alerts", "reapply-deletions", "seed"):
        assert command in out
    assert "create-admin" not in out


def test_invalid_config_exits_with_1_without_values(env, capsys):
    env = env | {"APP_URL": "", "INTERNAL_API_TOKEN": "valor-secreto-invalido"}
    assert main(["run-alerts"], env) == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: configuração inválida")
    assert "APP_URL: obrigatória" in err
    assert "valor-secreto-invalido" not in err


def test_missing_database_is_not_created(env, tmp_path, capsys):
    path = tmp_path / "outro.db"
    assert main(["run-alerts"], env | {"DATABASE_PATH": str(path)}) == 1
    assert capsys.readouterr().err == (
        "erro: DATABASE_PATH não aponta para um banco existente (alembic upgrade head)\n"
    )
    assert not path.exists()


def test_database_error_shows_only_the_type(env, tmp_path, capsys):
    # Arquivo vazio: banco SQLite válido, mas sem as tabelas
    path = tmp_path / "vazio.db"
    path.touch()
    assert main(["run-alerts"], env | {"DATABASE_PATH": str(path)}) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(r"erro: falha no banco de dados \(OperationalError em app/\S+:\d+\)\n", err)


def test_command_error_message_goes_to_stderr(env, monkeypatch, capsys):
    def refuse(*_args, **_kwargs):
        raise CommandError("entrada ilegível")

    monkeypatch.setattr(cli, "run_alerts", refuse)
    assert main(["run-alerts"], env) == 1
    assert capsys.readouterr() == ("", "erro: entrada ilegível\n")


def test_unexpected_error_hides_the_message(env, monkeypatch, capsys):
    def explode(*_args, **_kwargs):
        raise RuntimeError("ana@example.com 123456")

    monkeypatch.setattr(cli, "run_alerts", explode)
    assert main(["run-alerts"], env) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(r"erro: erro inesperado \(RuntimeError em app/cli\.py:\d+\)\n", err)
