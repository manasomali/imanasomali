"""API de progresso: `GET /habits/progress` (ETH-23)."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from sqlalchemy import delete, select

from app import score
from app.db import write_transaction
from app.errors import ApiError
from app.habits.access import MAX_ID
from app.habits.scoring import to_score_habit
from app.main import create_app
from app.models import Habit, HabitMember, HabitPause, Mark
from app.progress.schemas import MAX_HABIT_IDS
from app.progress.service import check_range, limit_percent, range_end
from tests.factories import new_habit, new_mark, new_member, new_pause, save
from tests.habit_helpers import Account, invalid, stored

SP = ZoneInfo("America/Sao_Paulo")
TOKYO = ZoneInfo("Asia/Tokyo")
# Quarta-feira, 12:00 em São Paulo
NOW = datetime(2026, 3, 25, 15, 0, tzinfo=UTC)
# Uma quarta-feira: a semana da criação (3/3/2025) é a primeira da pontuação
CREATED = datetime(2025, 3, 5, 15, 0, tzinfo=UTC)
MARCH = ("2026-03-01", "2026-03-31")
# 2026-03-01 com dígitos arábico-índicos (U+0660 a U+0669): o \d de um regex os aceitaria
ARABIC_INDIC_DAY = "2026-03-01".translate({ord(d): 0x660 + int(d) for d in "0123456789"})


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
    return make_account("bia@example.com", timezone="Asia/Tokyo")


def progress(client, account: Account, first: str, last: str, **params: Any):
    query = {"from": first, "to": last, **params}
    return client.get("/habits/progress", params=query, headers=account.headers)


def ok(client, account: Account, first: str = MARCH[0], last: str = MARCH[1], **params) -> dict:
    response = progress(client, account, first, last, **params)
    assert response.status_code == 200, response.json()
    return response.json()


def only(body: dict) -> dict:
    [item] = body["habits"]
    return item


def ids(body: dict) -> list[int]:
    return [item["habit"]["id"] for item in body["habits"]]


def habit(db_session, owner: Account, **fields) -> Habit:
    model = new_habit(owner.user, **({"created_at": CREATED} | fields))
    save(db_session, model)
    return model


def mark(db_session, model: Habit, *instants: datetime, **fields) -> None:
    save(db_session, *[new_mark(model, instant, **fields) for instant in instants])


def at(day: str, hour: int = 12, minute: int = 0, tz: ZoneInfo = SP) -> datetime:
    local = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=tz)
    return local.replace(hour=hour, minute=minute).astimezone(UTC)


def days(*items: tuple[str, str]) -> list[dict]:
    return [{"first_day": first, "last_day": last} for first, last in items]


def period_json(result: score.PeriodResult) -> dict:
    out = {
        "first_day": result.period.first_day.isoformat(),
        "last_day": (result.period.end_day - timedelta(days=1)).isoformat(),
        "value": result.value,
        "met": result.met,
    }
    if result.spend_cents is not None:
        out["spend_cents"] = result.spend_cents
    return out


def direct(
    db_session, habit_id: int, tz: ZoneInfo, first: str, last: str
) -> tuple[list[dict], score.Evaluation]:
    """O `score.py` chamado direto, com as linhas lidas do banco aqui (sem o adaptador)."""
    config = to_score_habit(stored(db_session, habit_id))
    marks = [
        score.Mark(
            marked_at=row.marked_at,
            duration_minutes=row.duration_minutes,
            cost_cents=row.cost_cents,
        )
        for row in db_session.scalars(select(Mark).where(Mark.habit_id == habit_id))
    ]
    pauses = [
        score.Pause(started_at=row.started_at, ended_at=row.ended_at)
        for row in db_session.scalars(select(HabitPause).where(HabitPause.habit_id == habit_id))
    ]
    periods = score.summarize_periods(
        config, marks, tz, date.fromisoformat(first), date.fromisoformat(last)
    )
    evaluation = score.evaluate(config, marks, pauses, tz, NOW)
    return [period_json(result) for result in periods], evaluation


# --- rota e entrada ---


def test_route_is_not_taken_by_habit_id(client, ana, db_session):
    # /habits/{habit_id} é registrado depois: "progress" não pode cair nele (422 em habit_id)
    model = habit(db_session, ana)

    body = ok(client, ana)

    assert body == {
        "from": "2026-03-01",
        "to": "2026-03-31",
        "timezone": "America/Sao_Paulo",
        "habits": [body["habits"][0]],
    }
    assert ids(body) == [model.id]
    assert client.get(f"/habits/{model.id}", headers=ana.headers).status_code == 200


def test_habit_is_the_same_as_get_habit(client, ana, db_session):
    model = habit(db_session, ana, score_enabled=True, code="EX", reward="Pizza")
    mark(db_session, model, at("2026-03-10"))

    item = only(ok(client, ana))

    assert item["habit"] == client.get(f"/habits/{model.id}", headers=ana.headers).json()
    assert item["habit"]["label"] == "EX"
    assert item["goal_target"] == 3


def test_requires_session(client):
    response = client.get("/habits/progress", params={"from": MARCH[0], "to": MARCH[1]})
    assert response.status_code == 401


def test_without_habits(client, ana):
    assert ok(client, ana)["habits"] == []


@pytest.mark.parametrize("missing", ["from", "to"])
def test_dates_are_required(client, ana, missing):
    query = {"from": MARCH[0], "to": MARCH[1]}
    del query[missing]
    response = client.get("/habits/progress", params=query, headers=ana.headers)
    assert (response.status_code, response.json()) == (422, invalid(missing))


@pytest.mark.parametrize(
    "value",
    [
        "2026-3-01",
        "2026-03-01T00:00:00",
        "2026-03-01T00:00:00Z",
        "2026-03-01Z",
        "20260301",
        "1772323200",
        "2026-02-30",
        "2026-13-01",
        "",
        " 2026-03-01",
        "2026-03-01\n",
        ARABIC_INDIC_DAY,
        "1899-12-31",
    ],
)
def test_from_must_be_a_valid_day(client, ana, value):
    response = progress(client, ana, value, MARCH[1])
    assert (response.status_code, response.json()) == (422, invalid("from"))


@pytest.mark.parametrize(
    ("first", "last"),
    [
        # Depois do último dia aceito
        ("2999-01-01", "3000-01-01"),
        # Antes de from
        ("2026-03-02", "2026-03-01"),
    ],
)
def test_invalid_to(client, ana, first, last):
    response = progress(client, ana, first, last)
    assert (response.status_code, response.json()) == (422, invalid("to"))


@pytest.mark.parametrize(
    ("first", "last", "accepted"),
    [
        ("2026-03-01", "2026-03-01", True),
        # Exatamente 5 anos de dias
        ("2021-01-01", "2025-12-31", True),
        # 5 anos e 1 dia
        ("2021-01-01", "2026-01-01", False),
        ("2021-03-25", "2026-03-24", True),
        ("2021-03-25", "2026-03-25", False),
        # De 29/2, o aniversário num ano não bissexto é 1/3
        ("2024-02-29", "2029-02-28", True),
        ("2024-02-29", "2029-03-01", False),
    ],
)
def test_range_of_five_years(client, ana, db_session, first, last, accepted):
    habit(db_session, ana)
    response = progress(client, ana, first, last)
    if accepted:
        assert response.status_code == 200
    else:
        assert (response.status_code, response.json()) == (422, invalid("to"))


def test_range_rule():
    assert range_end(date(2021, 1, 1)) == date(2026, 1, 1)
    assert range_end(date(2024, 2, 29)) == date(2029, 3, 1)
    assert range_end(date(2995, 2, 28)) == date(3000, 2, 28)
    check_range(date(2021, 1, 1), date(2025, 12, 31))
    with pytest.raises(ApiError) as error:
        check_range(date(2021, 1, 1), date(2026, 1, 1))
    assert (error.value.status_code, error.value.field) == (422, "to")


@pytest.mark.parametrize(
    ("first", "last"), [("1900-01-01", "1904-12-31"), ("2995-01-01", "2999-12-31")]
)
@pytest.mark.parametrize("timezone", ["Pacific/Kiritimati", "Pacific/Pago_Pago"])
def test_extreme_dates(client, make_account, db_session, first, last, timezone):
    # Pontas do intervalo aceito, nos fusos dos dois lados da linha de data: nada estoura
    account = make_account("ext@example.com", timezone=timezone)
    for period in ("week", "month", "year"):
        habit(
            db_session,
            account,
            goal_period=period,
            goal_count=1,
            score_enabled=True,
            cost_enabled=True,
            cost_limit_cents=100,
            cost_limit_period=period,
        )

    body = ok(client, account, first, last)

    for item in body["habits"]:
        assert item["periods"][0]["first_day"] <= first
        assert item["periods"][-1]["last_day"] >= last
        assert item["cost_periods"][-1]["last_day"] >= last


@pytest.mark.parametrize(
    ("value", "field"),
    [
        ("abc", "habit_ids.0"),
        ("", "habit_ids.0"),
        ("0", "habit_ids.0"),
        ("-1", "habit_ids.0"),
        (str(MAX_ID + 1), "habit_ids.0"),
    ],
)
def test_invalid_habit_ids(client, ana, value, field):
    response = progress(client, ana, *MARCH, habit_ids=[value])
    assert (response.status_code, response.json()) == (422, invalid(field))


def test_habit_ids_limit(client, ana, db_session):
    model = habit(db_session, ana)
    at_limit = [model.id, *range(MAX_ID - MAX_HABIT_IDS + 2, MAX_ID + 1)]
    assert len(at_limit) == MAX_HABIT_IDS

    assert ids(ok(client, ana, habit_ids=at_limit)) == [model.id]
    response = progress(client, ana, *MARCH, habit_ids=[*at_limit, 1])
    assert (response.status_code, response.json()) == (422, invalid("habit_ids"))


# --- acesso ---


def test_without_habit_ids_returns_every_accessible_habit(client, ana, bia, db_session):
    own = habit(db_session, ana)
    archived = habit(db_session, ana, status="archived", archived_at=NOW - timedelta(days=3))
    paused = habit(db_session, ana, status="paused")
    shared = habit(db_session, bia)
    save(db_session, new_member(shared, ana.user, "viewer"))
    habit(db_session, bia)

    body = ok(client, ana)

    assert ids(body) == [own.id, archived.id, paused.id, shared.id]
    assert [item["habit"]["status"] for item in body["habits"]] == [
        "active",
        "archived",
        "paused",
        "active",
    ]
    assert [item["habit"]["role"] for item in body["habits"]] == [
        "owner",
        "owner",
        "owner",
        "viewer",
    ]


def test_habit_without_access_is_left_out(client, ana, bia, db_session):
    own = habit(db_session, ana)
    other = habit(db_session, bia)
    mark(db_session, other, at("2026-03-10"))

    body = ok(client, ana, habit_ids=[other.id, own.id, MAX_ID])

    # Nem 404 nem 403: igual a um id que não existe
    assert ids(body) == [own.id]
    assert ok(client, ana, habit_ids=[other.id])["habits"] == []
    assert ids(ok(client, bia, habit_ids=[other.id])) == [other.id]


def test_habit_ids_choose_and_repeat(client, ana, bia, db_session):
    first = habit(db_session, ana)
    second = habit(db_session, ana)
    shared = habit(db_session, bia)
    save(db_session, new_member(shared, ana.user, "editor"))

    body = ok(client, ana, habit_ids=[shared.id, first.id, shared.id])

    assert ids(body) == [first.id, shared.id]
    assert second.id not in ids(body)
    assert body["habits"][1]["habit"]["role"] == "editor"


def test_member_who_left_loses_the_habit(client, ana, bia, db_session):
    shared = habit(db_session, bia)
    save(db_session, new_member(shared, ana.user, "viewer"))
    assert ids(ok(client, ana)) == [shared.id]

    db_session.rollback()
    with write_transaction(db_session):
        db_session.execute(delete(HabitMember).where(HabitMember.habit_id == shared.id))

    assert ok(client, ana)["habits"] == []


# --- cálculos iguais ao score.py ---


def varied_marks(start: date, count: int, step: int) -> list[datetime]:
    """Marcações espalhadas em dias e horários variados, algumas duas no mesmo dia."""
    instants = []
    for index in range(count):
        day = start + timedelta(days=index * step)
        hour = (index * 7) % 24
        instants.append(datetime(day.year, day.month, day.day, hour, 59, tzinfo=UTC))
        if index % 4 == 0:
            instants.append(datetime(day.year, day.month, day.day, (hour + 1) % 24, tzinfo=UTC))
    return instants


CONFIGS = [
    pytest.param({"goal_type": "min", "goal_count": 3}, id="toggle-week-min"),
    pytest.param(
        {"goal_type": "exact", "goal_count": 4, "goal_period": "month", "multi_mark": True},
        id="multi-month-exact",
    ),
    pytest.param(
        {"goal_count": 1, "duration_enabled": True, "duration_minutes": 40},
        id="duration-week",
    ),
    pytest.param({"goal_type": "max", "goal_count": 0, "goal_period": "year"}, id="max-zero-year"),
    pytest.param(
        {"goal_type": "max", "goal_count": 2, "multi_mark": True, "score_threshold": 40},
        id="multi-week-max",
    ),
    pytest.param(
        {"status": "archived", "archived_at": datetime(2026, 1, 20, 15, tzinfo=UTC)},
        id="archived",
    ),
    pytest.param(
        {
            "goal_period": "month",
            "goal_count": 5,
            "cost_enabled": True,
            "cost_level": "mark",
            "cost_limit_cents": 3000,
            "cost_limit_period": "week",
        },
        id="cost-month-week-limit",
    ),
]


@pytest.mark.parametrize("config", CONFIGS)
def test_matches_score_module(client, ana, bia, db_session, config):
    model = habit(db_session, ana, score_enabled=True, **config)
    save(db_session, new_member(model, bia.user, "viewer"))
    # Do mês antes da criação (histórico) até hoje, passando pela virada do ano
    instants = varied_marks(date(2025, 2, 20), 140, 3)
    save(
        db_session,
        *[
            new_mark(model, instant, duration_minutes=10 + index % 35, cost_cents=index * 37)
            for index, instant in enumerate(instants)
        ],
        new_pause(model, datetime(2025, 6, 4, tzinfo=UTC), datetime(2025, 6, 20, tzinfo=UTC)),
        new_pause(model, datetime(2025, 9, 30, 23, tzinfo=UTC), datetime(2025, 10, 1, tzinfo=UTC)),
    )
    first, last = "2025-01-15", "2026-06-10"

    for account, tz in ((ana, SP), (bia, TOKYO)):
        item = only(ok(client, account, first, last))
        periods, evaluation = direct(db_session, model.id, tz, first, last)

        assert item["periods"] == periods
        assert item["habit"]["score"] == {"value": evaluation.score, "success": evaluation.success}
        assert item["goal_target"] == score.goal_target(
            to_score_habit(stored(db_session, model.id))
        )


def test_score_is_the_current_score(client, ana, db_session):
    # A pontuação é a do hábito agora, não a do intervalo pedido
    model = habit(db_session, ana, score_enabled=True, goal_count=1)
    mark(db_session, model, at("2026-03-10"))

    in_2025 = only(ok(client, ana, "2025-04-01", "2025-04-30"))
    detail = client.get(f"/habits/{model.id}", headers=ana.headers).json()

    assert in_2025["habit"]["score"] == detail["score"]
    assert detail["score"]["value"] is not None


def test_score_ignores_marks_before_creation_in_the_creation_week(client, ana, db_session):
    # Criado agora (quarta 25/03): a semana atual é a da criação e a única considerada. O
    # relatório lê todas as marcações, mas a da segunda, antes da criação, não entra na
    # pontuação (entra nos períodos, que são os números do que foi marcado)
    model = habit(db_session, ana, score_enabled=True, goal_count=1, created_at=NOW)
    mark(db_session, model, at("2026-03-23"))

    item = only(ok(client, ana))
    detail = client.get(f"/habits/{model.id}", headers=ana.headers).json()

    assert item["habit"]["score"] == detail["score"] == {"value": 0, "success": False}
    this_week = next(p for p in item["periods"] if p["first_day"] == "2026-03-23")
    assert (this_week["value"], this_week["met"]) == (1, True)


def test_score_disabled(client, ana, db_session):
    model = habit(db_session, ana, score_enabled=False, goal_count=1)
    mark(db_session, model, at("2026-03-10"))

    item = only(ok(client, ana))

    assert "score" not in item["habit"]
    assert "success" not in item
    assert "score" not in item
    assert item["habit"]["score_threshold"] == 70
    # Os valores e a meta de cada período continuam
    assert any(period["met"] for period in item["periods"])


def test_periods_touching_the_range_come_whole(client, ana, db_session):
    model = habit(db_session, ana, goal_count=2, multi_mark=True)
    mark(
        db_session,
        model,
        # Segunda 9/3, antes do from (quarta 11/3), mas no período: conta
        at("2026-03-09", 8),
        # Domingo 15/3 23:59 em São Paulo (segunda 02:59 UTC): ainda a semana de 9/3
        at("2026-03-15", 23, 59),
        # Segunda 16/3 00:00 em São Paulo: semana de 16/3
        at("2026-03-16", 0),
        # Segunda 23/3 00:00: fora (o intervalo acaba na terça 17/3)
        at("2026-03-23", 0),
        # Domingo 8/3 23:59: semana anterior, fora
        at("2026-03-08", 23, 59),
    )

    item = only(ok(client, ana, "2026-03-11", "2026-03-17"))

    assert item["periods"] == [
        {"first_day": "2026-03-09", "last_day": "2026-03-15", "value": 2, "met": True},
        {"first_day": "2026-03-16", "last_day": "2026-03-22", "value": 1, "met": False},
    ]


@pytest.mark.parametrize(
    ("period", "first", "last", "expected"),
    [
        (
            "week",
            "2026-03-22",
            "2026-03-23",
            [("2026-03-16", "2026-03-22"), ("2026-03-23", "2026-03-29")],
        ),
        (
            "month",
            "2026-02-28",
            "2026-03-01",
            [("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-31")],
        ),
        (
            "year",
            "2025-12-31",
            "2026-01-01",
            [("2025-01-01", "2025-12-31"), ("2026-01-01", "2026-12-31")],
        ),
        # Semana 53 ISO de 2026: segunda 28/12 a domingo 3/1/2027
        ("week", "2026-12-31", "2027-01-01", [("2026-12-28", "2027-01-03")]),
    ],
)
def test_period_edges(client, ana, db_session, period, first, last, expected):
    habit(db_session, ana, goal_period=period, goal_count=1)
    item = only(ok(client, ana, first, last))
    assert [
        {"first_day": p["first_day"], "last_day": p["last_day"]} for p in item["periods"]
    ] == days(*expected)


def test_daylight_saving_week(client, make_account, db_session):
    account = make_account("ny@example.com", timezone="America/New_York")
    model = habit(db_session, account, goal_count=1)
    ny = ZoneInfo("America/New_York")
    # O horário de verão começa domingo 8/3/2026 às 02:00: a semana de 2/3 tem 167 h
    mark(db_session, model, at("2026-03-08", 23, 30, ny), at("2026-03-09", 0, 30, ny))

    item = only(ok(client, account, "2026-03-02", "2026-03-15"))

    assert [(p["first_day"], p["value"]) for p in item["periods"]] == [
        ("2026-03-02", 1),
        ("2026-03-09", 1),
    ]


# --- gasto ---


def test_spend_at_habit_level(client, ana, db_session):
    model = habit(
        db_session,
        ana,
        goal_count=1,
        multi_mark=True,
        cost_enabled=True,
        cost_level="habit",
        cost_cents=800,
        cost_limit_cents=2000,
        cost_limit_period="month",
    )
    # 3 x 800 em março; a de fevereiro foi gravada quando o custo do hábito era 500
    mark(db_session, model, at("2026-03-02"), at("2026-03-03"), at("2026-03-10"), cost_cents=800)
    mark(db_session, model, at("2026-02-27"), cost_cents=500)

    item = only(ok(client, ana, "2026-02-23", "2026-03-15"))

    assert [(p["first_day"], p["spend_cents"]) for p in item["periods"]] == [
        ("2026-02-23", 500),
        ("2026-03-02", 1600),
        ("2026-03-09", 800),
    ]
    assert item["cost_periods"] == [
        {
            "first_day": "2026-02-01",
            "last_day": "2026-02-28",
            "spend_cents": 500,
            "limit_percent": 25,
        },
        {
            "first_day": "2026-03-01",
            "last_day": "2026-03-31",
            "spend_cents": 2400,
            "limit_percent": 120,
        },
    ]


def test_spend_at_mark_level(client, ana, db_session):
    model = habit(
        db_session,
        ana,
        goal_count=1,
        multi_mark=True,
        cost_enabled=True,
        cost_level="mark",
        cost_cents=1000,
        cost_limit_cents=1000,
        cost_limit_period="week",
    )
    # Semana de 2/3: 12,5% -> 13 (o round do Python daria 12). Semana de 9/3: 2,5% -> 3.
    # Semana de 16/3: marcação sem custo soma 0
    mark(db_session, model, at("2026-03-02"), cost_cents=100)
    mark(db_session, model, at("2026-03-04"), cost_cents=25)
    mark(db_session, model, at("2026-03-10"), cost_cents=25)
    mark(db_session, model, at("2026-03-17"), cost_cents=None)

    item = only(ok(client, ana, "2026-03-02", "2026-03-22"))

    assert item["cost_periods"] == [
        {
            "first_day": "2026-03-02",
            "last_day": "2026-03-08",
            "spend_cents": 125,
            "limit_percent": 13,
        },
        {
            "first_day": "2026-03-09",
            "last_day": "2026-03-15",
            "spend_cents": 25,
            "limit_percent": 3,
        },
        {"first_day": "2026-03-16", "last_day": "2026-03-22", "spend_cents": 0, "limit_percent": 0},
    ]
    assert [p["spend_cents"] for p in item["periods"]] == [125, 25, 0]


def test_spend_with_zero_limit(client, ana, db_session):
    model = habit(
        db_session,
        ana,
        goal_type="max",
        goal_count=0,
        cost_enabled=True,
        cost_level="habit",
        cost_cents=300,
        cost_limit_cents=0,
        cost_limit_period="month",
    )
    mark(db_session, model, at("2026-03-02"), cost_cents=300)

    item = only(ok(client, ana))

    assert item["cost_periods"] == [
        {
            "first_day": "2026-03-01",
            "last_day": "2026-03-31",
            "spend_cents": 300,
            "limit_percent": None,
        },
    ]


def test_spend_without_limit(client, ana, db_session):
    model = habit(db_session, ana, cost_enabled=True, cost_level="habit", cost_cents=300)
    mark(db_session, model, at("2026-03-02"), cost_cents=300)

    item = only(ok(client, ana, "2026-03-02", "2026-03-08"))

    assert "cost_periods" not in item
    assert item["periods"][0]["spend_cents"] == 300


def test_cost_disabled_hides_spend(client, ana, db_session):
    # Custo gravado quando estava ligado; desligado, nada de gasto na resposta
    model = habit(
        db_session,
        ana,
        cost_enabled=False,
        cost_cents=300,
        cost_limit_cents=1000,
        cost_limit_period="month",
    )
    mark(db_session, model, at("2026-03-02"), cost_cents=300)

    item = only(ok(client, ana))

    assert "cost_periods" not in item
    assert all("spend_cents" not in period for period in item["periods"])


def test_limit_percent():
    assert limit_percent(0, 1000) == 0
    assert limit_percent(5, 1000) == 1
    assert limit_percent(4, 1000) == 0
    assert limit_percent(1000, 1000) == 100
    assert limit_percent(10**15, 1) == 10**17
    assert limit_percent(0, 0) is None
    assert limit_percent(1, 0) is None


# --- marcações de todo o tempo ---


def test_marks_range_covers_all_time(client, ana, db_session):
    model = habit(db_session, ana)
    empty = habit(db_session, ana)
    # Antes da criação (histórico), fora do intervalo pedido e 01:00 UTC (dia anterior em SP)
    mark(
        db_session,
        model,
        at("1950-06-01"),
        at("2026-03-10"),
        datetime(2026, 3, 25, 1, 0, tzinfo=UTC),
    )

    body = ok(client, ana, "2026-03-01", "2026-03-01")

    assert [item["marks_range"] for item in body["habits"]] == [
        {"first_day": "1950-06-01", "last_day": "2026-03-24"},
        None,
    ]
    assert ids(body) == [model.id, empty.id]


def test_marks_range_in_the_timezone_of_the_viewer(client, ana, bia, db_session):
    shared = habit(db_session, ana)
    save(db_session, new_member(shared, bia.user, "viewer"))
    # 2026-03-10 22:00 em São Paulo já é 2026-03-11 em Tóquio
    mark(db_session, shared, at("2026-03-10", hour=22))

    assert only(ok(client, ana))["marks_range"] == {
        "first_day": "2026-03-10",
        "last_day": "2026-03-10",
    }
    assert only(ok(client, bia))["marks_range"] == {
        "first_day": "2026-03-11",
        "last_day": "2026-03-11",
    }


# --- leitura em lote ---


def test_no_n_plus_one(client, ana, bia, db_session, selects):
    def add_habits(amount: int) -> None:
        for _ in range(amount):
            scored = habit(db_session, ana, score_enabled=True, cost_enabled=True)
            mark(db_session, scored, at("2026-03-10"), cost_cents=10)
            save(
                db_session,
                new_pause(
                    scored, datetime(2026, 3, 18, tzinfo=UTC), datetime(2026, 3, 19, tzinfo=UTC)
                ),
            )
            habit(db_session, ana, status="archived", archived_at=NOW)
            shared = habit(db_session, bia, score_enabled=True)
            save(db_session, new_member(shared, ana.user, "viewer"))

    add_habits(1)
    selects()
    assert len(ok(client, ana)["habits"]) == 3
    few = selects()

    add_habits(4)
    selects()
    assert len(ok(client, ana)["habits"]) == 15
    many = selects()

    assert few == many
    # Sessão do usuário, hábitos (ativos e arquivados), marcações e pausas
    assert many == 5
