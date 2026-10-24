import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, cli
from app.audit import AuditEvent
from app.cli import CommandError, main
from app.config import ENV_VARS, Settings
from app.db import write_transaction
from app.models import AuditLog, User
from tests.conftest import BACKEND_DIR
from tests.factories import new_habit, new_user, save

NOW = datetime(2026, 6, 1, 3, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def env_for(settings: Settings) -> dict[str, str]:
    """Variáveis de ambiente equivalentes à `settings` dos testes."""
    return {
        "APP_ENV": settings.app_env.value,
        "APP_URL": settings.app_url,
        "DATABASE_PATH": str(settings.database_path),
        "EMAIL_BACKEND": settings.email_backend.value,
        "MAIL_FROM": settings.mail_from,
        "SUPPORT_EMAIL": settings.support_email,
        "MAX_CODE_EMAILS_PER_HOUR": str(settings.max_code_emails_per_hour),
        "MAX_CODE_EMAILS_PER_DAY": str(settings.max_code_emails_per_day),
    }


def add_event(session: Session, event: AuditEvent, age: timedelta, **kwargs: Any) -> int:
    with time_machine.travel(NOW - age, tick=False), write_transaction(session):
        entry = audit.record(session, event, ip="203.0.113.7", **kwargs)
        session.flush()
    return entry.id


@pytest.fixture
def env(settings, database) -> dict[str, str]:
    return env_for(settings)


@pytest.fixture
def ana(db_session) -> User:
    user = new_user()
    save(db_session, user)
    return user


def test_cleanup_applies_retention_with_frozen_time(db_session, env, ana, capsys):
    habit = new_habit(ana)
    save(db_session, habit)
    recent_login = add_event(db_session, AuditEvent.LOGIN, 89 * DAY, user_id=ana.id)
    add_event(db_session, AuditEvent.LOGIN, 91 * DAY, user_id=ana.id)
    old_mark = add_event(
        db_session, AuditEvent.MARK_CREATED, 365 * DAY, user_id=ana.id, habit_id=habit.id
    )

    with time_machine.travel(NOW, tick=False):
        assert main(["cleanup"], env) == 0

    assert capsys.readouterr().out == (
        "cleanup: 1 eventos de auth apagados, 1 IPs apagados na auditoria, "
        "0 sessões vencidas apagadas, 0 IPs apagados nas sessões, 0 códigos vencidos apagados\n"
    )
    db_session.rollback()
    remaining = {entry.id: entry.ip for entry in db_session.scalars(select(AuditLog))}
    assert remaining == {recent_login: "203.0.113.7", old_mark: None}

    # Segunda execução: nada a fazer
    with time_machine.travel(NOW, tick=False):
        assert main(["cleanup"], env) == 0
    assert capsys.readouterr().out.startswith("cleanup: 0 eventos de auth apagados, 0 IPs")


def test_cleanup_runs_as_a_module(settings, env):
    # Ambiente do processo sem as variáveis do app que porventura existam aqui
    environ = {key: value for key, value in os.environ.items() if key not in ENV_VARS}
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "cleanup"],
        cwd=BACKEND_DIR,
        env=environ | env | {"PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.startswith("cleanup: 0 eventos de auth apagados")


@pytest.mark.parametrize("argv", [[], ["nao-existe"], ["cleanup", "--sobra"]])
def test_wrong_usage_exits_with_2(env, argv, capsys):
    with pytest.raises(SystemExit) as raised:
        main(argv, env)
    assert raised.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_help_lists_cleanup(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["--help"], {})
    assert raised.value.code == 0
    assert "cleanup" in capsys.readouterr().out


def test_invalid_config_exits_with_1_without_values(env, capsys):
    env = env | {"APP_URL": "", "MAIL_FROM": "valor-secreto-invalido"}
    assert main(["cleanup"], env) == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: configuração inválida")
    assert "APP_URL: obrigatória" in err
    assert "valor-secreto-invalido" not in err


def test_missing_database_is_not_created(env, tmp_path, capsys):
    path = tmp_path / "outro.db"
    assert main(["cleanup"], env | {"DATABASE_PATH": str(path)}) == 1
    assert capsys.readouterr().err == (
        "erro: DATABASE_PATH não aponta para um banco existente (alembic upgrade head)\n"
    )
    assert not path.exists()


def test_database_error_shows_only_the_type(env, tmp_path, capsys):
    # Arquivo vazio: banco SQLite válido, mas sem as tabelas
    path = tmp_path / "vazio.db"
    path.touch()
    assert main(["cleanup"], env | {"DATABASE_PATH": str(path)}) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(r"erro: falha no banco de dados \(OperationalError em app/\S+:\d+\)\n", err)


def test_command_error_message_goes_to_stderr(env, monkeypatch, capsys):
    def refuse(*_args):
        raise CommandError("conta não encontrada")

    monkeypatch.setattr(cli, "run_cleanup", refuse)
    assert main(["cleanup"], env) == 1
    assert capsys.readouterr() == ("", "erro: conta não encontrada\n")


def test_unexpected_error_hides_the_message(env, monkeypatch, capsys):
    def explode(*_args):
        raise RuntimeError("ana@example.com 123456")

    monkeypatch.setattr(cli, "run_cleanup", explode)
    assert main(["cleanup"], env) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(r"erro: erro inesperado \(RuntimeError em app/cli\.py:\d+\)\n", err)
