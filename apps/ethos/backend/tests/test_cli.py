import json
import logging
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import audit, cli
from app.audit import AuditEvent
from app.cli import CommandError, main
from app.config import ENV_VARS, Settings
from app.db import write_transaction
from app.models import AuditLog, User
from tests.auth_helpers import open_session
from tests.conftest import BACKEND_DIR
from tests.factories import count, new_habit, new_user, save

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


@pytest.mark.parametrize(
    "argv",
    [[], ["nao-existe"], ["cleanup", "--sobra"], ["create-admin"], ["create-admin", "a", "b"]],
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
    assert "cleanup" in out
    assert "create-admin" in out


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


def snapshot(session: Session) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """Todas as linhas de `users` e de `audit_log`, para conferir que nada mudou."""
    session.rollback()
    users = session.execute(select(User.__table__).order_by(User.id)).all()
    events = session.execute(select(AuditLog.__table__).order_by(AuditLog.id)).all()
    return [tuple(row) for row in users], [tuple(row) for row in events]


def test_create_admin_promotes_and_records_the_event(db_session, env, ana, capsys):
    save(db_session, new_user("bia@example.com"))

    with time_machine.travel(NOW, tick=False):
        assert main(["create-admin", "ana@example.com"], env) == 0

    # A saída identifica a conta pelo id, sem o email
    assert capsys.readouterr() == (f"create-admin: a conta {ana.id} agora é admin\n", "")
    db_session.rollback()
    assert db_session.scalars(select(User.id).where(User.is_admin)).all() == [ana.id]
    entry = db_session.scalars(select(AuditLog)).one()
    assert (entry.event, entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        AuditEvent.ADMIN_CREATED,
        ana.id,
        None,
        None,
        {"via": "cli"},
    )
    assert entry.created_at == NOW


def test_create_admin_unknown_email_changes_nothing(db_session, env, ana, capsys):
    before = snapshot(db_session)

    assert main(["create-admin", "nao-existe@example.com"], env) == 1

    assert capsys.readouterr() == (
        "",
        "erro: nenhuma conta com esse email. A pessoa precisa entrar no app uma vez antes\n",
    )
    assert snapshot(db_session) == before
    assert count(db_session, AuditLog) == 0


@pytest.mark.parametrize("typed", ["", "ana", "ana@example", "ana @example.com"])
def test_create_admin_refuses_an_invalid_email(db_session, env, ana, typed, capsys):
    before = snapshot(db_session)

    assert main(["create-admin", typed], env) == 1

    assert capsys.readouterr() == ("", "erro: email inválido\n")
    assert snapshot(db_session) == before


def test_create_admin_twice_changes_nothing_the_second_time(db_session, env, ana, capsys):
    with time_machine.travel(NOW, tick=False):
        assert main(["create-admin", "ana@example.com"], env) == 0
    capsys.readouterr()
    before = snapshot(db_session)

    with time_machine.travel(NOW + DAY, tick=False):
        assert main(["create-admin", "ana@example.com"], env) == 0

    assert capsys.readouterr() == (f"create-admin: a conta {ana.id} já é admin; nada mudou\n", "")
    # Nem evento duplicado nem updated_at novo
    assert snapshot(db_session) == before
    assert count(db_session, AuditLog) == 1


@pytest.mark.parametrize("typed", ["ANA@Example.COM", "  ana@example.com\t\n", " Ana@EXAMPLE.com "])
def test_create_admin_normalizes_the_email(db_session, env, ana, typed, capsys):
    assert main(["create-admin", typed], env) == 0

    assert capsys.readouterr().out == f"create-admin: a conta {ana.id} agora é admin\n"
    db_session.rollback()
    assert db_session.scalar(select(User.is_admin).where(User.id == ana.id))
    assert count(db_session, AuditLog, AuditLog.user_id == ana.id) == 1


@pytest.mark.parametrize("is_admin", [False, True])
def test_create_admin_refuses_a_blocked_account(db_session, env, is_admin, capsys):
    blocked = new_user(is_active=False, is_admin=is_admin)
    save(db_session, blocked)
    before = snapshot(db_session)

    assert main(["create-admin", "ana@example.com"], env) == 1

    assert capsys.readouterr() == (
        "",
        f"erro: a conta {blocked.id} está bloqueada (is_active=false); nada mudou\n",
    )
    assert snapshot(db_session) == before


def exported(out: str) -> list[dict[str, Any]]:
    """As contas da saída do export-users, depois de conferir a linha final com o total."""
    *accounts, end = [json.loads(line) for line in out.splitlines()]
    assert end == {"end": True, "count": len(accounts)}
    return accounts


def database_files(settings: Settings) -> dict[str, bytes | None]:
    """Os arquivos da pasta do banco, com o conteúdo do principal e do WAL.

    O `-shm` é o índice em memória compartilhada do WAL, que o SQLite atualiza também em leituras
    (marcas de leitura): conta só a existência dele, não o conteúdo.
    """
    folder = settings.database_path.parent
    return {
        path.name: None if path.name.endswith("-shm") else path.read_bytes()
        for path in sorted(folder.iterdir())
        if path.is_file()
    }


def test_export_users_writes_one_json_line_per_account(db_session, env, settings, caplog, capsys):
    active = new_user(
        "ana@example.com",
        created_at=datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC),
        last_login_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    blocked = new_user(
        "bia@example.com",
        is_active=False,
        timezone="Europe/Lisbon",
        locale="en",
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    admin = new_user(
        "caio@example.com",
        is_admin=True,
        created_at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
        last_login_at=datetime(2026, 6, 1, 2, 59, 59, 1, tzinfo=UTC),
    )
    save(db_session, active, blocked, admin)
    save(db_session, new_habit(active))
    open_session(db_session, active)
    db_session.rollback()
    before = database_files(settings)

    with caplog.at_level(logging.DEBUG):
        assert main(["export-users"], env) == 0

    out, err = capsys.readouterr()
    assert err == ""
    # Nada no log: nem a contagem nem os emails
    assert caplog.records == []
    assert out.isascii()
    assert exported(out) == [
        {
            "id": active.id,
            "email": "ana@example.com",
            "is_active": True,
            "is_admin": False,
            "timezone": "America/Sao_Paulo",
            "locale": "pt",
            "created_at": "2026-01-02T03:04:05.678901Z",
            "last_login_at": "2026-05-30T12:00:00.000000Z",
        },
        {
            "id": blocked.id,
            "email": "bia@example.com",
            "is_active": False,
            "is_admin": False,
            "timezone": "Europe/Lisbon",
            "locale": "en",
            "created_at": "2026-02-01T00:00:00.000000Z",
            "last_login_at": None,
        },
        {
            "id": admin.id,
            "email": "caio@example.com",
            "is_active": True,
            "is_admin": True,
            "timezone": "America/Sao_Paulo",
            "locale": "pt",
            "created_at": "2026-03-01T09:30:00.000000Z",
            "last_login_at": "2026-06-01T02:59:59.000001Z",
        },
    ]
    # A linha final, com o total, fecha a saída (o import do imago exige exatamente esta)
    assert out.endswith('\n{"end":true,"count":3}\n')
    # As datas voltam para o mesmo instante
    assert datetime.fromisoformat(exported(out)[0]["created_at"]) == active.created_at
    # Só leu: os arquivos do banco estão iguais e nenhum arquivo novo apareceu
    assert database_files(settings) == before


def test_export_users_keeps_the_id_order_with_gaps(db_session, env, capsys):
    users = [new_user(f"u{n}@example.com") for n in range(3)]
    save(db_session, *users)
    with write_transaction(db_session):
        db_session.delete(db_session.get(User, users[1].id))

    assert main(["export-users"], env) == 0

    exported_ids = [line["id"] for line in exported(capsys.readouterr().out)]
    assert exported_ids == [users[0].id, users[2].id]


def test_export_users_with_no_accounts_writes_only_the_end_line(env, capsys):
    assert main(["export-users"], env) == 0
    assert capsys.readouterr() == ('{"end":true,"count":0}\n', "")


def test_export_users_failing_midway_writes_no_end_line(db_session, env, monkeypatch, capsys):
    save(db_session, *(new_user(f"u{n}@example.com") for n in range(3)))
    db_session.rollback()
    real_execute = Session.execute

    def failing_execute(self, statement, *args, **kwargs):
        # O banco falha depois da primeira conta, no meio da consulta
        result = real_execute(self, statement, *args, **kwargs)

        def rows():
            yield next(iter(result))
            raise OperationalError("SELECT", {}, Exception("disk I/O error"))

        return rows()

    monkeypatch.setattr(Session, "execute", failing_execute)

    assert main(["export-users"], env) == 1

    out, err = capsys.readouterr()
    # Só a primeira conta saiu, e sem a linha final: o import do imago recusa a entrada
    assert [json.loads(line)["email"] for line in out.splitlines()] == ["u0@example.com"]
    assert '"end"' not in out
    assert err.startswith("erro: falha no banco de dados (OperationalError em app/cli.py:")


def test_export_users_refuses_a_terminal(env, ana, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    assert main(["export-users"], env) == 1

    assert capsys.readouterr() == (
        "",
        "erro: a saída tem os emails de todas as contas: mande-a por um pipe para o "
        "import-users - do imago\n",
    )


def test_export_users_runs_as_a_module_into_a_pipe(env, ana):
    environ = {key: value for key, value in os.environ.items() if key not in ENV_VARS}
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "export-users"],
        cwd=BACKEND_DIR,
        env=environ | env | {"PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert (result.returncode, result.stderr) == (0, "")
    assert [line["email"] for line in exported(result.stdout)] == ["ana@example.com"]
