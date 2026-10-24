import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import pytest
import time_machine
from sqlalchemy import delete, select

from app import audit
from app.audit import AUTH_EVENTS, MAX_DETAILS_DEPTH, MAX_DETAILS_LENGTH, AuditError, AuditEvent
from app.db import write_transaction
from app.models import EVENT_MAX_LENGTH, AuditLog, Habit, User
from tests.factories import count, new_habit, new_user, save

NOW = datetime(2026, 3, 10, 9, 30, tzinfo=UTC)


@pytest.fixture
def ana(db_session) -> User:
    user = new_user()
    save(db_session, user)
    return user


@pytest.fixture
def habit(db_session, ana) -> Habit:
    habit = new_habit(ana)
    save(db_session, habit)
    return habit


def record(session, event: Any = AuditEvent.LOGIN, **kwargs: Any) -> AuditLog:
    """Grava um evento numa transação própria (user_id=None se não vier)."""
    kwargs.setdefault("user_id", None)
    with write_transaction(session):
        return audit.record(session, event, **kwargs)


def all_events(session) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).order_by(AuditLog.id)))


@time_machine.travel(NOW, tick=False)
def test_event_is_saved_with_every_field(db_session, ana, habit):
    entry = record(
        db_session,
        AuditEvent.MARK_CREATED,
        user_id=ana.id,
        ip="203.0.113.7",
        habit_id=habit.id,
        details={"mark_id": 12, "changes": [{"field": "note", "old": None, "new": "ok"}]},
    )
    db_session.expunge_all()
    (saved,) = all_events(db_session)
    assert saved.id == entry.id
    assert saved.user_id == ana.id
    assert saved.habit_id == habit.id
    assert saved.event == "mark_created"
    assert saved.ip == "203.0.113.7"
    assert saved.created_at == NOW
    assert saved.details == {
        "mark_id": 12,
        "changes": [{"field": "note", "old": None, "new": "ok"}],
    }


def test_optional_fields_default_to_empty(db_session):
    record(db_session, AuditEvent.LOGOUT)
    (saved,) = all_events(db_session)
    assert (saved.user_id, saved.habit_id, saved.ip, saved.details) == (None, None, None, {})


def test_event_name_as_text_is_accepted(db_session):
    record(db_session, "logout_all")
    assert [entry.event for entry in all_events(db_session)] == ["logout_all"]


def test_rollback_also_discards_the_event(db_session, ana):
    def fail_after_event() -> None:
        with write_transaction(db_session):
            audit.record(db_session, AuditEvent.LOGIN, user_id=ana.id, ip="203.0.113.7")
            db_session.flush()
            raise RuntimeError("falhou depois do evento")

    with pytest.raises(RuntimeError, match="falhou depois"):
        fail_after_event()
    assert count(db_session, AuditLog) == 0


def test_event_and_change_are_committed_together(db_session, ana):
    with write_transaction(db_session):
        habit = new_habit(ana)
        db_session.add(habit)
        db_session.flush()
        audit.record(db_session, AuditEvent.HABIT_CREATED, user_id=ana.id, habit_id=habit.id)
    (saved,) = all_events(db_session)
    assert saved.habit_id == habit.id


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
    # Mudança da sigla do hábito (coluna habits.code): o nome do campo vai como valor
    details = {"changes": [{"field": "code", "old": "AB", "new": "CD"}], "email": "a@b.com"}
    record(db_session, AuditEvent.HABIT_UPDATED, details=details)
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
    ("field", "value"), [("user_id", "1"), ("user_id", True), ("habit_id", 1.0)]
)
def test_ids_must_be_int_or_none(db_session, field, value):
    with pytest.raises(TypeError, match=f"{field} precisa ser int ou None"):
        record(db_session, **{field: value})


def test_habit_deleted_survives_the_habit(db_session, ana, habit):
    """`habit_id` tem ON DELETE CASCADE: o evento da exclusão vai com o id só no details."""
    record(db_session, AuditEvent.HABIT_UPDATED, user_id=ana.id, habit_id=habit.id)
    with write_transaction(db_session):
        db_session.execute(delete(Habit).where(Habit.id == habit.id))
        audit.record(
            db_session,
            AuditEvent.HABIT_DELETED,
            user_id=ana.id,
            details={"habit_id": habit.id},
        )
    (saved,) = all_events(db_session)
    assert (saved.event, saved.habit_id) == ("habit_deleted", None)
    assert saved.details == {"habit_id": habit.id}


def test_event_list_is_well_formed():
    for event in AuditEvent:
        assert re.fullmatch(r"[a-z]+(_[a-z]+)*", event.value), event
        assert len(event.value) <= EVENT_MAX_LENGTH, event
    assert {AuditEvent.LOGIN, AuditEvent.LOGOUT, AuditEvent.LOGOUT_ALL} <= AUTH_EVENTS
    # Auditoria de marcações e de configuração não é de auth (fica enquanto o hábito existir)
    kept = {"mark_", "habit_", "invite_", "member_", "alert_", "admin_", "account_", "email_"}
    for event in AUTH_EVENTS:
        assert not any(event.value.startswith(prefix) for prefix in kept), event
