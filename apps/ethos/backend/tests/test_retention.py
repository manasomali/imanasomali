import itertools
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.audit import AUTH_EVENTS, AuditEvent
from app.db import write_transaction
from app.models import AuditLog, Habit, LoginCode, User, UserSession
from app.retention import (
    CleanupResult,
    delete_expired_login_codes,
    delete_expired_sessions,
    delete_old_auth_events,
    run_cleanup,
)
from tests.factories import new_habit, new_user, save

NOW = datetime(2026, 6, 1, 3, 0, tzinfo=UTC)
DAY = timedelta(days=1)
IP = "203.0.113.7"
# Hashes de sessão diferentes em cada linha (o valor não importa)
_token_numbers = itertools.count(1)


@pytest.fixture
def ana(db_session) -> User:
    user = new_user()
    save(db_session, user)
    return user


@pytest.fixture
def habit(db_session, ana) -> Habit:
    # Criado há 2 anos, antes de toda a auditoria dos testes
    with time_machine.travel(NOW - 730 * DAY, tick=False):
        habit = new_habit(ana)
        save(db_session, habit)
    return habit


def add_event(
    session: Session,
    event: AuditEvent,
    age: timedelta,
    *,
    user_id: int | None = None,
    habit_id: int | None = None,
) -> int:
    with time_machine.travel(NOW - age, tick=False), write_transaction(session):
        entry = audit.record(session, event, user_id=user_id, ip=IP, habit_id=habit_id)
        session.flush()
    return entry.id


def add_session(session: Session, user: User, age: timedelta, expires_in: timedelta) -> str:
    token_hash = f"{next(_token_numbers):064x}"
    save(
        session,
        UserSession(
            token_hash=token_hash,
            user_id=user.id,
            created_at=NOW - age,
            last_seen_at=NOW - age,
            expires_at=NOW + expires_in,
            ip=IP,
            user_agent="Firefox",
        ),
    )
    return token_hash


def add_code(session: Session, age: timedelta, valid_for: timedelta = timedelta(minutes=10)) -> int:
    code = LoginCode(
        email="ana@example.com",
        purpose="login",
        code_hash="c" * 64,
        created_at=NOW - age,
        expires_at=NOW - age + valid_for,
    )
    save(session, code)
    return code.id


def cleanup(session: Session, now: datetime = NOW) -> CleanupResult:
    with write_transaction(session):
        return run_cleanup(session, now)


def rows(session: Session, model: Any) -> list[Any]:
    session.rollback()
    return list(session.scalars(select(model)))


def snapshot(session: Session) -> dict[str, list[Any]]:
    session.rollback()
    return {
        table.__tablename__: session.execute(select(table.__table__)).all()
        for table in (AuditLog, UserSession, LoginCode)
    }


@pytest.mark.parametrize("event", sorted(AUTH_EVENTS))
def test_auth_events_stay_89_days_and_leave_after_91(db_session, ana, event):
    kept = add_event(db_session, event, 89 * DAY, user_id=ana.id)
    add_event(db_session, event, 91 * DAY, user_id=ana.id)

    result = cleanup(db_session)

    assert result.auth_events_deleted == 1
    assert [(entry.id, entry.ip) for entry in rows(db_session, AuditLog)] == [(kept, IP)]


def test_mark_and_configuration_audit_is_never_deleted(db_session, ana, habit):
    year = 365 * DAY
    kept = {
        add_event(db_session, AuditEvent.MARK_CREATED, year, user_id=ana.id, habit_id=habit.id),
        add_event(db_session, AuditEvent.MARK_DELETED, year, user_id=ana.id, habit_id=habit.id),
        add_event(db_session, AuditEvent.HABIT_UPDATED, year, user_id=ana.id, habit_id=habit.id),
        add_event(db_session, AuditEvent.MEMBER_REMOVED, year, user_id=ana.id, habit_id=habit.id),
        add_event(db_session, AuditEvent.HABIT_DELETED, year, user_id=ana.id),
        add_event(db_session, AuditEvent.TERMS_ACCEPTED, year, user_id=ana.id),
        add_event(db_session, AuditEvent.ADMIN_VIEWED_HABITS, year, user_id=ana.id),
    }

    result = cleanup(db_session)

    assert result.auth_events_deleted == 0
    remaining = rows(db_session, AuditLog)
    assert {entry.id for entry in remaining} == kept
    # O IP some mesmo nas linhas que ficam
    assert {entry.ip for entry in remaining} == {None}
    assert result.audit_ips_cleared == len(kept)


def test_audit_ip_stays_89_days_and_is_cleared_after_91(db_session, ana, habit):
    recent = add_event(db_session, AuditEvent.MARK_CREATED, 89 * DAY, habit_id=habit.id)
    old = add_event(db_session, AuditEvent.MARK_CREATED, 91 * DAY, habit_id=habit.id)

    result = cleanup(db_session)

    assert {entry.id: entry.ip for entry in rows(db_session, AuditLog)} == {recent: IP, old: None}
    assert result.audit_ips_cleared == 1


def test_sessions(db_session, ana):
    expired = add_session(db_session, ana, 10 * DAY, expires_in=-timedelta(seconds=1))
    # Renovada com o uso: ainda vale, mas foi criada há mais de 90 dias
    renewed = add_session(db_session, ana, 91 * DAY, expires_in=30 * DAY)
    recent = add_session(db_session, ana, 89 * DAY, expires_in=30 * DAY)
    # Vence exatamente agora: ainda não está vencida
    boundary = add_session(db_session, ana, 59 * DAY, expires_in=timedelta(0))

    result = cleanup(db_session)

    remaining = {entry.token_hash: entry for entry in rows(db_session, UserSession)}
    assert expired not in remaining
    assert set(remaining) == {renewed, recent, boundary}
    assert remaining[renewed].ip is None
    assert remaining[recent].ip == IP
    assert remaining[renewed].user_agent == "Firefox"
    assert (result.sessions_deleted, result.session_ips_cleared) == (1, 1)


def test_login_codes(db_session):
    # Vencido há mais de 1 dia: sai
    add_code(db_session, 25 * timedelta(hours=1))
    # Vencido há pouco: fica, porque os limites de envio por hora e por dia contam esta linha
    counted = add_code(db_session, 2 * timedelta(hours=1))
    valid = add_code(db_session, timedelta(minutes=5))

    result = cleanup(db_session)

    assert {code.id for code in rows(db_session, LoginCode)} == {counted, valid}
    assert result.login_codes_deleted == 1


def fill_everything(session: Session, user: User, habit: Habit) -> None:
    for age in (1 * DAY, 89 * DAY, 91 * DAY, 400 * DAY):
        add_event(session, AuditEvent.LOGIN, age, user_id=user.id)
        add_event(session, AuditEvent.MARK_CREATED, age, user_id=user.id, habit_id=habit.id)
        # Só a de 1 dia está vencida; as outras foram renovadas
        add_session(session, user, age, expires_in=age - 60 * DAY)
        add_code(session, age)


def test_result_counts_every_change(db_session, ana, habit):
    fill_everything(db_session, ana, habit)

    result = cleanup(db_session)

    assert result == CleanupResult(
        auth_events_deleted=2,
        audit_ips_cleared=2,
        sessions_deleted=1,
        session_ips_cleared=2,
        login_codes_deleted=3,
    )
    assert result.total == 10


def test_second_run_changes_nothing(db_session, ana, habit):
    fill_everything(db_session, ana, habit)
    first = cleanup(db_session)
    before = snapshot(db_session)

    second = cleanup(db_session)

    assert first.total > 0
    assert second.total == 0
    assert snapshot(db_session) == before


def test_rollback_undoes_the_cleanup(db_session, ana, habit):
    fill_everything(db_session, ana, habit)
    before = snapshot(db_session)

    def fail_after_cleanup() -> None:
        with write_transaction(db_session):
            run_cleanup(db_session, NOW)
            raise RuntimeError("falhou depois")

    with pytest.raises(RuntimeError, match="falhou depois"):
        fail_after_cleanup()
    assert snapshot(db_session) == before


CLEANUP_FUNCTIONS = [
    run_cleanup,
    delete_old_auth_events,
    delete_expired_sessions,
    delete_expired_login_codes,
]


@pytest.mark.parametrize("function", CLEANUP_FUNCTIONS)
def test_outside_write_transaction_is_refused(db_session, function: Callable[..., Any]):
    with pytest.raises(RuntimeError, match="fora de write_transaction"):
        function(db_session, NOW)


@pytest.mark.parametrize("function", CLEANUP_FUNCTIONS)
def test_now_without_timezone_is_refused(db_session, function: Callable[..., Any]):
    with pytest.raises(ValueError, match="now sem fuso"), write_transaction(db_session):
        function(db_session, NOW.replace(tzinfo=None))
