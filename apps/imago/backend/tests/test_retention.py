"""Retenção de dados (`app/retention.py`), com o tempo congelado."""

from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from sqlalchemy import select

from app import audit
from app.audit import AuditEvent
from app.db import write_transaction
from app.models import AppTask, AuditLog, LoginCode, MailLog, User, UserSession
from app.retention import (
    delete_expired_login_codes,
    delete_expired_sessions,
    delete_old_auth_events,
    run_cleanup,
)
from tests.factories import new_user, save

NOW = datetime(2026, 6, 1, 3, 0, tzinfo=UTC)
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
IP = "203.0.113.7"


@pytest.fixture
def ana(db_session) -> User:
    user = new_user()
    save(db_session, user)
    return user


def add_event(session, event: AuditEvent, age: timedelta, **kwargs) -> int:
    with time_machine.travel(NOW - age, tick=False), write_transaction(session):
        entry = audit.record(session, event, ip=IP, **kwargs)
        session.flush()
    return entry.id


def add_session(session, user: User, token_hash: str, *, age: timedelta, expires_in: timedelta):
    created = NOW - age
    save(
        session,
        UserSession(
            token_hash=token_hash,
            user_id=user.id,
            created_at=created,
            last_seen_at=created,
            expires_at=NOW + expires_in,
            ip=IP,
        ),
    )


def add_code(session, email: str, age: timedelta) -> None:
    created = NOW - age
    save(
        session,
        LoginCode(
            email=email,
            purpose="login",
            code_hash="c" * 64,
            created_at=created,
            expires_at=created + timedelta(minutes=10),
        ),
    )


def cleanup(session):
    with write_transaction(session):
        return run_cleanup(session, NOW)


def test_auth_events_after_90_days_go_and_ips_are_cleared(db_session, ana):
    recent = add_event(db_session, AuditEvent.LOGIN, 89 * DAY, user_id=ana.id)
    add_event(db_session, AuditEvent.LOGIN, 91 * DAY, user_id=ana.id)
    add_event(db_session, AuditEvent.SEND_CAP_REACHED, 91 * DAY, user_id=None)
    old_terms = add_event(db_session, AuditEvent.TERMS_ACCEPTED, 365 * DAY, user_id=ana.id)
    old_admin = add_event(
        db_session, AuditEvent.USER_BLOCKED, 91 * DAY, user_id=ana.id, details={"target_user_id": 1}
    )

    result = cleanup(db_session)

    assert (result.auth_events_deleted, result.audit_ips_cleared) == (2, 2)
    db_session.rollback()
    remaining = {entry.id: entry.ip for entry in db_session.scalars(select(AuditLog))}
    # Conta e admin ficam, sem o IP depois de 90 dias
    assert remaining == {recent: IP, old_terms: None, old_admin: None}


def test_sessions(db_session, ana):
    add_session(db_session, ana, "a" * 64, age=89 * DAY, expires_in=DAY)
    add_session(db_session, ana, "b" * 64, age=91 * DAY, expires_in=DAY)
    add_session(db_session, ana, "c" * 64, age=61 * DAY, expires_in=-DAY)

    result = cleanup(db_session)

    assert (result.sessions_deleted, result.session_ips_cleared) == (1, 1)
    db_session.rollback()
    remaining = {row.token_hash[0]: row.ip for row in db_session.scalars(select(UserSession))}
    assert remaining == {"a": IP, "b": None}


def test_login_codes_stay_one_day(db_session):
    add_code(db_session, "ana@example.com", 23 * HOUR)
    add_code(db_session, "bia@example.com", 25 * HOUR)

    assert cleanup(db_session).login_codes_deleted == 1

    db_session.rollback()
    assert list(db_session.scalars(select(LoginCode.email))) == ["ana@example.com"]


def test_mail_log_stays_48_hours(db_session):
    save(
        db_session,
        MailLog(app="imago", kind="code", created_at=NOW - 47 * HOUR),
        MailLog(app="ethos", kind="notification", created_at=NOW - 49 * HOUR),
    )

    assert cleanup(db_session).mail_log_deleted == 1

    db_session.rollback()
    assert list(db_session.scalars(select(MailLog.app))) == ["imago"]


def test_done_tasks_stay_7_days_and_pending_ones_stay(db_session, ana):
    def task(app: str, done_age: timedelta | None) -> AppTask:
        done_at = None if done_age is None else NOW - done_age
        return AppTask(
            user_id=ana.id, app=app, action="refresh", created_at=NOW - 30 * DAY, done_at=done_at
        )

    save(db_session, task("ethos", 6 * DAY), task("engrafi", 8 * DAY), task("ethos", None))

    assert cleanup(db_session).app_tasks_deleted == 1

    db_session.rollback()
    remaining = sorted(
        (row.app, row.done_at is None) for row in db_session.scalars(select(AppTask))
    )
    assert remaining == [("ethos", False), ("ethos", True)]


def test_second_run_changes_nothing(db_session, ana):
    add_event(db_session, AuditEvent.LOGIN, 91 * DAY, user_id=ana.id)
    add_event(db_session, AuditEvent.ADMIN_CREATED, 91 * DAY, user_id=ana.id)
    add_session(db_session, ana, "a" * 64, age=91 * DAY, expires_in=-DAY)
    add_code(db_session, "ana@example.com", 2 * DAY)
    save(db_session, MailLog(app="imago", kind="code", created_at=NOW - 3 * DAY))

    assert cleanup(db_session).total == 5
    assert cleanup(db_session).total == 0


@pytest.mark.parametrize(
    "function",
    [run_cleanup, delete_old_auth_events, delete_expired_sessions, delete_expired_login_codes],
)
def test_requires_write_transaction_and_aware_now(db_session, function):
    with pytest.raises(RuntimeError, match="write_transaction"):
        function(db_session, NOW)
    with write_transaction(db_session), pytest.raises(ValueError, match="now sem fuso"):
        function(db_session, NOW.replace(tzinfo=None))
