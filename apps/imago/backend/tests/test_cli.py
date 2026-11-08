"""CLI (`python -m app.cli`): cleanup, seed, erros e uso."""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from sqlalchemy import select

from app import audit, cli
from app.audit import AuditEvent
from app.cli import CommandError, main
from app.config import ENV_VARS, Settings
from app.db import write_transaction
from app.models import AuditLog, MailLog, User
from app.seed import SEED_ACCOUNTS
from tests.conftest import BACKEND_DIR
from tests.factories import count, new_user, save
from tests.internal_helpers import ENGRAFI_TOKEN, ETHOS_TOKEN

NOW = datetime(2026, 6, 1, 3, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def env_for(settings: Settings) -> dict[str, str]:
    """Variáveis de ambiente equivalentes à `settings` dos testes."""
    return {
        "APP_ENV": settings.app_env.value,
        "APP_URL": settings.app_url,
        "DATABASE_PATH": str(settings.database_path),
        "EMAIL_BACKEND": settings.email_backend.value,
        "MAIL_FROM_ADDRESS": settings.mail_from_address,
        "SUPPORT_EMAIL": settings.support_email,
        "IMAGO_APPS": ",".join(f"{app.name}={app.url}" for app in settings.imago_apps),
        "IMAGO_APP_TOKENS": f"ethos:{ETHOS_TOKEN},engrafi:{ENGRAFI_TOKEN}",
    }


@pytest.fixture
def env(settings, database) -> dict[str, str]:
    return env_for(settings)


def test_cleanup_applies_retention_with_frozen_time(db_session, env, capsys):
    ana = new_user()
    save(db_session, ana)
    for age in (89 * DAY, 91 * DAY):
        with time_machine.travel(NOW - age, tick=False), write_transaction(db_session):
            audit.record(db_session, AuditEvent.LOGIN, user_id=ana.id, ip="203.0.113.7")
    save(
        db_session,
        MailLog(app="ethos", kind="notification", created_at=NOW - 49 * timedelta(hours=1)),
    )

    with time_machine.travel(NOW, tick=False):
        assert main(["cleanup"], env) == 0

    assert capsys.readouterr().out == (
        "cleanup: 1 eventos de auth apagados, 0 IPs apagados na auditoria, "
        "0 sessões vencidas apagadas, 0 IPs apagados nas sessões, 0 códigos apagados, "
        "1 envios apagados do mail_log, 0 tarefas concluídas apagadas\n"
    )
    db_session.rollback()
    assert count(db_session, AuditLog) == 1
    assert count(db_session, MailLog) == 0

    # Segunda execução: nada a fazer
    with time_machine.travel(NOW, tick=False):
        assert main(["cleanup"], env) == 0
    assert capsys.readouterr().out.startswith("cleanup: 0 eventos de auth apagados, 0 IPs")


def test_cleanup_runs_as_a_module(env):
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


def test_seed_creates_the_contract_accounts(db_session, env, capsys):
    assert main(["seed"], env) == 0

    assert capsys.readouterr().out == "seed: 3 contas criadas (ids 101, 102 e 103)\n"
    db_session.rollback()
    users = {user.id: user for user in db_session.scalars(select(User))}
    assert sorted(users) == [101, 102, 103]
    assert [(u.email, u.timezone, u.locale, u.is_admin) for u in users.values()] == [
        ("ana@example.com", "America/Sao_Paulo", "pt", True),
        ("bia@example.com", "America/Sao_Paulo", "pt", False),
        ("caio@example.com", "Europe/Lisbon", "en", False),
    ]
    [admin_event] = db_session.scalars(select(AuditLog))
    assert (admin_event.event, admin_event.user_id) == ("admin_created", 101)

    # Segunda vez: nada muda
    assert main(["seed"], env) == 0
    assert "já existem; nada mudou" in capsys.readouterr().out
    db_session.rollback()
    assert count(db_session, User) == 3


def test_seed_does_nothing_if_one_email_already_exists(db_session, env, capsys):
    save(db_session, new_user(SEED_ACCOUNTS[2].email))

    assert main(["seed"], env) == 0

    assert "já existem" in capsys.readouterr().out
    db_session.rollback()
    assert count(db_session, User) == 1


def test_seed_refuses_outside_dev(db_session, env, capsys):
    env |= {
        "APP_ENV": "prod",
        "APP_URL": "https://manasomali.com/imago",
        "EMAIL_BACKEND": "smtp",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "u",
        "SMTP_PASSWORD": "p",
    }

    assert main(["seed"], env) == 1

    assert capsys.readouterr().err == "erro: seed só roda com APP_ENV=dev; nada foi gravado\n"
    db_session.rollback()
    assert count(db_session, User) == 0


@pytest.mark.parametrize("argv", [[], ["nao-existe"], ["cleanup", "--sobra"], ["seed", "x"]])
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
    for command in ("cleanup", "seed"):
        assert command in out


def test_invalid_config_exits_with_1_without_values(env, capsys):
    env["IMAGO_APP_TOKENS"] = f"ethos:{ETHOS_TOKEN}"

    assert main(["cleanup"], env) == 1

    err = capsys.readouterr().err
    assert err.startswith("erro: configuração inválida")
    assert "IMAGO_APP_TOKENS sem o token de engrafi" in err
    assert ETHOS_TOKEN not in err


def test_missing_database_exits_with_1(env, tmp_path, capsys):
    env["DATABASE_PATH"] = str(tmp_path / "nao-existe.db")

    assert main(["cleanup"], env) == 1

    assert "DATABASE_PATH não aponta para um banco existente" in capsys.readouterr().err
    assert not (tmp_path / "nao-existe.db").exists()


def test_command_error_exits_with_1(env, monkeypatch, capsys):
    def fail(_context, _args):
        raise CommandError("algo esperado deu errado")

    monkeypatch.setattr(cli, "_cleanup", fail)

    assert main(["cleanup"], env) == 1
    assert capsys.readouterr().err == "erro: algo esperado deu errado\n"


def test_database_error_hides_the_message(env, monkeypatch, capsys):
    def fail(context, _args):
        with context.session_factory() as session:
            session.execute(select(User).where(User.email == "segredo@example.com"))
            session.connection().exec_driver_sql("SELECT * FROM tabela_que_nao_existe")

    monkeypatch.setattr(cli, "_cleanup", fail)

    assert main(["cleanup"], env) == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: falha no banco de dados (OperationalError em app/cli.py:")
    assert "tabela_que_nao_existe" not in err


def test_unexpected_error_hides_the_message(env, monkeypatch, capsys):
    def fail(_context, _args):
        raise ValueError("segredo@example.com")

    monkeypatch.setattr(cli, "_cleanup", fail)

    assert main(["cleanup"], env) == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: erro inesperado (ValueError em app/cli.py:")
    assert "segredo" not in err
