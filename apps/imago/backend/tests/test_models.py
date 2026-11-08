"""Constraints do banco: os CHECK dos enums e tamanhos, o id da conta e as chaves estrangeiras."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.db import write_transaction
from app.models import (
    MAX_ACCOUNT_ID,
    AppTask,
    AuditLog,
    LoginCode,
    MailLog,
    User,
    UserSession,
)
from tests.factories import count, new_user, save

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def insert_user_sql(db_session, **values) -> None:
    columns = {
        "id": 7,
        "email": "ana@example.com",
        "timezone": "UTC",
        "locale": "pt",
        "terms_version": "v",
        "terms_accepted_at": "2026-01-15 12:00:00.000000",
        "created_at": "2026-01-15 12:00:00.000000",
        "updated_at": "2026-01-15 12:00:00.000000",
    } | values
    names = ", ".join(columns)
    params = ", ".join(f":{name}" for name in columns)
    with write_transaction(db_session):
        db_session.execute(text(f"INSERT INTO users ({names}) VALUES ({params})"), columns)  # noqa: S608


def test_user_without_id_is_refused(db_session):
    # BIGINT não vira o rowid: sem id, o NOT NULL recusa em vez de dar um id sequencial
    with pytest.raises(IntegrityError, match=r"NOT NULL constraint failed: users.id"):
        insert_user_sql(db_session, id=None)


@pytest.mark.parametrize("user_id", [0, -1, MAX_ACCOUNT_ID + 1])
def test_user_id_out_of_range_is_refused(db_session, user_id):
    with pytest.raises(IntegrityError, match="ck_users_id_range"):
        insert_user_sql(db_session, id=user_id)


@pytest.mark.parametrize("user_id", [1, MAX_ACCOUNT_ID])
def test_user_id_limits_are_accepted(db_session, user_id):
    insert_user_sql(db_session, id=user_id)

    assert db_session.scalar(select(User.id)) == user_id


@pytest.mark.parametrize(
    ("email", "constraint"),
    [
        ("Ana@example.com", "ck_users_email_normalized"),
        (" ana@example.com", "ck_users_email_normalized"),
        ("joão@example.com", "ck_users_email_ascii"),
        ("ana\t@example.com", "ck_users_email_ascii"),
        ("a@", "ck_users_email_length"),
        ("a" * 243 + "@example.com", "ck_users_email_length"),
    ],
)
def test_user_email_checks(db_session, email, constraint):
    with pytest.raises(IntegrityError, match=constraint):
        insert_user_sql(db_session, email=email)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"status": "deleted"}, "ck_users_status"),
        ({"locale": "es"}, "ck_users_locale"),
        ({"timezone": ""}, "ck_users_timezone_length"),
        ({"terms_version": None}, "ck_users_terms_accepted"),
        ({"terms_accepted_at": None}, "ck_users_terms_accepted"),
        ({"terms_version": "x" * 33}, "ck_users_terms_version_length"),
    ],
)
def test_user_checks(db_session, values, constraint):
    with pytest.raises(IntegrityError, match=constraint):
        insert_user_sql(db_session, **values)


def test_user_without_any_terms_is_accepted(db_session):
    # Conta importada do ethos: ainda não aceitou nenhuma versão
    insert_user_sql(db_session, terms_version=None, terms_accepted_at=None)

    user = db_session.scalar(select(User))
    assert (user.terms_version, user.terms_accepted_at, user.status) == (None, None, "active")


def test_user_email_is_unique(db_session):
    save(db_session, new_user("ana@example.com"))

    with pytest.raises(IntegrityError, match=r"UNIQUE constraint failed: users.email"):
        save(db_session, new_user("ana@example.com"))


def mail(app: str, kind: str = "code") -> MailLog:
    return MailLog(app=app, kind=kind, created_at=NOW)


@pytest.mark.parametrize("app", ["imago", "ethos", "a-1", "ab", "a" + "b" * 26])
def test_mail_log_accepts_app_names(db_session, app):
    save(db_session, mail(app))

    assert db_session.scalar(select(MailLog.app)) == app


@pytest.mark.parametrize("app", ["Ethos", "1ethos", "-ethos", "a", "eth_os", "eth os", "a" * 28])
def test_mail_log_refuses_bad_app_names(db_session, app):
    with pytest.raises(IntegrityError, match="ck_mail_log_app"):
        save(db_session, mail(app))


def test_mail_log_refuses_unknown_kind(db_session):
    with pytest.raises(IntegrityError, match="ck_mail_log_kind"):
        save(db_session, mail("ethos", kind="marketing"))


def task(user: User, **values) -> AppTask:
    return AppTask(**({"user_id": user.id, "app": "ethos", "action": "refresh"} | values))


def test_one_pending_task_per_user_app_and_action(db_session):
    user = new_user()
    save(db_session, user)
    save(db_session, task(user), task(user, action="delete"), task(user, app="engrafi"))

    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        save(db_session, task(user))


def test_done_tasks_do_not_block_a_new_pending_one(db_session):
    user = new_user()
    save(db_session, user)
    save(db_session, task(user, done_at=NOW), task(user, done_at=NOW + timedelta(hours=1)))

    save(db_session, task(user))

    assert count(db_session, AppTask) == 3


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"action": "purge"}, "ck_app_tasks_action"),
        ({"app": "Ethos"}, "ck_app_tasks_app"),
        ({"attempts": -1}, "ck_app_tasks_attempts_not_negative"),
    ],
)
def test_app_task_checks(db_session, values, constraint):
    user = new_user()
    save(db_session, user)

    with pytest.raises(IntegrityError, match=constraint):
        save(db_session, task(user, **values))


def test_login_code_refuses_unknown_purpose(db_session):
    code = LoginCode(
        email="ana@example.com",
        purpose="reset_password",
        code_hash="a" * 64,
        expires_at=NOW,
        created_at=NOW,
    )
    with pytest.raises(IntegrityError, match="ck_login_codes_purpose"):
        save(db_session, code)


def test_deleting_a_user_cascades_and_keeps_the_audit_anonymous(db_session):
    user, other = new_user("ana@example.com"), new_user("bia@example.com")
    save(db_session, user, other)
    save(
        db_session,
        UserSession(token_hash="a" * 64, user_id=user.id, expires_at=NOW),
        UserSession(token_hash="b" * 64, user_id=other.id, expires_at=NOW),
        LoginCode(
            email=user.email,
            user_id=user.id,
            purpose="delete_account",
            code_hash="c" * 64,
            expires_at=NOW,
        ),
        task(user),
        AuditLog(user_id=user.id, event="login"),
    )

    with write_transaction(db_session):
        db_session.execute(delete(User).where(User.id == user.id))

    db_session.rollback()
    assert count(db_session, UserSession) == 1
    assert count(db_session, LoginCode) == 0
    assert count(db_session, AppTask) == 0
    assert db_session.scalar(select(AuditLog.user_id)) is None
    assert count(db_session, AuditLog) == 1


def test_datetimes_are_utc_and_naive_ones_are_refused(db_session):
    # 09:00 em São Paulo (UTC-3) é 12:00 UTC
    user = new_user(created_at=datetime(2026, 3, 10, 9, 0, tzinfo=timezone(timedelta(hours=-3))))
    save(db_session, user)
    db_session.rollback()
    stored = db_session.scalar(select(User.created_at))
    assert stored == NOW
    assert stored.tzinfo is UTC

    with pytest.raises(StatementError, match="datetime sem fuso"):
        save(db_session, new_user("bia@example.com", created_at=datetime(2026, 3, 10)))
    db_session.rollback()
    with pytest.raises(StatementError, match="esperava datetime"):
        save(db_session, new_user("caio@example.com", created_at=date(2026, 3, 10)))
