"""API de hábitos: criar, listar, ver, editar e apagar (ETH-20)."""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import time_machine
from sqlalchemy import select

from app import score
from app.audit import AuditEvent
from app.db import create_session_factory
from app.errors import ApiError
from app.habits import service
from app.habits.access import MAX_ID, HabitAccess, HabitRole
from app.habits.scoring import load_marks, load_pauses, to_score_habit
from app.main import create_app
from app.models import AuditLog, Habit, HabitMember, HabitPause, Mark
from tests.factories import count, new_habit, new_mark, new_member, new_pause, save
from tests.habit_helpers import (
    FORBIDDEN,
    NOT_FOUND,
    VALID,
    Account,
    create,
    created,
    events,
    invalid,
    share,
    stored,
)

IP = "203.0.113.7"
# Quarta-feira
NOW = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock() -> Iterator[time_machine.Traveller]:
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def client(settings, database, make_client, outbox):
    return make_client(create_app(settings, mail_backend=outbox), client=(IP, 50000))


@pytest.fixture
def ana(make_account) -> Account:
    return make_account("ana@example.com")


@pytest.fixture
def bia(make_account) -> Account:
    return make_account("bia@example.com", locale="en")


@pytest.fixture
def caio(make_account) -> Account:
    return make_account("caio@example.com")


# --- criar ---


def test_create_with_defaults(client, ana, db_session):
    response = create(client, ana)

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": body["id"],
        "role": "owner",
        "name": "Exercício",
        "code": None,
        "label": "Exercício",
        "description": None,
        "color": "teal",
        "goal_type": "min",
        "goal_count": 3,
        "goal_period": "week",
        "multi_mark": False,
        "duration_enabled": False,
        "duration_minutes": None,
        "notes_enabled": False,
        "score_enabled": False,
        "score_threshold": 70,
        "reward": None,
        "punishment": None,
        "cost_enabled": False,
        "cost_level": "habit",
        "cost_cents": None,
        "cost_limit_cents": None,
        "cost_limit_period": None,
        "status": "active",
        "archived_at": None,
        "created_at": "2026-03-25T12:00:00Z",
        "updated_at": "2026-03-25T12:00:00Z",
    }
    habit = stored(db_session, body["id"])
    assert habit.owner_id == ana.user.id
    [entry] = events(db_session, AuditEvent.HABIT_CREATED)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        ana.user.id,
        body["id"],
        IP,
        {},
    )


def test_create_with_every_field(client, ana, db_session):
    fields = {
        "name": "  Apostar  ",
        "code": " ab1 ",
        "description": "Linha 1\nLinha\t2",
        "color": "violet",
        "goal_type": "max",
        "goal_count": 0,
        "goal_period": "month",
        "multi_mark": True,
        "duration_enabled": True,
        "duration_minutes": 40,
        "notes_enabled": True,
        "score_enabled": True,
        "score_threshold": 80,
        "reward": "Pizza",
        "punishment": "Correr 50 min",
        "cost_enabled": True,
        "cost_level": "mark",
        "cost_cents": 0,
        "cost_limit_cents": 10_000,
        "cost_limit_period": "year",
    }

    body = created(client, ana, **fields)

    expected = fields | {"name": "Apostar", "code": "AB1", "label": "AB1"}
    assert {key: body[key] for key in expected} == expected
    habit = stored(db_session, body["id"])
    assert (habit.name, habit.code, habit.cost_limit_period) == ("Apostar", "AB1", "year")


@pytest.mark.parametrize(
    ("code", "saved"),
    [("ab1", "AB1"), ("1", "1"), ("abcd", "ABCD"), ("Z9", "Z9"), ("", None), ("  ", None)],
)
def test_code_saved_in_upper_case(client, ana, code, saved):
    body = created(client, ana, code=code)
    assert body["code"] == saved
    assert body["label"] == (saved or "Exercício")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("name", "   "),
        ("name", "x" * 61),
        ("name", None),
        ("name", 123),
        ("name", "a\nb"),
        ("name", "a\x00b"),
        ("name", "a\u202eb"),
        ("reward", "a\u2066b"),
        ("description", "a\u202bb"),
        ("code", "ab-1"),
        ("code", "abcde"),
        ("code", "a b"),
        ("code", "ção"),
        # Dígitos de largura total (outro alfabeto)
        ("code", "\uff11\uff12"),
        ("code", "a\nb"),
        ("code", 12),
        ("description", "x" * 501),
        ("description", "a\x1bb"),
        ("description", "a\rb"),
        ("color", "magenta"),
        ("color", "Teal"),
        ("color", None),
        # Cor própria: só "#" e 6 dígitos hexadecimais
        ("color", "#fff"),
        ("color", "#gggggg"),
        ("color", "white"),
        ("color", "0a1b2c"),
        ("color", "#0a1b2c0"),
        ("color", "#0a1b2c\n"),
        ("color", " #0a1b2c"),
        # Zero de largura total (outro alfabeto)
        ("color", "#\uff10a1b2c"),
        ("color", ""),
        ("color", 0x0A1B2C),
        ("goal_type", "at_least"),
        ("goal_count", -1),
        ("goal_count", "3"),
        ("goal_count", 3.0),
        ("goal_count", True),
        ("goal_count", 10**30),
        ("goal_period", "day"),
        ("multi_mark", "true"),
        ("multi_mark", 1),
        ("multi_mark", None),
        ("duration_enabled", "yes"),
        ("duration_minutes", 0),
        ("duration_minutes", 1441),
        ("notes_enabled", 0),
        ("score_enabled", "false"),
        ("score_threshold", 0),
        ("score_threshold", 101),
        ("score_threshold", None),
        ("cost_enabled", "1"),
        ("cost_level", "day"),
        ("cost_cents", -1),
        ("cost_cents", 10**12 + 1),
        ("cost_cents", 1.5),
        ("cost_limit_cents", -1),
        ("cost_limit_period", "day"),
        ("status", "archived"),
        ("owner_id", 2),
    ],
)
def test_create_refuses_invalid_field(client, ana, db_session, field, value):
    response = create(client, ana, **{field: value})

    assert response.status_code == 422
    assert response.json() == invalid(field)
    assert count(db_session, Habit) == 0


@pytest.mark.parametrize("field", ["name", "color", "goal_type", "goal_count", "goal_period"])
def test_create_requires_field(client, ana, field):
    body = {key: value for key, value in VALID.items() if key != field}
    response = client.post("/habits", json=body, headers=ana.headers)

    assert response.status_code == 422
    assert response.json() == invalid(field)


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "x" * 60},
        {"description": "x" * 500},
        {"description": "x" * 499 + "\n"},
        {"score_enabled": True, "reward": "x" * 140, "punishment": "y" * 140},
        {"score_enabled": True, "score_threshold": 1},
        {"score_enabled": True, "score_threshold": 100},
        {"duration_enabled": True, "duration_minutes": 1440},
        {"cost_enabled": True, "cost_cents": 10**12},
        {"cost_enabled": True, "cost_cents": 0, "cost_limit_cents": 0, "cost_limit_period": "week"},
        {"cost_enabled": True, "cost_level": "mark"},
    ],
)
def test_create_accepts_limits(client, ana, fields):
    body = created(client, ana, **fields)
    for key, value in fields.items():
        # Espaços nas pontas saem
        assert body[key] == (value.strip() if isinstance(value, str) else value)


# Corredora: emoji com junção (ZWJ) e seletor de variação, 4 caracteres
RUNNER = "".join(map(chr, (0x1F3C3, 0x200D, 0x2640, 0xFE0F)))
# Fora do plano básico: 12 caracteres cada no JSON da auditoria
ASTRAL = chr(0x1F355)


def test_emoji_with_joiner_is_accepted(client, ana):
    body = created(client, ana, name=f"{RUNNER} Correr", description=f"{RUNNER}\n{ASTRAL}")
    assert body["name"] == f"{RUNNER} Correr"


def test_update_every_text_at_the_maximum_fits_the_audit(client, ana, db_session):
    habit = created(client, ana, score_enabled=True)
    texts = {
        "name": ASTRAL * 60,
        "description": ASTRAL * 500,
        "reward": ASTRAL * 140,
        "punishment": ASTRAL * 140,
    }

    first = patch(client, ana, habit["id"], **texts)
    second = patch(client, ana, habit["id"], **{key: value[:-1] for key, value in texts.items()})

    assert first.status_code == second.status_code == 200
    entries = events(db_session, AuditEvent.HABIT_UPDATED)
    assert entries[1].details["changes"] == [
        {"field": "name", "old": ASTRAL * 60, "new": ASTRAL * 59},
        # A descrição vai sem os valores
        {"field": "description"},
        {"field": "reward", "old": ASTRAL * 140, "new": ASTRAL * 139},
        {"field": "punishment", "old": ASTRAL * 140, "new": ASTRAL * 139},
    ]


def test_length_is_counted_without_outer_spaces(client, ana):
    body = created(client, ana, name=" " + "x" * 60 + " ")
    assert body["name"] == "x" * 60


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        # N >= 1 em min e exact
        ({"goal_type": "min", "goal_count": 0}, "goal_count"),
        ({"goal_type": "exact", "goal_count": 0}, "goal_count"),
        # Toggle: no máximo os dias do período
        ({"goal_period": "week", "goal_count": 8}, "goal_count"),
        ({"goal_period": "month", "goal_count": 29}, "goal_count"),
        ({"goal_period": "year", "goal_count": 366}, "goal_count"),
        ({"goal_type": "max", "goal_period": "week", "goal_count": 8}, "goal_count"),
        # Várias por dia: MAX_MARKS_PER_DAY (999) x dias
        ({"multi_mark": True, "goal_period": "week", "goal_count": 999 * 7 + 1}, "goal_count"),
        ({"multi_mark": True, "goal_period": "year", "goal_count": 999 * 365 + 1}, "goal_count"),
        # Duração ligada precisa dos minutos
        ({"duration_enabled": True}, "duration_minutes"),
        # Recompensa e punição só com pontuação ligada
        ({"reward": "Pizza"}, "reward"),
        ({"punishment": "Correr"}, "punishment"),
        ({"score_enabled": False, "reward": "Pizza"}, "reward"),
        # Custo no nível hábito precisa do valor
        ({"cost_enabled": True}, "cost_cents"),
        ({"cost_enabled": True, "cost_level": "habit"}, "cost_cents"),
        # Limite e período vêm juntos
        ({"cost_limit_cents": 100}, "cost_limit_period"),
        ({"cost_limit_period": "month"}, "cost_limit_cents"),
    ],
)
def test_create_refuses_invalid_combination(client, ana, db_session, fields, field):
    response = create(client, ana, **fields)

    assert response.status_code == 422
    assert response.json() == invalid(field)
    assert count(db_session, Habit) == 0


@pytest.mark.parametrize(
    "fields",
    [
        {"goal_type": "max", "goal_count": 0},
        {"goal_type": "exact", "goal_count": 1},
        {"goal_period": "week", "goal_count": 7},
        {"goal_period": "month", "goal_count": 28},
        {"goal_period": "year", "goal_count": 365},
        {"multi_mark": True, "goal_period": "week", "goal_count": 999 * 7},
        {"multi_mark": True, "goal_period": "month", "goal_count": 999 * 28},
        # Valores de recursos desligados ficam guardados
        {"duration_minutes": 30},
        {"cost_cents": 800, "cost_limit_cents": 5000, "cost_limit_period": "month"},
        {"score_enabled": True, "reward": "Pizza"},
    ],
)
def test_create_accepts_valid_combination(client, ana, fields):
    body = created(client, ana, **fields)
    assert {key: body[key] for key in fields} == fields


def test_goal_ceiling_follows_max_marks_per_day(make_settings, database, make_client, ana):
    settings = make_settings(database_path=database, max_marks_per_day=2)
    client = make_client(create_app(settings))

    ok = create(client, ana, multi_mark=True, goal_period="week", goal_count=14)
    too_many = create(client, ana, multi_mark=True, goal_period="week", goal_count=15)

    assert ok.status_code == 201
    assert too_many.status_code == 422
    assert too_many.json() == invalid("goal_count")


# --- limite de hábitos ---


def test_eleventh_habit_refused(client, ana, db_session):
    for _ in range(10):
        created(client, ana)

    response = create(client, ana)

    assert response.status_code == 409
    assert response.json() == {"error": "habit_limit_reached", "field": None}
    assert count(db_session, Habit) == 10
    assert len(events(db_session, AuditEvent.HABIT_CREATED)) == 10


def test_limit_counts_paused_but_not_archived(client, ana, bia, db_session):
    save(
        db_session,
        *[new_habit(ana.user) for _ in range(8)],
        new_habit(ana.user, status="paused"),
        *[new_habit(ana.user, status="archived", archived_at=NOW) for _ in range(3)],
    )
    # Hábito de outra pessoa compartilhado com a Ana conta só no limite da dona
    other = new_habit(bia.user)
    save(db_session, other)
    save(db_session, new_member(other, ana.user, "editor"))

    assert create(client, ana).status_code == 201
    assert create(client, ana).status_code == 409


def test_limit_is_per_owner(client, ana, bia, db_session):
    save(db_session, *[new_habit(ana.user) for _ in range(10)])

    assert create(client, ana).status_code == 409
    assert create(client, bia).status_code == 201


def test_limit_follows_config(make_settings, database, make_client, ana):
    settings = make_settings(database_path=database, max_habits_per_user=1)
    client = make_client(create_app(settings))

    assert create(client, ana).status_code == 201
    assert create(client, ana).status_code == 409


# --- listar ---


def test_list_owned_and_shared_with_role(client, ana, bia, caio, db_session):
    own = created(client, ana, name="Meu")
    shared_edit = created(client, bia, name="Da Bia, editor")
    shared_view = created(client, caio, name="Do Caio, viewer")
    created(client, bia, name="Da Bia, não compartilhado")
    share(db_session, shared_edit["id"], ana, "editor")
    share(db_session, shared_view["id"], ana, "viewer")

    response = client.get("/habits", headers=ana.headers)

    assert response.status_code == 200
    habits = response.json()["habits"]
    assert [(habit["id"], habit["role"], habit["name"]) for habit in habits] == [
        (own["id"], "owner", "Meu"),
        (shared_edit["id"], "editor", "Da Bia, editor"),
        (shared_view["id"], "viewer", "Do Caio, viewer"),
    ]
    # Todos os membros veem a configuração inteira
    assert habits[1] == shared_edit | {"role": "editor"}


def test_list_member_sees_own_role_only(client, ana, bia, caio, db_session):
    habit = created(client, ana)
    share(db_session, habit["id"], bia, "viewer")
    share(db_session, habit["id"], caio, "editor")

    roles = {
        account.user.email: client.get("/habits", headers=account.headers).json()["habits"]
        for account in (ana, bia, caio)
    }

    assert [habit["role"] for habit in roles["ana@example.com"]] == ["owner"]
    assert [habit["role"] for habit in roles["bia@example.com"]] == ["viewer"]
    assert [habit["role"] for habit in roles["caio@example.com"]] == ["editor"]


def test_list_empty(client, ana):
    response = client.get("/habits", headers=ana.headers)
    assert response.json() == {"habits": []}


def test_list_includes_paused_and_archived_only_on_their_own_list(client, ana, db_session):
    save(
        db_session,
        new_habit(ana.user, status="paused"),
        new_habit(ana.user, status="archived", archived_at=NOW),
    )

    habits = client.get("/habits", headers=ana.headers).json()["habits"]
    archived = client.get("/habits?archived=true", headers=ana.headers).json()["habits"]

    assert [habit["status"] for habit in habits] == ["paused"]
    assert [habit["status"] for habit in archived] == ["archived"]
    assert archived[0]["archived_at"] == "2026-03-25T12:00:00Z"


# --- ver ---


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_member_sees_habit(client, ana, bia, db_session, role):
    habit = created(client, ana, score_enabled=True, reward="Pizza")
    share(db_session, habit["id"], bia, role)

    response = client.get(f"/habits/{habit['id']}", headers=bia.headers)

    assert response.status_code == 200
    assert response.json() == habit | {"role": role}


def test_owner_sees_habit(client, ana):
    habit = created(client, ana)
    response = client.get(f"/habits/{habit['id']}", headers=ana.headers)
    assert response.json() == habit


def test_stranger_gets_same_404_as_missing_habit(client, ana, bia):
    habit = created(client, ana)

    hidden = client.get(f"/habits/{habit['id']}", headers=bia.headers)
    missing = client.get(f"/habits/{habit['id'] + 1}", headers=bia.headers)

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json() == NOT_FOUND
    assert hidden.headers["content-length"] == missing.headers["content-length"]


@pytest.mark.parametrize("habit_id", ["0", "-1", "abc", str(MAX_ID + 1), "1.5"])
def test_invalid_habit_id(client, ana, habit_id):
    response = client.get(f"/habits/{habit_id}", headers=ana.headers)
    assert response.status_code == 422
    assert response.json() == invalid("habit_id")


def test_largest_habit_id_is_404(client, ana):
    response = client.get(f"/habits/{MAX_ID}", headers=ana.headers)
    assert response.status_code == 404


# --- autenticação ---


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/habits"),
        ("POST", "/habits"),
        ("GET", "/habits/1"),
        ("PATCH", "/habits/1"),
        ("DELETE", "/habits/1"),
    ],
)
def test_requires_session(client, method, path):
    response = client.request(method, path, json=VALID)
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "field": None}


def test_requires_current_terms(client, make_account):
    old_terms = make_account("dani@example.com", terms_version="2026-01")
    response = client.get("/habits", headers=old_terms.headers)
    assert response.status_code == 403
    assert response.json() == {"error": "terms_not_accepted", "field": None}


# --- editar ---


def patch(client, account: Account, habit_id: int, **fields):
    return client.patch(f"/habits/{habit_id}", json=fields, headers=account.headers)


def test_owner_updates_and_audit_records_changes(client, ana, db_session, clock):
    habit = created(client, ana, code="ab")
    clock.shift(timedelta(hours=1))

    response = patch(
        client, ana, habit["id"], name="Corrida", code="cd", goal_count=3, color="blue"
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["code"], body["label"], body["color"]) == (
        "Corrida",
        "CD",
        "CD",
        "blue",
    )
    assert body["updated_at"] == "2026-03-25T13:00:00Z"
    assert body["created_at"] == habit["created_at"]
    [entry] = events(db_session, AuditEvent.HABIT_UPDATED)
    assert (entry.user_id, entry.habit_id, entry.ip) == (ana.user.id, habit["id"], IP)
    # goal_count não mudou (3 -> 3): não aparece
    assert entry.details == {
        "changes": [
            {"field": "name", "old": "Exercício", "new": "Corrida"},
            {"field": "code", "old": "AB", "new": "CD"},
            {"field": "color", "old": "teal", "new": "blue"},
        ]
    }
    assert stored(db_session, habit["id"]).name == "Corrida"


@pytest.mark.parametrize(("sent", "saved"), [("#0a1b2c", "#0a1b2c"), ("#0A1B2C", "#0a1b2c")])
def test_create_with_custom_color(client, ana, db_session, sent, saved):
    habit = created(client, ana, color=sent)

    assert habit["color"] == saved
    assert stored(db_session, habit["id"]).color == saved
    assert client.get(f"/habits/{habit['id']}", headers=ana.headers).json()["color"] == saved


def test_color_changes_between_palette_and_custom(client, ana, db_session, clock):
    habit = created(client, ana)

    to_custom = patch(client, ana, habit["id"], color="#FFFFFF")
    # O mesmo hex em maiúsculas não é mudança
    same = patch(client, ana, habit["id"], color="#ffffff")
    to_palette = patch(client, ana, habit["id"], color="pink")

    assert to_custom.json()["color"] == same.json()["color"] == "#ffffff"
    assert to_palette.json()["color"] == "pink"
    assert [entry.details for entry in events(db_session, AuditEvent.HABIT_UPDATED)] == [
        {"changes": [{"field": "color", "old": "teal", "new": "#ffffff"}]},
        {"changes": [{"field": "color", "old": "#ffffff", "new": "pink"}]},
    ]


def test_update_without_changes_records_nothing(client, ana, db_session, clock):
    habit = created(client, ana)
    clock.shift(timedelta(hours=1))

    empty = patch(client, ana, habit["id"])
    same = patch(client, ana, habit["id"], name="Exercício", goal_count=3)

    assert empty.status_code == same.status_code == 200
    assert empty.json() == same.json() == habit
    assert events(db_session, AuditEvent.HABIT_UPDATED) == []


def test_update_clears_optional_fields(client, ana, db_session):
    habit = created(
        client, ana, code="ab", description="d", cost_limit_cents=1, cost_limit_period="week"
    )

    body = patch(
        client,
        ana,
        habit["id"],
        code=None,
        description="  ",
        cost_limit_cents=None,
        cost_limit_period=None,
    ).json()

    assert (body["code"], body["label"], body["description"]) == (None, "Exercício", None)
    assert (body["cost_limit_cents"], body["cost_limit_period"]) == (None, None)
    [entry] = events(db_session, AuditEvent.HABIT_UPDATED)
    assert [change["field"] for change in entry.details["changes"]] == [
        "code",
        "description",
        "cost_limit_cents",
        "cost_limit_period",
    ]


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "color",
        "goal_type",
        "goal_count",
        "goal_period",
        "multi_mark",
        "duration_enabled",
        "notes_enabled",
        "score_enabled",
        "score_threshold",
        "cost_enabled",
        "cost_level",
    ],
)
def test_update_refuses_null_in_required_field(client, ana, field):
    habit = created(client, ana)
    response = patch(client, ana, habit["id"], **{field: None})
    assert response.status_code == 422
    assert response.json() == invalid(field)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("name", "x" * 61),
        ("code", "ab-1"),
        ("goal_count", -1),
        ("score_threshold", 101),
        ("multi_mark", "true"),
        ("status", "archived"),
        ("archived_at", None),
        ("id", 5),
    ],
)
def test_update_refuses_invalid_field(client, ana, db_session, field, value):
    habit = created(client, ana)

    response = patch(client, ana, habit["id"], **{field: value})

    assert response.status_code == 422
    assert response.json() == invalid(field)
    assert events(db_session, AuditEvent.HABIT_UPDATED) == []


@pytest.mark.parametrize(
    ("initial", "change", "field"),
    [
        # A combinação é conferida na configuração inteira depois da mudança
        ({"multi_mark": True, "goal_count": 20}, {"multi_mark": False}, "goal_count"),
        ({"goal_period": "month", "goal_count": 20}, {"goal_period": "week"}, "goal_count"),
        ({"goal_type": "max", "goal_count": 0}, {"goal_type": "min"}, "goal_count"),
        ({}, {"goal_count": 8}, "goal_count"),
        ({}, {"duration_enabled": True}, "duration_minutes"),
        (
            {"duration_enabled": True, "duration_minutes": 30},
            {"duration_minutes": None},
            "duration_minutes",
        ),
        ({}, {"reward": "Pizza"}, "reward"),
        ({}, {"punishment": "Correr"}, "punishment"),
        ({"score_enabled": True}, {"score_enabled": False, "reward": "Pizza"}, "reward"),
        ({}, {"cost_enabled": True}, "cost_cents"),
        ({"cost_enabled": True, "cost_level": "mark"}, {"cost_level": "habit"}, "cost_cents"),
        ({"cost_enabled": True, "cost_cents": 5}, {"cost_cents": None}, "cost_cents"),
        ({}, {"cost_limit_cents": 100}, "cost_limit_period"),
        (
            {"cost_limit_cents": 1, "cost_limit_period": "week"},
            {"cost_limit_cents": None},
            "cost_limit_cents",
        ),
    ],
)
def test_update_refuses_invalid_combination(client, ana, db_session, initial, change, field):
    habit = created(client, ana, **initial)

    response = patch(client, ana, habit["id"], **change)

    assert response.status_code == 422
    assert response.json() == invalid(field)
    # Nada mudou
    assert client.get(f"/habits/{habit['id']}", headers=ana.headers).json() == habit
    assert events(db_session, AuditEvent.HABIT_UPDATED) == []


def test_update_from_toggle_to_multi_mark_with_larger_goal(client, ana):
    habit = created(client, ana)

    body = patch(client, ana, habit["id"], multi_mark=True, goal_count=20).json()

    assert (body["multi_mark"], body["goal_count"]) == (True, 20)


def test_disabling_score_keeps_reward_and_punishment(client, ana, db_session):
    habit = created(
        client, ana, score_enabled=True, score_threshold=90, reward="Pizza", punishment="Correr"
    )

    off = patch(client, ana, habit["id"], score_enabled=False).json()
    # O front manda o formulário inteiro: o valor guardado, igual, não é recusado
    resent = patch(client, ana, habit["id"], reward="Pizza", punishment="Correr")
    cleared = patch(client, ana, habit["id"], punishment=None)
    on = patch(client, ana, habit["id"], score_enabled=True).json()

    assert (off["reward"], off["punishment"], off["score_threshold"]) == ("Pizza", "Correr", 90)
    assert resent.status_code == 200
    assert cleared.status_code == 200
    assert (on["score_enabled"], on["reward"], on["punishment"]) == (True, "Pizza", None)
    habit_row = stored(db_session, habit["id"])
    assert habit_row.reward == "Pizza"


def test_disabling_features_keeps_their_values(client, ana):
    habit = created(
        client,
        ana,
        duration_enabled=True,
        duration_minutes=40,
        notes_enabled=True,
        cost_enabled=True,
        cost_cents=800,
        cost_limit_cents=5000,
        cost_limit_period="month",
    )

    off = patch(
        client, ana, habit["id"], duration_enabled=False, notes_enabled=False, cost_enabled=False
    ).json()
    on = patch(
        client, ana, habit["id"], duration_enabled=True, notes_enabled=True, cost_enabled=True
    ).json()

    for body in (off, on):
        assert (body["duration_minutes"], body["cost_cents"], body["cost_limit_cents"]) == (
            40,
            800,
            5000,
        )
    assert on == habit | {"updated_at": on["updated_at"]}


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_member_cannot_update(client, ana, bia, db_session, role):
    habit = created(client, ana)
    share(db_session, habit["id"], bia, role)

    response = patch(client, bia, habit["id"], name="Outro")

    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert stored(db_session, habit["id"]).name == "Exercício"
    assert events(db_session, AuditEvent.HABIT_UPDATED) == []


def test_stranger_cannot_update(client, ana, bia, db_session):
    habit = created(client, ana)

    response = patch(client, bia, habit["id"], name="Outro")

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert stored(db_session, habit["id"]).name == "Exercício"


def test_update_missing_habit(client, ana):
    response = patch(client, ana, 999, name="Outro")
    assert response.status_code == 404


def test_update_validates_body_before_access(client, ana, bia):
    # Corpo inválido é 422 mesmo sem acesso: a validação não depende do hábito
    habit = created(client, ana)
    response = patch(client, bia, habit["id"], goal_count=-1)
    assert response.status_code == 422


# --- apagar ---


def test_owner_deletes_habit_with_everything(client, ana, bia, caio, outbox, db_session):
    habit = created(client, ana, score_enabled=True, reward="Pizza")
    keep = created(client, ana, name="Fica")
    patch(client, ana, habit["id"], name="Corrida")
    patch(client, ana, keep["id"], name="Fica mesmo")
    share(db_session, habit["id"], bia, "editor")
    share(db_session, habit["id"], caio, "viewer")
    row = stored(db_session, habit["id"])
    save(
        db_session,
        new_mark(row, NOW - timedelta(days=1), user_id=bia.user.id),
        new_pause(row, NOW - timedelta(days=3), NOW - timedelta(days=2)),
    )
    outbox.messages.clear()

    response = client.delete(f"/habits/{habit['id']}", headers=ana.headers)

    assert response.status_code == 204
    assert response.content == b""
    assert stored(db_session, habit["id"]) is None
    assert count(db_session, Mark) == 0
    assert count(db_session, HabitPause) == 0
    assert count(db_session, HabitMember) == 0
    # Nenhuma linha de auditoria do hábito sobra; a do outro hábito fica
    assert count(db_session, AuditLog, AuditLog.habit_id == habit["id"]) == 0
    assert count(db_session, AuditLog, AuditLog.habit_id == keep["id"]) == 2
    [entry] = events(db_session, AuditEvent.HABIT_DELETED)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        ana.user.id,
        None,
        IP,
        {"habit_id": habit["id"]},
    )
    # Um email para cada membro, no idioma dele; nenhum para a dona
    assert sorted(message["To"] for message in outbox.messages) == [
        "bia@example.com",
        "caio@example.com",
    ]
    [to_bia] = outbox.to("bia@example.com")
    [to_caio] = outbox.to("caio@example.com")
    assert to_bia["Subject"] == "A shared habit was deleted"
    assert to_caio["Subject"] == "Um hábito compartilhado foi apagado"
    assert "Corrida" in to_bia.get_body(preferencelist=("plain",)).get_content()
    assert client.get(f"/habits/{habit['id']}", headers=bia.headers).status_code == 404


def test_delete_without_members_sends_no_email(client, ana, outbox, db_session):
    habit = created(client, ana)
    outbox.messages.clear()

    assert client.delete(f"/habits/{habit['id']}", headers=ana.headers).status_code == 204

    assert outbox.messages == []
    assert count(db_session, Habit) == 0


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_member_cannot_delete(client, ana, bia, outbox, db_session, role):
    habit = created(client, ana)
    share(db_session, habit["id"], bia, role)
    outbox.messages.clear()

    response = client.delete(f"/habits/{habit['id']}", headers=bia.headers)

    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert stored(db_session, habit["id"]) is not None
    assert outbox.messages == []
    assert events(db_session, AuditEvent.HABIT_DELETED) == []


def test_stranger_cannot_delete(client, ana, bia, db_session):
    habit = created(client, ana)

    response = client.delete(f"/habits/{habit['id']}", headers=bia.headers)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert stored(db_session, habit["id"]) is not None


def test_delete_twice(client, ana):
    habit = created(client, ana)
    assert client.delete(f"/habits/{habit['id']}", headers=ana.headers).status_code == 204
    assert client.delete(f"/habits/{habit['id']}", headers=ana.headers).status_code == 404


def test_deleted_habit_frees_the_limit(client, ana, db_session):
    save(db_session, *[new_habit(ana.user) for _ in range(10)])
    first = db_session.scalar(select(Habit.id).order_by(Habit.id))

    assert client.delete(f"/habits/{first}", headers=ana.headers).status_code == 204
    assert create(client, ana).status_code == 201


# --- pontuação ---

# Hábito semanal criado numa quarta (4/3): a semana da criação (2/3) conta, até a atual (23/3)
CREATED = datetime(2026, 3, 4, 15, 0, tzinfo=UTC)


def scored_habit(db_session, owner: Account, **fields) -> Habit:
    habit = new_habit(
        owner.user,
        **(
            {"score_enabled": True, "goal_type": "min", "goal_count": 1, "created_at": CREATED}
            | fields
        ),
    )
    save(db_session, habit)
    return habit


def mark(db_session, habit: Habit, *instants: datetime, **fields) -> None:
    save(db_session, *[new_mark(habit, instant, **fields) for instant in instants])


def score_of(client, account: Account, habit_id: int) -> dict | None:
    return client.get(f"/habits/{habit_id}", headers=account.headers).json().get("score")


def test_score_disabled_is_not_returned(client, ana, db_session):
    habit = scored_habit(db_session, ana, score_enabled=False)
    mark(db_session, habit, datetime(2026, 3, 10, 15, tzinfo=UTC))

    detail = client.get(f"/habits/{habit.id}", headers=ana.headers).json()
    listed = client.get("/habits", headers=ana.headers).json()["habits"]

    assert "score" not in detail
    assert "score" not in listed[0]
    assert "success" not in detail


def test_score_of_a_habit_created_now(client, ana, db_session):
    # Criado agora: a semana atual já conta, com o valor de agora (sem marcação: não cumprida)
    habit = created(client, ana, score_enabled=True, goal_count=1)
    assert habit["score"] == {"value": 0, "success": False}

    # Meta da semana cumprida no mesmo dia: a pontuação aparece na hora
    mark(db_session, stored(db_session, habit["id"]), NOW)
    assert score_of(client, ana, habit["id"]) == {"value": 100, "success": True}


def test_score_without_data_when_every_period_is_paused(client, ana):
    habit = created(client, ana, score_enabled=True)

    paused = client.post(f"/habits/{habit['id']}/pause", headers=ana.headers).json()

    assert paused["score"] == {"value": None, "success": None}


def test_score_matches_score_module(client, ana, db_session):
    habit = scored_habit(db_session, ana, goal_count=2, score_threshold=50)
    # Semanas consideradas: 2/3 (a da criação), 9/3, 16/3 e 23/3 (a atual). Cumprem 2/3 e 9/3
    mark(
        db_session,
        habit,
        datetime(2026, 3, 5, 15, tzinfo=UTC),
        datetime(2026, 3, 6, 15, tzinfo=UTC),
        datetime(2026, 3, 9, 15, tzinfo=UTC),
        datetime(2026, 3, 11, 15, tzinfo=UTC),
        datetime(2026, 3, 17, 15, tzinfo=UTC),
        # Antes da criação: não conta
        datetime(2026, 3, 1, 15, tzinfo=UTC),
    )

    detail = score_of(client, ana, habit.id)
    listed = client.get("/habits", headers=ana.headers).json()["habits"][0]["score"]

    db_session.rollback()
    marks = [score.Mark(marked_at=row.marked_at) for row in db_session.scalars(select(Mark))]
    expected = score.evaluate(
        to_score_habit(stored(db_session, habit.id)),
        marks,
        [],
        ZoneInfo("America/Sao_Paulo"),
        NOW,
    )
    assert expected.score == 50
    assert detail == listed == {"value": expected.score, "success": expected.success}
    assert detail == {"value": 50, "success": True}


def test_changing_goal_changes_historical_score(client, ana, db_session):
    habit = scored_habit(db_session, ana, goal_count=2)
    # Uma marcação em cada semana e duas na de 9/3: só ela cumpre a meta 2
    mark(
        db_session,
        habit,
        datetime(2026, 3, 5, 15, tzinfo=UTC),
        datetime(2026, 3, 9, 15, tzinfo=UTC),
        datetime(2026, 3, 11, 15, tzinfo=UTC),
        datetime(2026, 3, 17, 15, tzinfo=UTC),
        datetime(2026, 3, 24, 15, tzinfo=UTC),
    )
    assert score_of(client, ana, habit.id) == {"value": 25, "success": False}

    body = patch(client, ana, habit.id, goal_count=1).json()

    assert body["score"] == {"value": 100, "success": True}
    assert score_of(client, ana, habit.id) == {"value": 100, "success": True}


def test_changing_threshold_changes_success(client, ana, db_session):
    habit = scored_habit(db_session, ana, goal_count=2)
    # Cumprem as semanas de 2/3 e 9/3; as de 16/3 e 23/3, não: 2 de 4
    mark(
        db_session,
        habit,
        datetime(2026, 3, 5, 15, tzinfo=UTC),
        datetime(2026, 3, 6, 15, tzinfo=UTC),
        datetime(2026, 3, 9, 15, tzinfo=UTC),
        datetime(2026, 3, 10, 15, tzinfo=UTC),
    )

    body = patch(client, ana, habit.id, score_threshold=50).json()

    assert body["score"] == {"value": 50, "success": True}


def test_toggling_duration_keeps_mark_minutes(client, ana, db_session):
    habit = scored_habit(db_session, ana, duration_enabled=True, duration_minutes=40)
    # 2/3: 1 x 40 min e 9/3: 2 x 20 min (cumprem 40 min); 16/3 e 23/3: 1 x 10 min (não cumprem)
    mark(db_session, habit, datetime(2026, 3, 5, 15, tzinfo=UTC), duration_minutes=40)
    mark(
        db_session,
        habit,
        datetime(2026, 3, 9, 15, tzinfo=UTC),
        datetime(2026, 3, 10, 15, tzinfo=UTC),
        duration_minutes=20,
    )
    mark(
        db_session,
        habit,
        datetime(2026, 3, 17, 15, tzinfo=UTC),
        datetime(2026, 3, 24, 15, tzinfo=UTC),
        duration_minutes=10,
    )
    assert score_of(client, ana, habit.id) == {"value": 50, "success": False}

    off = patch(client, ana, habit.id, duration_enabled=False).json()
    on = patch(client, ana, habit.id, duration_enabled=True).json()

    # Desligada, conta dias marcados (meta 1 por semana): as quatro semanas cumprem
    assert off["score"] == {"value": 100, "success": True}
    assert on["score"] == {"value": 50, "success": False}
    assert on["duration_minutes"] == 40
    db_session.rollback()
    assert sorted(db_session.scalars(select(Mark.duration_minutes))) == [10, 10, 20, 20, 40]


def test_score_ignores_paused_periods(client, ana, db_session):
    habit = scored_habit(db_session, ana)
    mark(
        db_session,
        habit,
        datetime(2026, 3, 5, 15, tzinfo=UTC),
        datetime(2026, 3, 10, 15, tzinfo=UTC),
        datetime(2026, 3, 24, 15, tzinfo=UTC),
    )
    # A semana de 16/3 (sem marcação) teve pausa: fica fora
    save(
        db_session,
        new_pause(
            habit, datetime(2026, 3, 18, 15, tzinfo=UTC), datetime(2026, 3, 19, 15, tzinfo=UTC)
        ),
    )

    assert score_of(client, ana, habit.id) == {"value": 100, "success": True}


def test_score_uses_timezone_of_who_asks(client, ana, make_account, db_session):
    utc_member = make_account("utc@example.com", timezone="UTC")
    habit = scored_habit(db_session, ana)
    save(db_session, new_member(habit, utc_member.user, "viewer"))
    # Segunda 9/3 01:00 UTC: semana de 9/3 em UTC; domingo 8/3 22:00 em São Paulo (semana da
    # criação). A de terça 10/3 cai na semana de 9/3 nos dois fusos
    mark(
        db_session,
        habit,
        datetime(2026, 3, 9, 1, tzinfo=UTC),
        datetime(2026, 3, 10, 15, tzinfo=UTC),
    )

    # São Paulo: 2/3 e 9/3 cumprem (2 de 4); UTC: só 9/3 (1 de 4)
    assert score_of(client, ana, habit.id) == {"value": 50, "success": False}
    assert score_of(client, utc_member, habit.id) == {"value": 25, "success": False}
    listed = client.get("/habits", headers=utc_member.headers).json()["habits"]
    assert listed[0]["score"] == {"value": 25, "success": False}


def test_list_has_no_n_plus_one(client, ana, bia, db_session, selects):
    def add_habits(amount: int) -> None:
        for _ in range(amount):
            habit = scored_habit(db_session, ana)
            mark(db_session, habit, datetime(2026, 3, 10, 15, tzinfo=UTC))
            save(
                db_session,
                new_pause(
                    habit, datetime(2026, 3, 18, tzinfo=UTC), datetime(2026, 3, 19, tzinfo=UTC)
                ),
            )
            shared = scored_habit(db_session, bia)
            save(db_session, new_member(shared, ana.user, "viewer"))

    add_habits(1)
    selects()
    assert len(client.get("/habits", headers=ana.headers).json()["habits"]) == 2
    few = selects()

    add_habits(4)
    selects()
    assert len(client.get("/habits", headers=ana.headers).json()["habits"]) == 10
    many = selects()

    assert few == many
    # Sessão do usuário, hábitos, marcações e pausas
    assert many == 4


# --- regra e adaptador (sem HTTP) ---


def test_parallel_creation_never_passes_the_limit(engine, db_session, settings, ana):
    save(db_session, *[new_habit(ana.user) for _ in range(8)])
    factory = create_session_factory(engine)
    calls = 6
    barrier = threading.Barrier(calls)
    values = VALID | {
        "code": None,
        "description": None,
        "multi_mark": False,
        "duration_enabled": False,
        "duration_minutes": None,
        "notes_enabled": False,
        "score_enabled": False,
        "score_threshold": 70,
        "reward": None,
        "punishment": None,
        "cost_enabled": False,
        "cost_level": "habit",
        "cost_cents": None,
        "cost_limit_cents": None,
        "cost_limit_period": None,
    }

    def task(_index):
        with factory() as session:
            barrier.wait()
            try:
                service.create_habit(
                    session, settings, owner_id=ana.user.id, values=values, ip=None
                )
            except ApiError as error:
                return error.code.value
            return "created"

    with ThreadPoolExecutor(max_workers=calls) as executor:
        results = list(executor.map(task, range(calls)))

    assert sorted(results) == ["created"] * 2 + ["habit_limit_reached"] * 4
    db_session.rollback()
    assert count(db_session, Habit) == 10


def test_load_marks_and_pauses(db_session, ana):
    habit = new_habit(ana.user, created_at=CREATED)
    other = new_habit(ana.user, created_at=CREATED)
    empty = new_habit(ana.user, created_at=CREATED)
    save(db_session, habit, other, empty)
    before = datetime(2026, 3, 1, tzinfo=UTC)
    after = datetime(2026, 3, 10, tzinfo=UTC)
    save(
        db_session,
        new_mark(habit, before, duration_minutes=5),
        new_mark(habit, after, cost_cents=300),
        new_mark(other, after),
        new_pause(habit, before, after),
        new_pause(other, after),
    )

    every = load_marks(db_session, [habit.id, empty.id])
    since = load_marks(db_session, [habit.id, empty.id], since_creation=True)
    pauses = load_pauses(db_session, [habit.id, empty.id])

    assert sorted(every[habit.id], key=lambda item: item.marked_at) == [
        score.Mark(marked_at=before, duration_minutes=5),
        score.Mark(marked_at=after, cost_cents=300),
    ]
    assert since == {habit.id: [score.Mark(marked_at=after, cost_cents=300)], empty.id: []}
    assert pauses == {habit.id: [score.Pause(started_at=before, ended_at=after)], empty.id: []}
    assert load_marks(db_session, []) == {}
    assert load_pauses(db_session, []) == {}


def test_to_score_habit(db_session, ana):
    habit = new_habit(
        ana.user,
        goal_type="exact",
        goal_count=2,
        goal_period="month",
        multi_mark=True,
        duration_enabled=True,
        duration_minutes=15,
        score_threshold=60,
        cost_enabled=True,
        cost_cents=100,
        cost_limit_cents=900,
        cost_limit_period="year",
        status="archived",
        archived_at=NOW,
        created_at=CREATED,
    )
    save(db_session, habit)

    assert to_score_habit(habit) == score.Habit(
        goal_type="exact",
        goal_count=2,
        goal_period="month",
        created_at=CREATED,
        multi_mark=True,
        duration_enabled=True,
        duration_minutes=15,
        score_threshold=60,
        cost_enabled=True,
        cost_limit_cents=900,
        cost_limit_period="year",
        archived_at=NOW,
    )


@pytest.mark.parametrize(
    ("role", "is_owner", "can_mark"),
    [
        (HabitRole.OWNER, True, True),
        (HabitRole.EDITOR, False, True),
        (HabitRole.VIEWER, False, False),
    ],
)
def test_access_permissions(ana, role, is_owner, can_mark):
    access = HabitAccess(new_habit(ana.user), role)
    assert (access.is_owner, access.can_mark) == (is_owner, can_mark)
