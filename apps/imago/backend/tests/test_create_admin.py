"""`python -m app.cli create-admin <email>` (ETH-19)."""

import pytest
from sqlalchemy import select

from app.cli import main
from app.models import AuditLog, User
from tests.factories import count, new_user, save
from tests.test_cli import env_for

ANA = "ana@example.com"


@pytest.fixture
def env(settings, database) -> dict[str, str]:
    return env_for(settings)


def reload(db_session, user: User) -> User:
    db_session.rollback()
    return db_session.scalar(
        select(User).where(User.id == user.id).execution_options(populate_existing=True)
    )


def test_existing_account_becomes_admin(db_session, env, capsys):
    user = new_user(ANA)
    save(db_session, user)

    assert main(["create-admin", "  Ana@Example.COM "], env) == 0

    out = capsys.readouterr().out
    assert out == f"create-admin: a conta {user.id} agora é admin\n"
    # A saída mostra o id, nunca o email
    assert ANA not in out
    assert reload(db_session, user).is_admin is True
    [entry] = db_session.scalars(select(AuditLog))
    assert (entry.event, entry.user_id, entry.ip, entry.details) == (
        "admin_created",
        user.id,
        None,
        {"via": "cli"},
    )


def test_second_run_changes_nothing(db_session, env, capsys):
    user = new_user(ANA)
    save(db_session, user)
    assert main(["create-admin", ANA], env) == 0
    capsys.readouterr()
    updated_at = reload(db_session, user).updated_at

    assert main(["create-admin", ANA], env) == 0

    assert capsys.readouterr().out == f"create-admin: a conta {user.id} já é admin; nada mudou\n"
    assert reload(db_session, user).updated_at == updated_at
    assert count(db_session, AuditLog) == 1


def test_unknown_email_fails_without_changing_anything(db_session, env, capsys):
    save(db_session, new_user("bia@example.com"))

    assert main(["create-admin", ANA], env) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "erro: nenhuma conta com esse email. A pessoa precisa entrar no imago uma vez antes\n"
    )
    db_session.rollback()
    assert count(db_session, User, User.is_admin.is_(True)) == 0
    assert count(db_session, AuditLog) == 0


@pytest.mark.parametrize("email", ["ana", "", "joão@example.com"])
def test_invalid_email_fails(db_session, env, capsys, email):
    assert main(["create-admin", email], env) == 1

    assert capsys.readouterr().err == "erro: email inválido\n"


@pytest.mark.parametrize("change", [{"is_active": False}, {"status": "deleting"}])
def test_blocked_or_deleting_account_is_refused(db_session, env, capsys, change):
    user = new_user(ANA, **change)
    save(db_session, user)

    assert main(["create-admin", ANA], env) == 1

    assert capsys.readouterr().err == (
        f"erro: a conta {user.id} está bloqueada ou em exclusão; nada mudou\n"
    )
    assert reload(db_session, user).is_admin is False
    assert count(db_session, AuditLog) == 0
