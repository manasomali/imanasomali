import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import pytest
import time_machine
from sqlalchemy import select

from app import audit
from app.audit import AUTH_EVENTS, MAX_DETAILS_DEPTH, MAX_DETAILS_LENGTH, AuditError, AuditEvent
from app.db import write_transaction
from app.models import EVENT_MAX_LENGTH, AuditLog, User
from tests.factories import count, new_user, save

NOW = datetime(2026, 3, 10, 9, 30, tzinfo=UTC)


@pytest.fixture
def ana(db_session) -> User:
    user = new_user()
    save(db_session, user)
    return user


def record(session, event: Any = AuditEvent.LOGIN, **kwargs: Any) -> AuditLog:
    """Grava um evento numa transação própria (user_id=None se não vier)."""
    kwargs.setdefault("user_id", None)
    with write_transaction(session):
        return audit.record(session, event, **kwargs)


def all_events(session) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).order_by(AuditLog.id)))


@time_machine.travel(NOW, tick=False)
def test_event_is_saved_with_every_field(db_session, ana):
    record(
        db_session,
        AuditEvent.EMAIL_CHANGED,
        user_id=ana.id,
        ip="203.0.113.7",
        details={"target_user_id": 12, "old_email": "a@b.com", "new_email": "c@d.com"},
    )

    [saved] = all_events(db_session)
    assert saved.user_id == ana.id
    assert saved.event == "email_changed"
    assert saved.ip == "203.0.113.7"
    assert saved.created_at == NOW
    assert saved.details == {"target_user_id": 12, "old_email": "a@b.com", "new_email": "c@d.com"}


def test_system_event_has_no_author(db_session):
    record(db_session, AuditEvent.SEND_CAP_REACHED, details={"window": "day", "limit": 275})

    [saved] = all_events(db_session)
    assert (saved.user_id, saved.ip) == (None, None)


def test_rollback_drops_the_event(db_session, ana):
    def fail() -> None:
        with write_transaction(db_session):
            audit.record(db_session, AuditEvent.LOGIN, user_id=ana.id)
            raise LookupError

    with pytest.raises(LookupError):
        fail()
    assert count(db_session, AuditLog) == 0


def test_record_outside_write_transaction_is_refused(db_session):
    with pytest.raises(RuntimeError, match="fora de write_transaction"):
        audit.record(db_session, AuditEvent.LOGIN, user_id=None)
    assert not db_session.new


@pytest.mark.parametrize("event", ["login_ok", "LOGIN", "", "mark created", 3, None])
def test_unknown_event_is_refused(db_session, event):
    with pytest.raises(AuditError, match="evento de auditoria desconhecido"):
        record(db_session, event)
    assert count(db_session, AuditLog) == 0


@pytest.mark.parametrize(
    "details",
    [
        {"code": "123456"},
        {"login_code": "123456"},
        {"codeHash": "abc"},
        {"CODE": 1},
        {"token": "x"},
        {"session_token": "x"},
        {"csrfToken": "x"},
        {"cookie": "x"},
        {"Set-Cookie": "x"},
        {"password": "x"},
        {"smtp_passwd": "x"},
        {"pwd": "x"},
        {"client_secret": "x"},
        {"Authorization": "Bearer x"},
        {"credentials": "x"},
        {"co​de": "x"},
        {"changes": {"token": "x"}},
        {"changes": [{"field": "note"}, {"cookie": "x"}]},
        {"a": {"b": {"c": {"refresh_token": "x"}}}},
    ],
)
def test_sensitive_key_in_details_is_refused(db_session, details):
    with pytest.raises(AuditError, match="chave sensível") as raised:
        record(db_session, details=details)
    # A mensagem cita a chave, nunca o valor
    assert "123456" not in str(raised.value)
    assert "Bearer" not in str(raised.value)
    assert count(db_session, AuditLog) == 0


def test_sensitive_field_name_goes_as_a_value(db_session):
    # O nome de um campo sensível vai como valor, nunca como chave
    details = {"changes": [{"field": "code", "old": "AB", "new": "CD"}], "email": "a@b.com"}
    record(db_session, AuditEvent.PROFILE_UPDATED, details=details)
    assert all_events(db_session)[0].details == details


def nested(depth: int) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for _ in range(depth):
        value = {"n": value}
    return value


def cyclic() -> dict[str, Any]:
    value: dict[str, Any] = {}
    value["self"] = value
    return value


@pytest.mark.parametrize(
    ("details", "message"),
    [
        ({"when": datetime(2026, 1, 1, tzinfo=UTC)}, "não serializável em details.when"),
        ({"ids": {1, 2}}, "não serializável em details.ids"),
        ({"raw": b"abc"}, "não serializável em details.raw"),
        ({"obj": object()}, "não serializável"),
        ({"list": [1, [2, {3}]]}, r"não serializável em details\.list\[1\]\[1\]"),
        ({"value": math.nan}, "não finito"),
        ({"value": math.inf}, "não finito"),
        ({"value": -math.inf}, "não finito"),
        ({1: "a"}, "chave que não é texto"),
        ({"a": {None: "b"}}, "chave que não é texto em details.a"),
        (nested(MAX_DETAILS_DEPTH + 1), "aninhado demais"),
        (cyclic(), "aninhado demais"),
        ({"text": "x" * MAX_DETAILS_LENGTH}, "grande demais"),
        (["login"], "precisa ser dict"),
        ("{}", "precisa ser dict"),
    ],
)
def test_invalid_details_are_refused(db_session, details, message):
    with pytest.raises(AuditError, match=message):
        record(db_session, details=details)
    assert count(db_session, AuditLog) == 0


def test_details_at_the_limits_are_accepted(db_session):
    deepest = nested(MAX_DETAILS_DEPTH)
    record(db_session, details=deepest)
    # {"text": "..."} com o tamanho máximo exato
    largest = {"text": "x" * (MAX_DETAILS_LENGTH - len('{"text": ""}'))}
    record(db_session, details=largest)
    assert [entry.details for entry in all_events(db_session)] == [deepest, largest]


def test_size_limit_counts_escaped_characters(db_session):
    # Fora do ASCII, o JSON gravado escapa cada caractere (ç): 6 caracteres no banco
    with pytest.raises(AuditError, match="grande demais"):
        record(db_session, details={"text": "ç" * (MAX_DETAILS_LENGTH // 6 + 1)})


class Color(StrEnum):
    TEAL = "teal"


def test_details_are_copied_as_json(db_session):
    details: dict[str, Any] = {"ids": (1, 2), "color": Color.TEAL, "ok": True, "n": 1.5}
    entry = record(db_session, details=details)
    details["ids"] = "mudou depois"
    assert entry.details == {"ids": [1, 2], "color": "teal", "ok": True, "n": 1.5}
    db_session.expunge_all()
    assert all_events(db_session)[0].details == entry.details


@pytest.mark.parametrize(
    ("ip", "saved"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:DB8:0:0:0:0:0:1", "2001:db8::1"),
        ("::ffff:203.0.113.7", "::ffff:203.0.113.7"),
        (None, None),
    ],
)
def test_ip_is_normalized(db_session, ip, saved):
    record(db_session, ip=ip)
    assert all_events(db_session)[0].ip == saved


@pytest.mark.parametrize(
    ("ip", "message"),
    [
        ("", "ip inválido"),
        ("999.1.1.1", "ip inválido"),
        ("203.0.113.7:443", "ip inválido"),
        ("localhost", "ip inválido"),
        ("fe80::1%" + "x" * 50, "ip longo demais"),
        (3405803783, "ip precisa ser texto"),
    ],
)
def test_invalid_ip_is_refused(db_session, ip, message):
    with pytest.raises(AuditError, match=message) as raised:
        record(db_session, ip=ip)
    # O valor recebido não vai para a mensagem
    if ip:
        assert str(ip) not in str(raised.value)


@pytest.mark.parametrize(
    ("field", "value"), [("user_id", "1"), ("user_id", True), ("user_id", 1.0)]
)
def test_ids_must_be_int_or_none(db_session, field, value):
    with pytest.raises(TypeError, match=f"{field} precisa ser int ou None"):
        record(db_session, **{field: value})


def test_event_list_is_well_formed():
    for event in AuditEvent:
        assert re.fullmatch(r"[a-z]+(_[a-z]+)*", event.value), event
        assert len(event.value) <= EVENT_MAX_LENGTH, event
    assert {
        AuditEvent.CODE_REQUESTED,
        AuditEvent.LOGIN,
        AuditEvent.LOGIN_FAILED,
        AuditEvent.LOGOUT,
        AuditEvent.LOGOUT_ALL,
        AuditEvent.DELETE_CODE_REQUESTED,
        AuditEvent.SEND_CAP_REACHED,
    } == AUTH_EVENTS
    # Eventos da conta e do admin ficam enquanto a conta existe
    kept = set(AuditEvent) - AUTH_EVENTS
    assert kept == {
        AuditEvent.TERMS_ACCEPTED,
        AuditEvent.PROFILE_UPDATED,
        AuditEvent.ACCOUNT_DELETION_STARTED,
        AuditEvent.ACCOUNT_DELETED,
        AuditEvent.ADMIN_CREATED,
        AuditEvent.USER_BLOCKED,
        AuditEvent.USER_UNBLOCKED,
        AuditEvent.EMAIL_CHANGED,
    }
