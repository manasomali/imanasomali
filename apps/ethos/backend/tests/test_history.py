"""API de histórico: `GET /history` (ETH-25)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from sqlalchemy import delete, select, text

from app.audit import AUTH_EVENTS, AuditEvent
from app.db import write_transaction
from app.habits.access import MAX_ID
from app.history.service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    OWNER_ONLY_EVENTS,
    PUBLIC_DETAILS,
    HistoryEvent,
    public_details,
)
from app.main import create_app
from app.models import AuditLog, Habit, HabitMember, User
from tests.factories import new_habit, new_member, save
from tests.habit_helpers import Account, created, invalid

# Quarta-feira, 12:00 em São Paulo
NOW = datetime(2026, 3, 25, 15, 0, tzinfo=UTC)
MULTI = {"multi_mark": True, "goal_count": 10}


@pytest.fixture(autouse=True)
def clock() -> Iterator[time_machine.Traveller]:
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def client(settings, database, make_client, outbox):
    return make_client(create_app(settings, mail_backend=outbox))


@pytest.fixture
def ana(make_account) -> Account:
    return make_account("ana@example.com")


@pytest.fixture
def bia(make_account) -> Account:
    return make_account("bia@example.com")


@pytest.fixture
def caio(make_account) -> Account:
    return make_account("caio@example.com")


@pytest.fixture
def dani(make_account) -> Account:
    return make_account("dani@example.com")


def habit(db_session, owner: Account, **fields) -> Habit:
    model = new_habit(owner.user, **fields)
    save(db_session, model)
    return model


def log(
    db_session,
    model: Habit | None,
    event: AuditEvent | str,
    *,
    by: Account | None,
    at: datetime = NOW,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> int:
    """Grava um evento direto no `audit_log`, com a data `at`; devolve o id."""
    entry = AuditLog(
        event=str(event),
        user_id=None if by is None else by.user.id,
        habit_id=None if model is None else model.id,
        created_at=at,
        details=details or {},
        ip=ip,
    )
    save(db_session, entry)
    return entry.id


def history(client, account: Account, **params: Any):
    return client.get("/history", params=params, headers=account.headers)


def ok(client, account: Account, **params: Any) -> dict:
    response = history(client, account, **params)
    assert response.status_code == 200, response.json()
    return response.json()


def ids(body: dict) -> list[int]:
    return [item["id"] for item in body["events"]]


def all_pages(client, account: Account, **params: Any) -> list[int]:
    seen: list[int] = []
    cursor = None
    while True:
        query = params if cursor is None else params | {"cursor": cursor}
        body = ok(client, account, **query)
        seen += ids(body)
        cursor = body["next_cursor"]
        if cursor is None:
            return seen


# --- Acesso -----------------------------------------------------------------------------------


def test_requires_session(client):
    response = client.get("/history")

    assert (response.status_code, response.json()) == (
        401,
        {"error": "unauthorized", "field": None},
    )


def test_without_events(client, ana):
    assert ok(client, ana) == {"events": [], "next_cursor": None}


def test_user_does_not_see_events_of_other_peoples_habits(client, db_session, ana, dani):
    mine = habit(db_session, ana)
    theirs = habit(db_session, dani)
    own_event = log(db_session, mine, AuditEvent.HABIT_CREATED, by=ana)
    other_event = log(db_session, theirs, AuditEvent.HABIT_CREATED, by=dani)

    assert ids(ok(client, ana)) == [own_event]
    assert ids(ok(client, dani)) == [other_event]
    # Filtrar pelo hábito alheio (ou um que não existe) dá a lista vazia, sem revelar nada
    assert ok(client, dani, habit_id=mine.id) == {"events": [], "next_cursor": None}
    assert ok(client, dani, habit_id=mine.id + 1000) == {"events": [], "next_cursor": None}
    # Nem pela marcação ou pelo autor
    mark_event = log(db_session, mine, AuditEvent.MARK_CREATED, by=ana, details={"mark_id": 9})
    assert ids(ok(client, dani, mark_id=9)) == []
    assert ids(ok(client, dani, user_id=ana.user.id)) == []
    assert ids(ok(client, ana, mark_id=9)) == [mark_event]


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_members_see_the_habit_history(client, db_session, ana, bia, role):
    model = habit(db_session, ana)
    save(db_session, new_member(model, bia.user, role))
    # Inclusive o que aconteceu antes de a pessoa entrar
    before = log(db_session, model, AuditEvent.HABIT_CREATED, by=ana, at=NOW - timedelta(days=30))
    after = log(db_session, model, AuditEvent.MARK_CREATED, by=bia)

    assert ids(ok(client, bia)) == [after, before]


def test_access_is_checked_now(client, db_session, ana, bia):
    model = habit(db_session, ana)
    save(db_session, new_member(model, bia.user, "editor"))
    event = log(db_session, model, AuditEvent.MARK_CREATED, by=bia)
    assert ids(ok(client, bia)) == [event]

    with write_transaction(db_session):
        db_session.execute(delete(HabitMember).where(HabitMember.user_id == bia.user.id))

    # Quem saiu deixa de ver, inclusive o que ele mesmo fez
    assert ids(ok(client, bia)) == []
    assert ids(ok(client, ana)) == [event]


def test_archived_habit_history_is_visible(client, db_session, ana, bia):
    model = habit(db_session, ana, status="archived", archived_at=NOW)
    save(db_session, new_member(model, bia.user, "viewer"))
    event = log(db_session, model, AuditEvent.HABIT_ARCHIVED, by=ana)

    assert ids(ok(client, ana)) == [event]
    assert ids(ok(client, bia)) == [event]


@pytest.mark.parametrize(
    "event",
    [
        *sorted(AUTH_EVENTS),
        AuditEvent.TERMS_ACCEPTED,
        AuditEvent.PROFILE_UPDATED,
        AuditEvent.ACCOUNT_DELETED,
        AuditEvent.ALERT_UPDATED,
        AuditEvent.ADMIN_CREATED,
        AuditEvent.ADMIN_VIEWED_HABITS,
        AuditEvent.USER_BLOCKED,
        AuditEvent.EMAIL_CHANGED,
        AuditEvent.BANNER_CREATED,
    ],
)
def test_other_events_never_appear(client, db_session, ana, event):
    model = habit(db_session, ana)
    # Mesmo com o habit_id preenchido (eles não têm), o evento não é do histórico
    log(db_session, model, event, by=ana, details={"x": 1})

    assert ids(ok(client, ana)) == []
    response = history(client, ana, event=str(event))
    assert (response.status_code, response.json()) == (422, invalid("event.0"))


def test_deleted_habit_leaves_no_history(client, db_session, ana):
    model = habit(db_session, ana)
    log(db_session, model, AuditEvent.HABIT_CREATED, by=ana)

    response = client.delete(f"/habits/{model.id}", headers=ana.headers)

    assert response.status_code == 204
    # O habit_deleted fica (habit_id nulo), mas não é de hábito nenhum que se possa ver
    assert ids(ok(client, ana)) == []


@pytest.mark.parametrize(
    ("event", "member_sees"),
    [
        (AuditEvent.INVITE_CREATED, False),
        (AuditEvent.INVITE_CANCELED, False),
        (AuditEvent.INVITE_DECLINED, False),
        (AuditEvent.INVITE_ACCEPTED, True),
    ],
)
@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_invites_are_the_owners(client, db_session, ana, bia, caio, event, member_sees, role):
    model = habit(db_session, ana)
    save(db_session, new_member(model, bia.user, role))
    entry = log(db_session, model, event, by=caio, details={"invite_id": 3, "role": "viewer"})

    assert ids(ok(client, ana)) == [entry]
    assert ids(ok(client, bia)) == ([entry] if member_sees else [])
    # O filtro por evento não fura a regra
    assert ids(ok(client, bia, event=str(event))) == ([entry] if member_sees else [])


def test_owner_only_events_are_invites_that_did_not_become_members():
    assert {str(event) for event in OWNER_ONLY_EVENTS} == {
        "invite_created",
        "invite_canceled",
        "invite_declined",
    }


# --- Resposta ---------------------------------------------------------------------------------


def test_entry_format(client, db_session, ana):
    model = habit(db_session, ana, name="Meditar", code="MED")
    details = {
        "mark_id": 5,
        "author_id": ana.user.id,
        "marked_at": "2026-03-25T12:00:00+00:00",
        "duration_minutes": 20,
        "cost_cents": None,
        "has_note": True,
    }
    event = log(
        db_session, model, AuditEvent.MARK_CREATED, by=ana, details=details, ip="203.0.113.9"
    )

    response = history(client, ana)

    assert response.json() == {
        "events": [
            {
                "id": event,
                "event": "mark_created",
                "created_at": "2026-03-25T15:00:00Z",
                "habit": {"id": model.id, "label": "MED"},
                "author": {"id": ana.user.id, "email": "ana@example.com"},
                "details": details,
            }
        ],
        "next_cursor": None,
    }
    # O IP nunca sai
    assert "203.0.113.9" not in response.text
    assert '"ip"' not in response.text


def test_label_is_the_name_without_code(client, db_session, ana):
    model = habit(db_session, ana, name="Ler")
    log(db_session, model, AuditEvent.HABIT_CREATED, by=ana)

    [entry] = ok(client, ana)["events"]

    assert entry["habit"] == {"id": model.id, "label": "Ler"}


def test_event_without_author_is_removed_user(client, db_session, ana):
    model = habit(db_session, ana)
    log(db_session, model, AuditEvent.MARK_DELETED, by=None)

    [entry] = ok(client, ana)["events"]

    assert entry["author"] is None


def test_deleted_account_becomes_removed_user(client, db_session, ana, bia):
    model = habit(db_session, ana)
    save(db_session, new_member(model, bia.user, "editor"))
    log(db_session, model, AuditEvent.MARK_CREATED, by=bia, details={"mark_id": 1})
    log(db_session, model, AuditEvent.MEMBER_LEFT, by=bia, details={"role": "editor"})

    # ON DELETE SET NULL: a autoria some com a conta (a exclusão de conta é da ETH-27)
    with write_transaction(db_session):
        db_session.execute(delete(User).where(User.id == bia.user.id))

    body = ok(client, ana)
    assert [entry["author"] for entry in body["events"]] == [None, None]
    assert ok(client, ana, user_id=bia.user.id)["events"] == []


def test_details_keep_only_the_public_keys(client, db_session, ana):
    model = habit(db_session, ana)
    details = {
        "mark_id": 5,
        "email": "fulano@example.com",
        "changes": [
            {"field": "note"},
            {"field": "cost_cents", "old": 100, "new": 200, "extra": "x"},
        ],
    }
    log(db_session, model, AuditEvent.MARK_UPDATED, by=ana, details=details)

    [entry] = ok(client, ana)["events"]

    assert entry["details"] == {
        "mark_id": 5,
        "changes": [{"field": "note"}, {"field": "cost_cents", "old": 100, "new": 200}],
    }
    assert "fulano" not in str(entry)


@pytest.mark.parametrize(
    ("event", "details", "public"),
    [
        (HistoryEvent.HABIT_CREATED, {"name": "x"}, {}),
        (HistoryEvent.HABIT_PAUSED, None, {}),
        (HistoryEvent.HABIT_UPDATED, ["changes"], {}),
        (HistoryEvent.HABIT_UPDATED, {"changes": "name"}, {}),
        (HistoryEvent.HABIT_UPDATED, {"changes": [1, {"old": 1}, {"field": 2}]}, {"changes": []}),
        (
            HistoryEvent.HABIT_UPDATED,
            {"changes": [{"field": "reward", "old": None, "new": {"x": 1}}]},
            {"changes": [{"field": "reward", "old": None}]},
        ),
        (HistoryEvent.MARK_CREATED, {"mark_id": [5], "has_note": False}, {"has_note": False}),
        (
            HistoryEvent.MEMBER_REMOVED,
            {"member_id": 4, "role": "viewer", "ip": "1"},
            {"member_id": 4, "role": "viewer"},
        ),
        (
            HistoryEvent.INVITE_CREATED,
            {"invite_id": 1, "role": "editor", "email": "a@b.c"},
            {"invite_id": 1, "role": "editor"},
        ),
    ],
)
def test_public_details(event, details, public):
    assert public_details(event, details) == public


def test_every_history_event_is_an_audit_event_with_public_details():
    assert {str(event) for event in HistoryEvent} <= {str(event) for event in AuditEvent}
    assert not {str(event) for event in HistoryEvent} & {str(event) for event in AUTH_EVENTS}
    assert set(PUBLIC_DETAILS) == set(HistoryEvent)
    assert "habit_deleted" not in set(HistoryEvent)
    assert "alert_updated" not in set(HistoryEvent)


def test_real_events_through_the_api(client, ana, bia):
    # Os eventos gravados pelos services saem com os detalhes que cada um grava
    model = created(client, ana, **MULTI, notes_enabled=True)
    habit_id = model["id"]
    response = client.patch(f"/habits/{habit_id}", json={"name": "Novo"}, headers=ana.headers)
    assert response.status_code == 200
    invite = client.post(
        f"/habits/{habit_id}/invites",
        json={"email": "bia@example.com", "role": "editor"},
        headers=ana.headers,
    )
    assert invite.status_code == 202
    [received] = client.get("/invites", headers=bia.headers).json()["invites"]
    assert client.post(f"/invites/{received['id']}/accept", headers=bia.headers).status_code == 200
    mark = client.post(
        f"/habits/{habit_id}/marks",
        json={"marked_at": NOW.isoformat(), "note": "texto"},
        headers=bia.headers,
    ).json()
    response = client.patch(
        f"/habits/{habit_id}/marks/{mark['id']}", json={"note": "outro"}, headers=ana.headers
    )
    assert response.status_code == 200

    body = ok(client, ana)

    # Tudo no mesmo instante (relógio parado): o desempate é o id, do mais novo ao mais antigo
    assert [(entry["event"], entry["author"]["email"]) for entry in body["events"]] == [
        ("mark_updated", "ana@example.com"),
        ("mark_created", "bia@example.com"),
        ("invite_accepted", "bia@example.com"),
        ("invite_created", "ana@example.com"),
        ("habit_updated", "ana@example.com"),
        ("habit_created", "ana@example.com"),
    ]
    details = [entry["details"] for entry in body["events"]]
    assert details[0] == {"mark_id": mark["id"], "changes": [{"field": "note"}]}
    assert details[1] == {
        "mark_id": mark["id"],
        "author_id": bia.user.id,
        "marked_at": "2026-03-25T15:00:00+00:00",
        "duration_minutes": None,
        "cost_cents": None,
        "has_note": True,
    }
    assert details[2] == {"invite_id": received["id"], "role": "editor"}
    assert details[3] == {"invite_id": received["id"], "role": "editor"}
    assert details[4] == {"changes": [{"field": "name", "old": "Exercício", "new": "Novo"}]}
    assert details[5] == {}
    # A observação nunca aparece
    assert "texto" not in str(body)
    assert "outro" not in str(body)
    # A editora vê tudo menos o convite (que é do dono)
    assert [entry["event"] for entry in ok(client, bia)["events"]] == [
        "mark_updated",
        "mark_created",
        "invite_accepted",
        "habit_updated",
        "habit_created",
    ]
    # Detalhes da marcação: quem criou, quem editou e quando
    response = client.delete(f"/habits/{habit_id}/marks/{mark['id']}", headers=bia.headers)
    assert response.status_code == 204
    of_mark = ok(client, bia, mark_id=mark["id"])["events"]
    assert [(e["event"], e["author"]["email"], e["created_at"]) for e in of_mark] == [
        ("mark_deleted", "bia@example.com", "2026-03-25T15:00:00Z"),
        ("mark_updated", "ana@example.com", "2026-03-25T15:00:00Z"),
        ("mark_created", "bia@example.com", "2026-03-25T15:00:00Z"),
    ]


# --- Filtros ----------------------------------------------------------------------------------


@pytest.fixture
def scene(db_session, ana, bia, caio) -> dict[str, Any]:
    """Dois hábitos da ana com a bia editora nos dois e o caio viewer no primeiro, e eventos
    em datas escolhidas para os filtros de período (horários em UTC; São Paulo é UTC-3)."""
    run = habit(db_session, ana, name="Correr")
    read = habit(db_session, ana, name="Ler")
    save(
        db_session,
        new_member(run, bia.user, "editor"),
        new_member(read, bia.user, "editor"),
        new_member(run, caio.user, "viewer"),
    )

    def mark(model, by, mark_id, event, at):
        return log(db_session, model, event, by=by, at=at, details={"mark_id": mark_id})

    events = {
        # 2026-03-01 09:00 em SP
        "run_created": log(
            db_session,
            run,
            AuditEvent.HABIT_CREATED,
            by=ana,
            at=datetime(2026, 3, 1, 12, tzinfo=UTC),
        ),
        # 2026-03-10 21:30 em SP (já é dia 11 em UTC)
        "run_mark_1": mark(
            run, bia, 1, AuditEvent.MARK_CREATED, datetime(2026, 3, 11, 0, 30, tzinfo=UTC)
        ),
        "read_mark_2": mark(
            read, ana, 2, AuditEvent.MARK_CREATED, datetime(2026, 3, 12, 12, tzinfo=UTC)
        ),
        "run_mark_1_updated": mark(
            run, ana, 1, AuditEvent.MARK_UPDATED, datetime(2026, 3, 15, 12, tzinfo=UTC)
        ),
        # 2026-03-20 23:59 em SP
        "run_mark_1_deleted": mark(
            run, bia, 1, AuditEvent.MARK_DELETED, datetime(2026, 3, 21, 2, 59, tzinfo=UTC)
        ),
        # 2026-03-21 00:00 em SP
        "read_paused": log(
            db_session,
            read,
            AuditEvent.HABIT_PAUSED,
            by=bia,
            at=datetime(2026, 3, 21, 3, tzinfo=UTC),
        ),
    }
    return {"run": run.id, "read": read.id, "events": events}


def named(scene: dict[str, Any], *names: str) -> list[int]:
    # Do mais novo ao mais antigo, como a API devolve
    return sorted((scene["events"][name] for name in names), reverse=True)


def test_without_filters_everything_in_order(client, scene, ana, bia, caio):
    every = named(scene, *scene["events"])

    assert ids(ok(client, ana)) == every
    assert ids(ok(client, bia)) == every
    assert ids(ok(client, caio)) == named(
        scene, "run_created", "run_mark_1", "run_mark_1_updated", "run_mark_1_deleted"
    )


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"habit_id": "read"}, ["read_mark_2", "read_paused"]),
        ({"user_id": "bia"}, ["run_mark_1", "run_mark_1_deleted", "read_paused"]),
        ({"event": ["mark_created"]}, ["run_mark_1", "read_mark_2"]),
        (
            {"event": ["mark_created", "habit_paused"]},
            ["run_mark_1", "read_mark_2", "read_paused"],
        ),
        ({"mark_id": 1}, ["run_mark_1", "run_mark_1_updated", "run_mark_1_deleted"]),
        # Datas locais (São Paulo), inclusivas
        ({"from": "2026-03-21"}, ["read_paused"]),
        (
            {"to": "2026-03-20"},
            [
                "run_created",
                "run_mark_1",
                "read_mark_2",
                "run_mark_1_updated",
                "run_mark_1_deleted",
            ],
        ),
        ({"from": "2026-03-10", "to": "2026-03-10"}, ["run_mark_1"]),
        ({"from": "2026-03-11", "to": "2026-03-15"}, ["read_mark_2", "run_mark_1_updated"]),
        # Combinados
        ({"habit_id": "run", "user_id": "bia"}, ["run_mark_1", "run_mark_1_deleted"]),
        ({"habit_id": "run", "event": ["mark_created", "mark_deleted"], "user_id": "ana"}, []),
        ({"mark_id": 1, "user_id": "ana"}, ["run_mark_1_updated"]),
        ({"mark_id": 1, "event": ["mark_deleted"], "to": "2026-03-20"}, ["run_mark_1_deleted"]),
        ({"mark_id": 2, "habit_id": "run"}, []),
        (
            {"user_id": "bia", "from": "2026-03-11", "to": "2026-03-21", "habit_id": "run"},
            ["run_mark_1_deleted"],
        ),
        (
            {
                "habit_id": "read",
                "user_id": "ana",
                "event": ["mark_created"],
                "mark_id": 2,
                "from": "2026-03-12",
                "to": "2026-03-12",
            },
            ["read_mark_2"],
        ),
    ],
)
def test_filters(client, scene, ana, bia, params, expected):
    accounts = {"ana": ana.user.id, "bia": bia.user.id}
    query = dict(params)
    if "habit_id" in query:
        query["habit_id"] = scene[query["habit_id"]]
    if "user_id" in query:
        query["user_id"] = accounts[query["user_id"]]

    assert ids(ok(client, ana, **query)) == named(scene, *expected)


def test_dates_follow_the_users_timezone(client, scene, make_account, db_session):
    # Em Tóquio (UTC+9), 2026-03-11 00:30 UTC já é dia 11, e 2026-03-21 02:59 UTC é dia 21
    tokyo = make_account("eva@example.com", timezone="Asia/Tokyo")
    for habit_id in (scene["run"], scene["read"]):
        save(db_session, HabitMember(habit_id=habit_id, user_id=tokyo.user.id, role="viewer"))

    assert ids(ok(client, tokyo, **{"from": "2026-03-11", "to": "2026-03-11"})) == named(
        scene, "run_mark_1"
    )
    assert ids(ok(client, tokyo, **{"from": "2026-03-21"})) == named(
        scene, "run_mark_1_deleted", "read_paused"
    )


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"from": "2026-03-21", "to": "2026-03-20"}, "to"),
        ({"from": "2026-3-1"}, "from"),
        ({"to": "2026-03-01T00:00:00"}, "to"),
        ({"from": "1899-12-31"}, "from"),
        ({"habit_id": 0}, "habit_id"),
        ({"habit_id": MAX_ID + 1}, "habit_id"),
        ({"user_id": "x"}, "user_id"),
        ({"mark_id": -1}, "mark_id"),
        ({"event": "habit_deleted"}, "event.0"),
        ({"event": ["mark_created"] * (len(HistoryEvent) + 1)}, "event"),
        ({"limit": 0}, "limit"),
        ({"limit": MAX_PAGE_SIZE + 1}, "limit"),
        ({"cursor": "abc"}, "cursor"),
        ({"cursor": "1." + "9" * 19}, "cursor"),
        ({"cursor": "-" + "9" * 18 + ".1"}, "cursor"),
        ({"cursor": "1" * 65}, "cursor"),
    ],
)
def test_invalid_params(client, ana, params, field):
    response = history(client, ana, **params)

    assert (response.status_code, response.json()) == (422, invalid(field))


def test_extreme_dates_and_ids(client, scene, ana):
    assert ids(ok(client, ana, **{"from": "1900-01-01", "to": "2999-12-31"})) == named(
        scene, *scene["events"]
    )
    assert ok(client, ana, habit_id=MAX_ID, user_id=MAX_ID, mark_id=MAX_ID)["events"] == []


# --- Paginação --------------------------------------------------------------------------------


def test_default_and_maximum_page_size(client, db_session, ana):
    model = habit(db_session, ana)
    save(
        db_session,
        *(
            AuditLog(
                event="habit_paused",
                user_id=ana.user.id,
                habit_id=model.id,
                created_at=NOW - timedelta(minutes=index),
            )
            for index in range(MAX_PAGE_SIZE + 1)
        ),
    )

    first = ok(client, ana)
    assert len(first["events"]) == DEFAULT_PAGE_SIZE == 50
    assert first["next_cursor"] is not None
    biggest = ok(client, ana, limit=MAX_PAGE_SIZE)
    assert len(biggest["events"]) == MAX_PAGE_SIZE == 200
    last = ok(client, ana, limit=MAX_PAGE_SIZE, cursor=biggest["next_cursor"])
    assert len(last["events"]) == 1
    assert last["next_cursor"] is None


def test_exact_page_has_no_next_cursor(client, db_session, ana):
    model = habit(db_session, ana)
    for _ in range(3):
        log(db_session, model, AuditEvent.HABIT_PAUSED, by=ana)

    assert ok(client, ana, limit=3)["next_cursor"] is None


def test_pages_neither_repeat_nor_skip(client, db_session, ana):
    model = habit(db_session, ana)
    # Vários eventos no mesmo instante: o desempate é o id
    rows = []
    for hour in (3, 0, 1, 0, 3, 2, 3, 1, 0, 4, 3):
        at = NOW - timedelta(hours=hour)
        rows.append((at, log(db_session, model, AuditEvent.HABIT_PAUSED, by=ana, at=at)))
    expected = [row_id for _at, row_id in sorted(rows, reverse=True)]

    assert all_pages(client, ana, limit=3) == expected
    assert all_pages(client, ana, limit=1) == expected


def test_new_events_between_pages_do_not_shift_the_next_ones(client, db_session, ana, clock):
    model = habit(db_session, ana)
    original = [
        log(db_session, model, AuditEvent.HABIT_PAUSED, by=ana, at=NOW - timedelta(minutes=m))
        for m in (0, 0, 1, 2, 2, 3, 4)
    ]

    first = ok(client, ana, limit=3)
    seen = ids(first)
    # Chegam eventos novos: no mesmo instante do mais novo (id maior) e depois
    log(db_session, model, AuditEvent.HABIT_RESUMED, by=ana, at=NOW)
    clock.shift(timedelta(seconds=5))
    response = client.post(f"/habits/{model.id}/pause", headers=ana.headers)
    assert response.status_code == 200
    seen += all_pages(client, ana, limit=3, cursor=first["next_cursor"])

    assert sorted(seen) == sorted(original)
    assert len(seen) == len(set(seen))


def test_pages_with_filters(client, scene, ana):
    # O cursor só diz onde parou: com os mesmos filtros, as páginas juntas dão a lista inteira
    pages = all_pages(client, ana, limit=1, habit_id=scene["run"])

    assert pages == named(
        scene, "run_created", "run_mark_1", "run_mark_1_updated", "run_mark_1_deleted"
    )


# --- Desempenho -------------------------------------------------------------------------------


def test_no_n_plus_one(client, db_session, ana, bia, caio, selects):
    def add(amount: int) -> None:
        for _ in range(amount):
            model = habit(db_session, ana)
            for account in (bia, caio):
                save(db_session, new_member(model, account.user, "editor"))
                log(db_session, model, AuditEvent.MARK_CREATED, by=account, details={"mark_id": 1})
            log(db_session, model, AuditEvent.HABIT_CREATED, by=None)

    add(1)
    selects()
    assert len(ok(client, ana)["events"]) == 3
    few = selects()

    add(20)
    selects()
    assert len(ok(client, ana)["events"]) == DEFAULT_PAGE_SIZE
    many = selects()

    assert few == many
    # A sessão do usuário e a página (hábitos e autores no JOIN)
    assert many == 2


def test_mark_filter_uses_the_index(engine):
    # `GET /history?mark_id=` acha os eventos da marcação pelo índice da coluna calculada,
    # sem rodar json_extract em cada evento
    with engine.connect() as connection:
        plan = connection.execute(
            text("EXPLAIN QUERY PLAN SELECT id FROM audit_log WHERE mark_id = :mark_id"),
            {"mark_id": 1},
        ).all()

    assert any("ix_audit_log_mark_id" in row[3] for row in plan)


def test_mark_id_column_follows_details(db_session, ana):
    model = habit(db_session, ana)
    with_mark = log(db_session, model, AuditEvent.MARK_CREATED, by=ana, details={"mark_id": 7})
    without = log(db_session, model, AuditEvent.HABIT_CREATED, by=ana)

    db_session.rollback()
    values = dict(db_session.execute(select(AuditLog.id, AuditLog.mark_id)).all())

    assert values == {with_mark: 7, without: None}
