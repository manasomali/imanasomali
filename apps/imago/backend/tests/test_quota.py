"""Teto de envio compartilhado (`app/mail/quota.py`), com o tempo congelado."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from sqlalchemy import select

from app.audit import AuditEvent
from app.db import create_session_factory, write_transaction
from app.mail import quota
from app.mail.catalog import SendCapReached
from app.mail.kinds import MailKind
from app.mail.quota import QuotaRefusal
from app.models import AuditLog, MailLog
from tests.factories import count, save

NOW = datetime(2026, 3, 10, 20, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(hours=24)


def fill(session, total: int, *, span: timedelta, kind: str = "notification", app: str = "ethos"):
    """`total` envios espalhados por igual nos últimos `span` (o mais velho ainda dentro)."""
    step = span / total
    save(
        session,
        *(
            MailLog(app=app, kind=kind, created_at=NOW - step * index - MINUTE / 2)
            for index in range(total)
        ),
    )


def reserve(session, settings, kind: MailKind, *, app: str = "ethos", now: datetime = NOW):
    with write_transaction(session):
        return quota.reserve(session, settings, app=app, kind=kind, now=now)


def test_limits_follow_the_plan(settings):
    assert quota.limits(settings, MailKind.CODE) == (("hour", 60), ("day", 275))
    assert quota.limits(settings, MailKind.ACCOUNT) == (("hour", 60), ("day", 275))
    assert quota.limits(settings, MailKind.NOTIFICATION) == (("hour", 45), ("day", 215))


def test_reserve_records_the_send_without_recipient(db_session, settings):
    assert reserve(db_session, settings, MailKind.NOTIFICATION) is None

    db_session.rollback()
    [row] = db_session.scalars(select(MailLog))
    assert (row.app, row.kind, row.created_at) == ("ethos", "notification", NOW)


def test_216th_notification_in_24h_is_refused_and_a_code_still_passes(db_session, settings):
    fill(db_session, 215, span=DAY)
    # O teto por hora não bateu: só o do dia
    assert quota.sent_in(db_session, "hour", NOW) < 45

    assert reserve(db_session, settings, MailKind.NOTIFICATION) == QuotaRefusal("day", 215)
    assert reserve(db_session, settings, MailKind.CODE, app="imago") is None
    assert reserve(db_session, settings, MailKind.ACCOUNT, app="imago") is None

    db_session.rollback()
    assert count(db_session, MailLog) == 217


def test_276th_send_is_refused(db_session, settings):
    fill(db_session, 200, span=DAY)
    fill(db_session, 75, span=DAY, kind="code", app="imago")

    assert reserve(db_session, settings, MailKind.CODE, app="imago") == QuotaRefusal("day", 275)
    assert reserve(db_session, settings, MailKind.ACCOUNT, app="imago") == QuotaRefusal("day", 275)

    db_session.rollback()
    assert count(db_session, MailLog) == 275


def test_46th_notification_in_the_hour_is_refused_and_a_code_still_passes(db_session, settings):
    fill(db_session, 45, span=HOUR)

    assert reserve(db_session, settings, MailKind.NOTIFICATION) == QuotaRefusal("hour", 45)
    assert reserve(db_session, settings, MailKind.CODE, app="imago") is None


def test_61st_send_in_the_hour_is_refused(db_session, settings):
    fill(db_session, 45, span=HOUR)
    fill(db_session, 15, span=HOUR, kind="code", app="imago")

    assert reserve(db_session, settings, MailKind.CODE, app="imago") == QuotaRefusal("hour", 60)


def test_windows_are_rolling(db_session, make_settings):
    settings = make_settings(
        max_emails_per_day=2,
        max_emails_per_hour=2,
        mail_reserved_for_codes_per_day=0,
        mail_reserved_for_codes_per_hour=0,
    )
    save(
        db_session,
        # 24 h e 1 min atrás: fora da janela
        MailLog(app="ethos", kind="notification", created_at=NOW - DAY - MINUTE),
        # Exatamente 24 h atrás: também fora (a janela é o intervalo depois dele)
        MailLog(app="ethos", kind="notification", created_at=NOW - DAY),
        MailLog(app="ethos", kind="notification", created_at=NOW - DAY + MINUTE),
    )

    assert quota.sent_in(db_session, "day", NOW) == 1
    assert reserve(db_session, settings, MailKind.NOTIFICATION) is None
    assert reserve(db_session, settings, MailKind.NOTIFICATION) == QuotaRefusal("day", 2)
    # Um minuto e um segundo depois, o envio de 23 h 59 min atrás saiu da janela de 24 h
    later = NOW + MINUTE + timedelta(seconds=1)
    assert reserve(db_session, settings, MailKind.NOTIFICATION, now=later) is None
    # A janela de 1 h tem os dois de agora
    assert reserve(db_session, settings, MailKind.NOTIFICATION, now=later) == QuotaRefusal(
        "hour", 2
    )


def test_zero_reserve_lets_notifications_use_everything(db_session, make_settings):
    settings = make_settings(mail_reserved_for_codes_per_day=0, mail_reserved_for_codes_per_hour=0)

    assert quota.limits(settings, MailKind.NOTIFICATION) == (("hour", 60), ("day", 275))


def test_parallel_reservations_never_pass_the_cap(engine, db_session, make_settings):
    settings = make_settings(
        max_emails_per_day=5,
        max_emails_per_hour=5,
        mail_reserved_for_codes_per_day=0,
        mail_reserved_for_codes_per_hour=0,
    )
    factory = create_session_factory(engine)
    calls = 12
    barrier = threading.Barrier(calls)

    def task(_index):
        with factory() as session:
            barrier.wait()
            return reserve(session, settings, MailKind.NOTIFICATION)

    with ThreadPoolExecutor(max_workers=calls) as executor:
        results = list(executor.map(task, range(calls)))

    assert results.count(None) == 5
    assert results.count(QuotaRefusal("hour", 5)) == 7
    db_session.rollback()
    assert count(db_session, MailLog) == 5


@time_machine.travel(NOW, tick=False)
def test_support_alert_at_most_once_an_hour(db_session):
    refusal = QuotaRefusal("day", 275)

    def alert():
        with write_transaction(db_session):
            return quota.support_alert(db_session, refusal, MailKind.CODE, NOW)

    assert alert() == SendCapReached(window="day", limit=275)
    assert alert() is None
    db_session.rollback()
    [event] = db_session.scalars(select(AuditLog))
    assert (event.event, event.user_id) == (AuditEvent.SEND_CAP_REACHED.value, None)
    assert event.details == {"window": "day", "limit": 275, "kind": "code"}
    # O aviso não conta no teto
    assert count(db_session, MailLog) == 0


def test_support_alert_again_after_an_hour(db_session):
    refusal = QuotaRefusal("hour", 60)

    def alert(at: datetime):
        with time_machine.travel(at, tick=False), write_transaction(db_session):
            return quota.support_alert(db_session, refusal, MailKind.ACCOUNT, at)

    assert alert(NOW) is not None
    assert alert(NOW + 59 * MINUTE) is None
    assert alert(NOW + HOUR + MINUTE) == SendCapReached(window="hour", limit=60)


@pytest.mark.parametrize("app", ["Ethos", "", "a", "ethos!", "x" * 28])
def test_record_refuses_bad_app_names(db_session, app):
    with write_transaction(db_session), pytest.raises(ValueError, match="nome de aplicação"):
        quota.record(db_session, app=app, kind=MailKind.NOTIFICATION, now=NOW)


def test_functions_require_a_write_transaction(db_session, settings):
    with pytest.raises(RuntimeError, match="write_transaction"):
        quota.check(db_session, settings, MailKind.CODE, NOW)
    with pytest.raises(RuntimeError, match="write_transaction"):
        quota.record(db_session, app="imago", kind=MailKind.CODE, now=NOW)
    with pytest.raises(RuntimeError, match="write_transaction"):
        quota.support_alert(db_session, QuotaRefusal("day", 1), MailKind.CODE, NOW)
