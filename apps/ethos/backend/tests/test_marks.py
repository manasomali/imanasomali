"""Marcações: toggle, várias por dia, listar, editar e apagar (ETH-22)."""

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from sqlalchemy import delete, select

from app.audit import AuditEvent
from app.db import create_session_factory, write_transaction
from app.errors import ApiError
from app.habits import service as habits_service
from app.habits.access import MAX_ID
from app.main import create_app
from app.marks import service
from app.marks.service import day_bounds, decode_cursor, encode_cursor
from app.models import Mark, User
from tests.factories import new_habit, new_mark, save
from tests.habit_helpers import (
    FORBIDDEN,
    NOT_FOUND,
    Account,
    created,
    events,
    invalid,
    share,
    stored,
)

IP = "203.0.113.7"
SP = ZoneInfo("America/Sao_Paulo")
# 12:00 em São Paulo, quarta-feira
NOW = datetime(2026, 3, 25, 15, 0, tzinfo=UTC)
TODAY = date(2026, 3, 25)
ARCHIVED = {"error": "habit_archived", "field": None}
MODE_MISMATCH = {"error": "mark_mode_mismatch", "field": None}
LIMIT_REACHED = {"error": "mark_limit_reached", "field": None}
MULTI = {"multi_mark": True, "goal_count": 10}


@pytest.fixture(autouse=True)
def clock() -> Iterator[time_machine.Traveller]:
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def make_app_client(settings, make_settings, database, make_client, outbox):
    def build(**overrides: Any):
        current = make_settings(**overrides) if overrides else settings
        return make_client(create_app(current, mail_backend=outbox), client=(IP, 50000))

    return build


@pytest.fixture
def client(make_app_client):
    return make_app_client()


@pytest.fixture
def ana(make_account) -> Account:
    return make_account("ana@example.com")


@pytest.fixture
def bia(make_account) -> Account:
    return make_account("bia@example.com")


def iso(value: datetime) -> str:
    return value.isoformat()


def day_of(day: date, tz: ZoneInfo = SP) -> tuple[datetime, datetime]:
    return day_bounds(datetime(day.year, day.month, day.day, 12, tzinfo=tz), tz)


def noon(day: date, tz: ZoneInfo = SP) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=tz).astimezone(UTC)


def toggle(client, account: Account, habit_id: int, day: date = TODAY, **fields):
    start, end = day_of(day)
    marked_at = NOW if day == TODAY else noon(day)
    body = {"day_start": iso(start), "day_end": iso(end), "marked_at": iso(marked_at)} | fields
    return client.post(f"/habits/{habit_id}/toggle", json=body, headers=account.headers)


def toggled(client, account: Account, habit_id: int, day: date = TODAY, **fields) -> dict:
    response = toggle(client, account, habit_id, day, **fields)
    assert response.status_code == 200, response.json()
    return response.json()


def add(client, account: Account, habit_id: int, **fields):
    body = {"marked_at": iso(NOW)} | fields
    return client.post(f"/habits/{habit_id}/marks", json=body, headers=account.headers)


def added(client, account: Account, habit_id: int, **fields) -> dict:
    response = add(client, account, habit_id, **fields)
    assert response.status_code == 201, response.json()
    return response.json()


def patch(client, account: Account, habit_id: int, mark_id: int, body: dict):
    return client.patch(f"/habits/{habit_id}/marks/{mark_id}", json=body, headers=account.headers)


def remove(client, account: Account, habit_id: int, mark_id: int):
    return client.delete(f"/habits/{habit_id}/marks/{mark_id}", headers=account.headers)


def listed(client, account: Account, habit_id: int, **params):
    query = {"from": iso(NOW - timedelta(days=30)), "to": iso(NOW + timedelta(days=1))} | params
    return client.get(f"/habits/{habit_id}/marks", params=query, headers=account.headers)


def stored_marks(db_session, habit_id: int) -> list[Mark]:
    db_session.rollback()
    query = select(Mark).where(Mark.habit_id == habit_id).order_by(Mark.marked_at, Mark.id)
    return list(db_session.scalars(query.execution_options(populate_existing=True)))


def event_names(db_session) -> list[str]:
    return [
        entry.event
        for name in (AuditEvent.MARK_CREATED, AuditEvent.MARK_UPDATED, AuditEvent.MARK_DELETED)
        for entry in events(db_session, name)
    ]


# --- toggle ---


def test_toggle_marks_and_unmarks_the_day(client, ana, db_session):
    habit = created(client, ana)

    first = toggled(client, ana, habit["id"])

    [mark] = stored_marks(db_session, habit["id"])
    mark_id = mark.id
    assert mark.user_id == ana.user.id
    assert first == {
        "marked": True,
        "mark": {
            "id": mark_id,
            "habit_id": habit["id"],
            "author": {"id": ana.user.id, "email": "ana@example.com"},
            "marked_at": "2026-03-25T15:00:00Z",
            "duration_minutes": None,
            "cost_cents": None,
            "note": None,
            "created_at": "2026-03-25T15:00:00Z",
            "updated_at": "2026-03-25T15:00:00Z",
        },
    }

    second = toggled(client, ana, habit["id"])

    assert second == {"marked": False, "mark": None}
    assert stored_marks(db_session, habit["id"]) == []
    [created_event] = events(db_session, AuditEvent.MARK_CREATED)
    [deleted_event] = events(db_session, AuditEvent.MARK_DELETED)
    snapshot = {
        "mark_id": mark_id,
        "author_id": ana.user.id,
        "marked_at": "2026-03-25T15:00:00+00:00",
        "duration_minutes": None,
        "cost_cents": None,
        "has_note": False,
    }
    for entry in (created_event, deleted_event):
        assert (entry.user_id, entry.habit_id, entry.ip) == (ana.user.id, habit["id"], IP)
        assert entry.details == snapshot


def test_toggle_unmarks_every_mark_of_the_day_for_everyone(client, ana, bia, db_session):
    habit = created(client, ana)
    share(db_session, habit["id"], bia, "editor")
    start, end = day_of(TODAY)
    # Várias marcações no dia (o hábito já foi de várias por dia), de autores diferentes, e
    # vizinhas do intervalo, que ficam
    inside = (start, start + timedelta(hours=10), end - timedelta(microseconds=1))
    outside = (start - timedelta(microseconds=1), end)
    with write_transaction(db_session):
        for when in inside:
            db_session.add(Mark(habit_id=habit["id"], user_id=ana.user.id, marked_at=when))
        for when in outside:
            db_session.add(Mark(habit_id=habit["id"], user_id=bia.user.id, marked_at=when))

    assert toggled(client, bia, habit["id"]) == {"marked": False, "mark": None}

    assert [mark.marked_at for mark in stored_marks(db_session, habit["id"])] == list(outside)
    deleted = events(db_session, AuditEvent.MARK_DELETED)
    assert len(deleted) == 3
    assert {entry.user_id for entry in deleted} == {bia.user.id}
    assert {entry.details["author_id"] for entry in deleted} == {ana.user.id}


@pytest.mark.parametrize(
    ("hours", "status"), [(22, 422), (23, 200), (24, 200), (25, 200), (26, 422)]
)
def test_toggle_day_length(client, ana, db_session, hours, status):
    habit = created(client, ana)
    start = NOW - timedelta(hours=12)

    response = toggle(
        client, ana, habit["id"], day_start=iso(start), day_end=iso(start + timedelta(hours=hours))
    )

    assert response.status_code == status, response.json()
    if status == 422:
        assert response.json() == invalid("day_end")
        assert stored_marks(db_session, habit["id"]) == []


def test_toggle_on_daylight_saving_days(client, make_account):
    # Nova York: 2/11/2025 tem 25 h e 8/03/2026 tem 23 h
    new_york = ZoneInfo("America/New_York")
    account = make_account("ny@example.com", timezone="America/New_York")
    habit = created(client, account)
    for day, hours in ((date(2025, 11, 2), 25), (date(2026, 3, 8), 23)):
        start, end = day_of(day, new_york)
        assert end - start == timedelta(hours=hours)
        response = toggle(
            client,
            account,
            habit["id"],
            day_start=iso(start),
            day_end=iso(end),
            marked_at=iso(noon(day, new_york)),
        )
        assert response.json()["marked"] is True


@pytest.mark.parametrize(
    "marked_at",
    [
        # Antes do início e no fim (exclusivo) do dia
        datetime(2026, 3, 25, 2, 59, 59, tzinfo=UTC),
        datetime(2026, 3, 26, 3, 0, tzinfo=UTC),
    ],
)
def test_toggle_marked_at_must_be_inside_the_day(client, ana, marked_at):
    habit = created(client, ana)

    response = toggle(client, ana, habit["id"], marked_at=iso(marked_at))

    assert response.status_code == 422
    assert response.json() == invalid("marked_at")


def test_toggle_with_duration_and_cost(client, ana):
    duration = created(client, ana, duration_enabled=True, duration_minutes=25)
    fixed = created(client, ana, cost_enabled=True, cost_level="habit", cost_cents=800)
    per_mark = created(client, ana, cost_enabled=True, cost_level="mark", cost_cents=1500)
    no_default = created(client, ana, cost_enabled=True, cost_level="mark")
    hidden = created(client, ana)
    # Recursos desligados com valores guardados: a marcação não os herda
    client.patch(
        f"/habits/{hidden['id']}",
        json={"duration_enabled": True, "duration_minutes": 10},
        headers=ana.headers,
    )
    client.patch(f"/habits/{hidden['id']}", json={"duration_enabled": False}, headers=ana.headers)

    marks = {
        name: toggled(client, ana, habit["id"])["mark"]
        for name, habit in [
            ("duration", duration),
            ("fixed", fixed),
            ("per_mark", per_mark),
            ("no_default", no_default),
            ("hidden", hidden),
        ]
    }

    assert {name: (m["duration_minutes"], m["cost_cents"]) for name, m in marks.items()} == {
        "duration": (25, None),
        "fixed": (None, 800),
        "per_mark": (None, 1500),
        "no_default": (None, None),
        "hidden": (None, None),
    }


def test_toggle_body_is_strict(client, ana):
    habit = created(client, ana)

    extra = toggle(client, ana, habit["id"], note="oi")
    naive = toggle(client, ana, habit["id"], marked_at="2026-03-25T12:00:00")
    missing = client.post(
        f"/habits/{habit['id']}/toggle", json={"marked_at": iso(NOW)}, headers=ana.headers
    )

    assert (extra.status_code, extra.json()) == (422, invalid("note"))
    assert (naive.status_code, naive.json()) == (422, invalid("marked_at"))
    assert (missing.status_code, missing.json()) == (422, invalid("day_start"))


def test_toggle_on_multi_mark_habit_is_refused(client, ana, db_session):
    habit = created(client, ana, **MULTI)

    response = toggle(client, ana, habit["id"])

    assert response.status_code == 409
    assert response.json() == MODE_MISMATCH
    assert stored_marks(db_session, habit["id"]) == []


# --- datas ---


@pytest.mark.parametrize(("ahead", "status"), [(30, 201), (60, 201), (61, 422), (120, 422)])
def test_marked_at_in_the_future(client, ana, db_session, ahead, status):
    habit = created(client, ana, **MULTI)

    response = add(client, ana, habit["id"], marked_at=iso(NOW + timedelta(seconds=ahead)))

    assert response.status_code == status
    if status == 422:
        assert response.json() == invalid("marked_at")
        assert stored_marks(db_session, habit["id"]) == []


@pytest.mark.parametrize(("ahead", "status"), [(30, 200), (120, 422)])
def test_toggle_marked_at_in_the_future(client, ana, ahead, status):
    habit = created(client, ana)

    response = toggle(client, ana, habit["id"], marked_at=iso(NOW + timedelta(seconds=ahead)))

    assert response.status_code == status


def test_tomorrow_cannot_be_marked(client, ana):
    habit = created(client, ana)

    response = toggle(client, ana, habit["id"], TODAY + timedelta(days=1))

    assert response.status_code == 422
    assert response.json() == invalid("marked_at")


def test_days_before_the_habit_creation_can_be_marked(client, ana, db_session):
    habit = created(client, ana)
    multi = created(client, ana, **MULTI)
    long_ago = TODAY - timedelta(days=400)

    assert toggled(client, ana, habit["id"], long_ago)["marked"] is True
    assert added(client, ana, multi["id"], marked_at=iso(noon(long_ago)))

    assert [m.marked_at for m in stored_marks(db_session, habit["id"])] == [noon(long_ago)]


@pytest.mark.parametrize(
    "value",
    [
        "1899-12-31T23:59:59Z",
        "0001-01-01T00:00:00+05:00",
        "9999-12-31T23:59:59-05:00",
        "2026-03-25T12:00:00",
        "ontem",
        1774450800,
    ],
)
def test_invalid_marked_at(client, ana, value):
    habit = created(client, ana, **MULTI)

    response = add(client, ana, habit["id"], marked_at=value)

    assert response.status_code == 422
    assert response.json() == invalid("marked_at")


def test_marked_at_with_offset_is_stored_in_utc(client, ana, db_session):
    habit = created(client, ana, **MULTI)

    mark = added(client, ana, habit["id"], marked_at="2026-03-25T09:30:00-03:00")

    assert mark["marked_at"] == "2026-03-25T12:30:00Z"
    assert stored_marks(db_session, habit["id"])[0].marked_at == datetime(
        2026, 3, 25, 12, 30, tzinfo=UTC
    )


# --- várias por dia ---


def test_multi_mark_creates_marks(client, ana, db_session):
    habit = created(
        client,
        ana,
        **MULTI,
        notes_enabled=True,
        duration_enabled=True,
        duration_minutes=15,
        cost_enabled=True,
        cost_level="mark",
        cost_cents=500,
    )

    first = added(client, ana, habit["id"])
    second = added(
        client,
        ana,
        habit["id"],
        note="  primeira\nlinha\tok  ",
        duration_minutes=40,
        cost_cents=0,
    )

    assert (first["duration_minutes"], first["cost_cents"], first["note"]) == (15, 500, None)
    assert (second["duration_minutes"], second["cost_cents"]) == (40, 0)
    assert second["note"] == "primeira\nlinha\tok"
    assert second["author"] == {"id": ana.user.id, "email": "ana@example.com"}
    assert len(stored_marks(db_session, habit["id"])) == 2
    created_events = events(db_session, AuditEvent.MARK_CREATED)
    assert [entry.details["has_note"] for entry in created_events] == [False, True]
    # O texto da observação nunca vai para a auditoria
    assert "primeira" not in str([entry.details for entry in created_events])


def test_marks_on_toggle_habit_is_refused(client, ana, db_session):
    habit = created(client, ana)

    response = add(client, ana, habit["id"])

    assert response.status_code == 409
    assert response.json() == MODE_MISMATCH
    assert stored_marks(db_session, habit["id"]) == []


@pytest.mark.parametrize(
    ("config", "fields", "field"),
    [
        ({}, {"note": "oi"}, "note"),
        ({"notes_enabled": True}, {"note": "a" * 141}, "note"),
        ({"notes_enabled": True}, {"note": "a\x00b"}, "note"),
        ({"notes_enabled": True}, {"note": "a\rb"}, "note"),
        ({"notes_enabled": True}, {"note": "a‮b"}, "note"),
        ({"notes_enabled": True}, {"note": 5}, "note"),
        ({}, {"duration_minutes": 10}, "duration_minutes"),
        (
            {"duration_enabled": True, "duration_minutes": 5},
            {"duration_minutes": 0},
            "duration_minutes",
        ),
        (
            {"duration_enabled": True, "duration_minutes": 5},
            {"duration_minutes": 1441},
            "duration_minutes",
        ),
        (
            {"duration_enabled": True, "duration_minutes": 5},
            {"duration_minutes": "10"},
            "duration_minutes",
        ),
        ({}, {"cost_cents": 100}, "cost_cents"),
        ({"cost_enabled": True, "cost_cents": 800}, {"cost_cents": 100}, "cost_cents"),
        ({"cost_enabled": True, "cost_level": "mark"}, {"cost_cents": -1}, "cost_cents"),
        ({"cost_enabled": True, "cost_level": "mark"}, {"cost_cents": 10**12 + 1}, "cost_cents"),
        ({}, {"author_id": 1}, "author_id"),
    ],
)
def test_multi_mark_invalid_fields(client, ana, db_session, config, fields, field):
    habit = created(client, ana, **MULTI, **config)

    response = add(client, ana, habit["id"], **fields)

    assert response.status_code == 422
    assert response.json() == invalid(field)
    assert stored_marks(db_session, habit["id"]) == []


def test_note_length_follows_the_config(make_app_client, ana):
    client = make_app_client(max_note_length=5)
    habit = created(client, ana, **MULTI, notes_enabled=True)

    assert added(client, ana, habit["id"], note=" " + "é" * 5 + " ")["note"] == "ééééé"
    assert add(client, ana, habit["id"], note="a" * 6).json() == invalid("note")


def test_note_with_140_characters_is_accepted(client, ana):
    habit = created(client, ana, **MULTI, notes_enabled=True)

    assert added(client, ana, habit["id"], note="a" * 140)["note"] == "a" * 140


def test_empty_note_is_null(client, ana):
    habit = created(client, ana, **MULTI, notes_enabled=True)

    assert added(client, ana, habit["id"], note="   ")["note"] is None


def test_daily_limit_in_the_marker_timezone(make_app_client, ana, db_session):
    client = make_app_client(max_marks_per_day=3)
    habit = created(client, ana, **MULTI)
    # 25/03 em São Paulo: de 03:00 UTC do dia 25 a 03:00 UTC do dia 26
    start = day_of(TODAY)[0]
    model = stored(db_session, habit["id"])
    save(db_session, new_mark(model, start), new_mark(model, start - timedelta(microseconds=1)))
    added(client, ana, habit["id"])
    added(client, ana, habit["id"], marked_at=iso(start + timedelta(hours=1)))

    refused = add(client, ana, habit["id"])

    assert refused.status_code == 409
    assert refused.json() == LIMIT_REACHED
    # O dia anterior (que tem 1) ainda aceita
    assert added(client, ana, habit["id"], marked_at=iso(start - timedelta(hours=1)))
    assert len(stored_marks(db_session, habit["id"])) == 5
    assert len(events(db_session, AuditEvent.MARK_CREATED)) == 3


def test_daily_limit_counts_every_member(make_app_client, ana, bia, db_session):
    client = make_app_client(max_marks_per_day=2)
    habit = created(client, ana, **MULTI)
    share(db_session, habit["id"], bia, "editor")
    added(client, ana, habit["id"])
    added(client, bia, habit["id"])

    assert add(client, bia, habit["id"]).json() == LIMIT_REACHED


def test_daily_limit_uses_the_timezone_of_who_marks(make_app_client, ana, make_account, db_session):
    client = make_app_client(max_marks_per_day=1)
    lisbon = make_account("lisboa@example.com", timezone="Europe/Lisbon")
    habit = created(client, ana, multi_mark=True)
    share(db_session, habit["id"], lisbon, "editor")
    # 02:00 UTC do dia 25: dia 24 em São Paulo, dia 25 em Lisboa
    early = datetime(2026, 3, 25, 2, 0, tzinfo=UTC)
    added(client, ana, habit["id"], marked_at=iso(early))

    # Lisboa: o dia 25 (de 00:00 UTC a 00:00 UTC do dia 26) já tem a de 02:00
    assert add(client, lisbon, habit["id"]).json() == LIMIT_REACHED
    # São Paulo: o dia 25 começa às 03:00 UTC e está vazio
    assert added(client, ana, habit["id"])


# --- custo ---


def test_changing_the_habit_cost_keeps_old_marks(client, ana, db_session):
    fixed = created(client, ana, cost_enabled=True, cost_level="habit", cost_cents=800)
    per_mark = created(client, ana, **MULTI, cost_enabled=True, cost_level="mark", cost_cents=300)
    old_fixed = toggled(client, ana, fixed["id"], TODAY - timedelta(days=1))["mark"]
    old_per_mark = added(client, ana, per_mark["id"])

    for habit in (fixed, per_mark):
        response = client.patch(
            f"/habits/{habit['id']}", json={"cost_cents": 1000}, headers=ana.headers
        )
        assert response.status_code == 200

    new_fixed = toggled(client, ana, fixed["id"])["mark"]
    new_per_mark = added(client, ana, per_mark["id"])
    assert [m.cost_cents for m in stored_marks(db_session, fixed["id"])] == [800, 1000]
    assert [m.cost_cents for m in stored_marks(db_session, per_mark["id"])] == [300, 1000]
    assert (old_fixed["cost_cents"], new_fixed["cost_cents"]) == (800, 1000)
    assert (old_per_mark["cost_cents"], new_per_mark["cost_cents"]) == (300, 1000)


# --- status e papéis ---


def test_archived_habit_refuses_every_write(client, ana, db_session):
    toggle_habit = created(client, ana)
    multi = created(client, ana, **MULTI)
    toggled(client, ana, toggle_habit["id"])
    mark = added(client, ana, multi["id"])
    for habit in (toggle_habit, multi):
        client.post(f"/habits/{habit['id']}/archive", headers=ana.headers)
    before = event_names(db_session)

    responses = [
        toggle(client, ana, toggle_habit["id"]),
        add(client, ana, multi["id"]),
        patch(client, ana, multi["id"], mark["id"], {}),
        remove(client, ana, multi["id"], mark["id"]),
    ]

    assert [(r.status_code, r.json()) for r in responses] == [(409, ARCHIVED)] * 4
    assert len(stored_marks(db_session, toggle_habit["id"])) == 1
    assert len(stored_marks(db_session, multi["id"])) == 1
    assert event_names(db_session) == before
    # Continua legível
    assert listed(client, ana, multi["id"]).json()["marks"][0]["id"] == mark["id"]


def test_paused_habit_accepts_marks(client, ana):
    habit = created(client, ana)
    multi = created(client, ana, **MULTI)
    for item in (habit, multi):
        client.post(f"/habits/{item['id']}/pause", headers=ana.headers)

    assert toggled(client, ana, habit["id"])["marked"] is True
    assert added(client, ana, multi["id"])


def test_editor_writes_marks_of_anyone(client, ana, bia, db_session):
    habit = created(client, ana, **MULTI, notes_enabled=True)
    share(db_session, habit["id"], bia, "editor")
    toggle_habit = created(client, ana)
    share(db_session, toggle_habit["id"], bia, "editor")
    by_ana = added(client, ana, habit["id"])
    toggled(client, ana, toggle_habit["id"])

    edited = patch(client, bia, habit["id"], by_ana["id"], {"note": "da Bia"})
    by_bia = added(client, bia, habit["id"])
    unmarked = toggled(client, bia, toggle_habit["id"])

    assert edited.status_code == 200
    assert edited.json()["note"] == "da Bia"
    # Editar não muda o autor
    assert edited.json()["author"] == {"id": ana.user.id, "email": "ana@example.com"}
    assert by_bia["author"] == {"id": bia.user.id, "email": "bia@example.com"}
    assert unmarked["marked"] is False
    # O dono apaga a da editora e a editora apaga a do dono
    assert remove(client, ana, habit["id"], by_bia["id"]).status_code == 204
    assert remove(client, bia, habit["id"], by_ana["id"]).status_code == 204
    assert stored_marks(db_session, habit["id"]) == []


def test_viewer_gets_403_on_every_write(client, ana, bia, db_session):
    toggle_habit = created(client, ana)
    multi = created(client, ana, **MULTI)
    for habit in (toggle_habit, multi):
        share(db_session, habit["id"], bia, "viewer")
    mark = added(client, ana, multi["id"])
    before = event_names(db_session)

    responses = [
        toggle(client, bia, toggle_habit["id"]),
        add(client, bia, multi["id"]),
        patch(client, bia, multi["id"], mark["id"], {}),
        remove(client, bia, multi["id"], mark["id"]),
        # Mesmo num id de marcação que não existe: o papel vem antes
        remove(client, bia, multi["id"], mark["id"] + 1000),
    ]

    assert [(r.status_code, r.json()) for r in responses] == [(403, FORBIDDEN)] * 5
    assert len(stored_marks(db_session, multi["id"])) == 1
    assert stored_marks(db_session, toggle_habit["id"]) == []
    assert event_names(db_session) == before
    # Mas lê
    assert listed(client, bia, multi["id"]).json()["marks"][0]["id"] == mark["id"]


def test_viewer_gets_403_even_on_archived_habit(client, ana, bia, db_session):
    habit = created(client, ana)
    share(db_session, habit["id"], bia, "viewer")
    client.post(f"/habits/{habit['id']}/archive", headers=ana.headers)

    assert toggle(client, bia, habit["id"]).json() == FORBIDDEN


def test_stranger_gets_404_everywhere(client, ana, bia):
    toggle_habit = created(client, ana)
    multi = created(client, ana, **MULTI)
    mark = added(client, ana, multi["id"])

    responses = [
        toggle(client, bia, toggle_habit["id"]),
        add(client, bia, multi["id"]),
        listed(client, bia, multi["id"]),
        patch(client, bia, multi["id"], mark["id"], {}),
        remove(client, bia, multi["id"], mark["id"]),
        # Hábito que não existe
        toggle(client, ana, 999_999),
        listed(client, ana, MAX_ID),
    ]

    assert [(r.status_code, r.json()) for r in responses] == [(404, NOT_FOUND)] * 7


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/habits/1/toggle"),
        ("POST", "/habits/1/marks"),
        ("GET", "/habits/1/marks"),
        ("PATCH", "/habits/1/marks/1"),
        ("DELETE", "/habits/1/marks/1"),
    ],
)
def test_without_session_is_401(client, method, path):
    response = client.request(method, path, json={})

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "field": None}


@pytest.mark.parametrize("mark_id", [0, -1, MAX_ID + 1, "x"])
def test_invalid_mark_id_is_422(client, ana, mark_id):
    habit = created(client, ana, **MULTI)

    response = remove(client, ana, habit["id"], mark_id)

    assert response.status_code == 422
    assert response.json() == invalid("mark_id")


# --- editar ---


def test_patch_changes_note_duration_and_cost(client, ana, db_session, clock):
    habit = created(
        client,
        ana,
        **MULTI,
        notes_enabled=True,
        duration_enabled=True,
        duration_minutes=15,
        cost_enabled=True,
        cost_level="mark",
        cost_cents=500,
    )
    mark = added(client, ana, habit["id"], note="antes")
    clock.shift(timedelta(minutes=5))

    response = patch(
        client,
        ana,
        habit["id"],
        mark["id"],
        {"note": "depois", "duration_minutes": 45, "cost_cents": 1200},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["note"], body["duration_minutes"], body["cost_cents"]) == ("depois", 45, 1200)
    assert body["marked_at"] == mark["marked_at"]
    assert body["created_at"] == mark["created_at"]
    assert body["updated_at"] == "2026-03-25T15:05:00Z"
    [entry] = events(db_session, AuditEvent.MARK_UPDATED)
    assert (entry.user_id, entry.habit_id, entry.ip) == (ana.user.id, habit["id"], IP)
    assert entry.details == {
        "mark_id": mark["id"],
        "changes": [
            {"field": "note"},
            {"field": "duration_minutes", "old": 15, "new": 45},
            {"field": "cost_cents", "old": 500, "new": 1200},
        ],
    }


def test_patch_with_marked_at_does_not_change_the_date(client, ana, db_session):
    habit = created(client, ana, **MULTI, notes_enabled=True)
    mark = added(client, ana, habit["id"])
    other_day = iso(NOW - timedelta(days=3))

    responses = [
        patch(client, ana, habit["id"], mark["id"], {"marked_at": other_day}),
        patch(client, ana, habit["id"], mark["id"], {"note": "x", "marked_at": other_day}),
        patch(client, ana, habit["id"], mark["id"], {"created_at": other_day}),
    ]

    assert [r.status_code for r in responses] == [422] * 3
    assert responses[0].json() == invalid("marked_at")
    [row] = stored_marks(db_session, habit["id"])
    assert (row.marked_at, row.note) == (NOW, None)
    assert events(db_session, AuditEvent.MARK_UPDATED) == []


def test_patch_without_changes_records_nothing(client, ana, db_session):
    habit = created(client, ana, **MULTI, notes_enabled=True)
    mark = added(client, ana, habit["id"], note="igual")

    for body in ({}, {"note": "igual"}, {"note": "  igual "}):
        response = patch(client, ana, habit["id"], mark["id"], body)
        assert response.json() == mark

    assert events(db_session, AuditEvent.MARK_UPDATED) == []


def test_patch_null_clears_note_and_cost(client, ana, db_session):
    habit = created(client, ana, **MULTI, notes_enabled=True, cost_enabled=True, cost_level="mark")
    mark = added(client, ana, habit["id"], note="nota", cost_cents=100)

    response = patch(client, ana, habit["id"], mark["id"], {"note": None, "cost_cents": None})

    assert (response.json()["note"], response.json()["cost_cents"]) == (None, None)
    [entry] = events(db_session, AuditEvent.MARK_UPDATED)
    assert entry.details["changes"] == [
        {"field": "note"},
        {"field": "cost_cents", "old": 100, "new": None},
    ]


@pytest.mark.parametrize(
    ("config", "body", "field"),
    [
        ({}, {"note": "oi"}, "note"),
        # Desligado: nem apagar
        ({}, {"note": None}, "note"),
        ({"notes_enabled": True}, {"note": "a" * 141}, "note"),
        ({}, {"duration_minutes": 10}, "duration_minutes"),
        (
            {"duration_enabled": True, "duration_minutes": 5},
            {"duration_minutes": None},
            "duration_minutes",
        ),
        (
            {"duration_enabled": True, "duration_minutes": 5},
            {"duration_minutes": 0},
            "duration_minutes",
        ),
        ({}, {"cost_cents": 10}, "cost_cents"),
        # Nível hábito: o custo é o fixo do hábito
        ({"cost_enabled": True, "cost_cents": 800}, {"cost_cents": 10}, "cost_cents"),
        ({"cost_enabled": True, "cost_cents": 800}, {"cost_cents": None}, "cost_cents"),
    ],
)
def test_patch_invalid_fields(client, ana, db_session, config, body, field):
    habit = created(client, ana, **MULTI, **config)
    mark = added(client, ana, habit["id"])

    response = patch(client, ana, habit["id"], mark["id"], body)

    assert response.status_code == 422
    assert response.json() == invalid(field)
    assert events(db_session, AuditEvent.MARK_UPDATED) == []


def test_feature_turned_off_hides_nothing_already_stored(client, ana):
    habit = created(client, ana, **MULTI, notes_enabled=True)
    mark = added(client, ana, habit["id"], note="guardada")
    client.patch(f"/habits/{habit['id']}", json={"notes_enabled": False}, headers=ana.headers)

    # A observação continua guardada (o front a esconde) e não dá para mexer nela
    assert listed(client, ana, habit["id"]).json()["marks"][0]["note"] == "guardada"
    assert patch(client, ana, habit["id"], mark["id"], {"note": "x"}).json() == invalid("note")


def test_patch_and_delete_unknown_or_foreign_mark_is_404(client, ana):
    habit = created(client, ana, **MULTI)
    other = created(client, ana, **MULTI)
    foreign = added(client, ana, other["id"])

    responses = [
        patch(client, ana, habit["id"], foreign["id"], {}),
        remove(client, ana, habit["id"], foreign["id"]),
        patch(client, ana, habit["id"], MAX_ID, {}),
        remove(client, ana, habit["id"], MAX_ID),
    ]

    assert [(r.status_code, r.json()) for r in responses] == [(404, NOT_FOUND)] * 4


# --- apagar ---


def test_delete_mark(client, ana, db_session):
    habit = created(client, ana, **MULTI)
    kept = added(client, ana, habit["id"])
    gone = added(client, ana, habit["id"])

    response = remove(client, ana, habit["id"], gone["id"])

    assert response.status_code == 204
    assert [m.id for m in stored_marks(db_session, habit["id"])] == [kept["id"]]
    [entry] = events(db_session, AuditEvent.MARK_DELETED)
    assert (entry.user_id, entry.habit_id, entry.ip) == (ana.user.id, habit["id"], IP)
    assert entry.details["mark_id"] == gone["id"]
    assert remove(client, ana, habit["id"], gone["id"]).status_code == 404


def test_audit_is_recorded_on_create_update_and_delete(client, ana, db_session):
    habit = created(client, ana, **MULTI, notes_enabled=True)
    toggle_habit = created(client, ana)
    mark = added(client, ana, habit["id"])
    patch(client, ana, habit["id"], mark["id"], {"note": "x"})
    remove(client, ana, habit["id"], mark["id"])
    toggled(client, ana, toggle_habit["id"])
    toggled(client, ana, toggle_habit["id"])

    assert event_names(db_session) == [
        "mark_created",
        "mark_created",
        "mark_updated",
        "mark_deleted",
        "mark_deleted",
    ]


# --- autor removido ---


def test_deleted_author_shows_as_removed_user(client, ana, bia, db_session):
    habit = created(client, ana, **MULTI, notes_enabled=True)
    share(db_session, habit["id"], bia, "editor")
    mark = added(client, bia, habit["id"])
    with write_transaction(db_session):
        db_session.execute(delete(User).where(User.id == bia.user.id))

    [listed_mark] = listed(client, ana, habit["id"]).json()["marks"]
    edited = patch(client, ana, habit["id"], mark["id"], {"note": "ainda aqui"})

    assert listed_mark["author"] is None
    assert edited.json()["author"] is None
    [row] = stored_marks(db_session, habit["id"])
    assert row.user_id is None
    assert remove(client, ana, habit["id"], mark["id"]).status_code == 204


# --- listar ---


def test_list_returns_the_range_in_order(client, ana, bia, db_session):
    habit = created(client, ana, **MULTI)
    share(db_session, habit["id"], bia, "viewer")
    start = NOW - timedelta(days=2)
    end = NOW
    times = [start - timedelta(seconds=1), start, NOW - timedelta(days=1), end]
    model = stored(db_session, habit["id"])
    save(db_session, *[new_mark(model, when, user_id=ana.user.id) for when in reversed(times)])

    response = listed(client, bia, habit["id"], **{"from": iso(start), "to": iso(end)})

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    assert [m["marked_at"] for m in body["marks"]] == [
        "2026-03-23T15:00:00Z",
        "2026-03-24T15:00:00Z",
    ]
    assert body["marks"][0]["author"] == {"id": ana.user.id, "email": "ana@example.com"}


def test_list_pages_with_cursor(client, ana, db_session):
    habit = created(client, ana, **MULTI)
    model = stored(db_session, habit["id"])
    # Mesmo instante em três: o id desempata
    times = [NOW - timedelta(hours=3), NOW - timedelta(hours=2)] + [NOW - timedelta(hours=1)] * 3
    save(db_session, *[new_mark(model, when) for when in times])
    expected = [(m.marked_at, m.id) for m in stored_marks(db_session, habit["id"])]

    seen = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = listed(client, ana, habit["id"], **params).json()
        seen += [(datetime.fromisoformat(m["marked_at"]), m["id"]) for m in body["marks"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert seen == expected
    assert pages == 3


def test_list_last_full_page_has_no_cursor(client, ana):
    habit = created(client, ana, **MULTI)
    added(client, ana, habit["id"])
    added(client, ana, habit["id"])

    body = listed(client, ana, habit["id"], limit=2).json()

    assert len(body["marks"]) == 2
    assert body["next_cursor"] is None


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"from": iso(NOW), "to": iso(NOW)}, "to"),
        ({"from": iso(NOW), "to": iso(NOW - timedelta(days=1))}, "to"),
        ({"from": iso(NOW), "to": iso(NOW + timedelta(days=367, seconds=1))}, "to"),
        ({"from": "2026-03-25T00:00:00"}, "from"),
        ({"to": "amanhã"}, "to"),
        ({"cursor": "x"}, "cursor"),
        ({"cursor": "1.2.3"}, "cursor"),
        ({"cursor": f"1.{MAX_ID + 1}"}, "cursor"),
        ({"cursor": f"{10**18 - 1}.1"}, "cursor"),
        ({"cursor": f"-{10**18 - 1}.1"}, "cursor"),
        ({"cursor": "1" * 65}, "cursor"),
        # Dígito arábico (U+0661), que o int() do Python aceitaria
        ({"cursor": chr(0x661) + ".1"}, "cursor"),
        ({"limit": 0}, "limit"),
        ({"limit": 1001}, "limit"),
    ],
)
def test_list_invalid_params(client, ana, params, field):
    habit = created(client, ana, **MULTI)

    response = listed(client, ana, habit["id"], **params)

    assert response.status_code == 422
    assert response.json() == invalid(field)


def test_list_without_range_is_422(client, ana):
    habit = created(client, ana, **MULTI)

    response = client.get(f"/habits/{habit['id']}/marks", headers=ana.headers)

    assert response.status_code == 422
    assert response.json() == invalid("from")


def test_list_accepts_367_days(client, ana):
    habit = created(client, ana, **MULTI)
    added(client, ana, habit["id"])

    response = listed(
        client, ana, habit["id"], **{"from": iso(NOW), "to": iso(NOW + timedelta(days=367))}
    )

    assert len(response.json()["marks"]) == 1


def test_cursor_round_trip():
    for marked_at in (NOW, datetime(1900, 1, 1, tzinfo=UTC), NOW + timedelta(microseconds=7)):
        mark = Mark(id=MAX_ID, marked_at=marked_at)
        assert decode_cursor(encode_cursor(mark)) == (marked_at, MAX_ID)


def test_day_bounds():
    assert day_bounds(datetime(2026, 3, 25, 2, 59, tzinfo=UTC), SP) == (
        datetime(2026, 3, 24, 3, tzinfo=UTC),
        datetime(2026, 3, 25, 3, tzinfo=UTC),
    )
    # Horário de verão que começava à meia-noite (São Paulo, 2018): o dia começa à 01:00
    start, end = day_bounds(datetime(2018, 11, 4, 15, tzinfo=UTC), SP)
    assert (start, end - start) == (datetime(2018, 11, 4, 3, tzinfo=UTC), timedelta(hours=23))


# --- concorrência (threads de verdade, banco em arquivo) ---


def run_parallel(engine, calls: int, action: Callable[[Any, int], Any]) -> list[Any]:
    factory = create_session_factory(engine)
    barrier = threading.Barrier(calls)

    def task(index: int) -> Any:
        with factory() as session:
            barrier.wait()
            try:
                return action(session, index)
            except ApiError as error:
                return error.code.value

    with ThreadPoolExecutor(max_workers=calls) as executor:
        return list(executor.map(task, range(calls)))


def toggle_today(session, user_id: int, habit_id: int):
    start, end = day_of(TODAY)
    return service.toggle_mark(
        session,
        user_id=user_id,
        habit_id=habit_id,
        day_start=start,
        day_end=end,
        marked_at=NOW,
        ip=None,
    )


def saved_habit(db_session, owner: Account, *shared: Account, **fields) -> int:
    """Id de um hábito novo, compartilhado como editor com `shared`.

    As threads recebem só ids: os objetos do ORM são da sessão do teste, que não é thread-safe.
    """
    habit = new_habit(owner.user, **fields)
    save(db_session, habit)
    for account in shared:
        share(db_session, habit.id, account, "editor")
    return habit.id


def test_double_click_on_toggle_never_duplicates(engine, db_session, ana):
    habit_id = saved_habit(db_session, ana)
    user_id = ana.user.id

    results = run_parallel(engine, 2, lambda session, _: toggle_today(session, user_id, habit_id))

    # Um clique marcou, o outro viu a marcação e desmarcou
    assert sorted(result is None for result in results) == [False, True]
    assert stored_marks(db_session, habit_id) == []
    assert len(events(db_session, AuditEvent.MARK_CREATED)) == 1
    assert len(events(db_session, AuditEvent.MARK_DELETED)) == 1


@pytest.mark.parametrize("calls", [2, 3, 6])
def test_members_toggling_together_leave_one_mark_or_none(engine, db_session, ana, bia, calls):
    habit_id = saved_habit(db_session, ana, bia)
    users = (ana.user.id, bia.user.id)

    results = run_parallel(
        engine, calls, lambda session, i: toggle_today(session, users[i % 2], habit_id)
    )

    marked = sum(result is not None for result in results)
    # Os cliques se alternam: marca, desmarca, marca... Nunca duas no dia
    assert marked == (calls + 1) // 2
    assert len(stored_marks(db_session, habit_id)) == calls % 2


def test_parallel_marks_never_pass_the_daily_limit(engine, db_session, make_settings, ana, bia):
    settings = make_settings(max_marks_per_day=3)
    habit_id = saved_habit(db_session, ana, bia, multi_mark=True, goal_count=10)
    save(db_session, Mark(habit_id=habit_id, marked_at=NOW - timedelta(hours=1)))
    users = (ana.user.id, bia.user.id)

    def create(session, index: int) -> str:
        service.create_mark(
            session,
            settings,
            user_id=users[index % 2],
            timezone="America/Sao_Paulo",
            habit_id=habit_id,
            marked_at=NOW - timedelta(minutes=index),
            note=None,
            duration_minutes=None,
            cost_cents=None,
            ip=None,
        )
        return "created"

    results = run_parallel(engine, 8, create)

    assert sorted(results) == ["created"] * 2 + ["mark_limit_reached"] * 6
    assert len(stored_marks(db_session, habit_id)) == 3
    assert len(events(db_session, AuditEvent.MARK_CREATED)) == 2


def test_toggle_and_archive_in_parallel(engine, db_session, ana):
    # Arquivar e marcar ao mesmo tempo: ou a marcação entra antes, ou é recusada
    habit_id = saved_habit(db_session, ana)
    user_id = ana.user.id

    def action(session, index: int) -> str:
        if index == 0:
            habits_service.archive_habit(session, user_id=user_id, habit_id=habit_id, ip=None)
            return "archived"
        toggle_today(session, user_id, habit_id)
        return "marked"

    results = run_parallel(engine, 2, action)

    assert results[0] == "archived"
    assert results[1] in ("marked", "habit_archived")
    assert len(stored_marks(db_session, habit_id)) == (results[1] == "marked")
