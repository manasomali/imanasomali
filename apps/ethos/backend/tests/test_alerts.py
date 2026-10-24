"""Alertas (ETH-26): a configuração pela API e a avaliação do `run-alerts`.

Tempo sempre congelado. O cenário base é um hábito "3x por semana" criado semanas antes, de uma
conta em São Paulo (UTC-3, sem horário de verão), com o alerta diário das 08:00. Na quarta,
2026-03-25, às 08:00 locais (11:00 UTC), o ritmo esperado é 3 * 56 h // 168 h = 1.
"""

import logging
import re
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cli
from app.alerts import service
from app.alerts.service import DEFAULT_HOUR, RunResult, is_due, run_alerts, scheduled_at
from app.audit import AuditEvent
from app.db import create_session_factory, write_transaction
from app.mail.sender import Mailer
from app.main import create_app
from app.models import Alert, Habit, HabitStatus, User
from tests.auth_helpers import Outbox
from tests.factories import (
    count,
    new_alert,
    new_habit,
    new_mark,
    new_member,
    new_pause,
    new_user,
    save,
)
from tests.habit_helpers import FORBIDDEN, NOT_FOUND, events, invalid
from tests.test_cli import env_for

SP = ZoneInfo("America/Sao_Paulo")
NY = ZoneInfo("America/New_York")
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
# Quarta-feira, 08:00 em São Paulo
WEDNESDAY_8 = datetime(2026, 3, 25, 11, 0, tzinfo=UTC)
MONDAY = datetime(2026, 3, 23, 3, 0, tzinfo=UTC)
CREATED = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
APP_URL = "http://localhost:5174/ethos"
ARCHIVED = {"error": "habit_archived", "field": None}
CONFIG = {
    "goal_enabled": True,
    "cost_enabled": False,
    "hour": 8,
    "frequency": "daily",
    "weekday": None,
}
DEFAULT = {
    "goal_enabled": False,
    "cost_enabled": False,
    "hour": DEFAULT_HOUR,
    "frequency": "daily",
    "weekday": None,
    "last_sent_at": None,
}
COST = {"cost_enabled": True, "cost_limit_cents": 10_000, "cost_limit_period": "week"}


# --- Montagem ---


@pytest.fixture
def outbox_mailer(settings, outbox) -> Mailer:
    return Mailer(settings, outbox)


@pytest.fixture
def run(engine, outbox_mailer) -> Callable[..., RunResult]:
    """Roda o `run_alerts` no instante dado (padrão: quarta 08:00), com o tempo congelado."""
    factory = create_session_factory(engine)

    def call(now: datetime = WEDNESDAY_8, mailer: Mailer | None = None) -> RunResult:
        with time_machine.travel(now, tick=False):
            return run_alerts(factory, mailer or outbox_mailer, now=now)

    return call


def make_user(db_session: Session, email: str = "ana@example.com", **fields: Any) -> User:
    user = new_user(email, **fields)
    save(db_session, user)
    return user


def make_habit(
    db_session: Session,
    owner: User,
    *,
    alert: dict[str, Any] | None = None,
    marks: tuple[datetime, ...] = (),
    mark_cost: int | None = None,
    **fields: Any,
) -> Habit:
    """Hábito do `owner` (criado em `CREATED`) com o alerta do dono e as marcações dadas."""
    habit = new_habit(owner, **({"created_at": CREATED} | fields))
    save(db_session, habit)
    rows: list[Any] = [new_mark(habit, at, cost_cents=mark_cost) for at in marks]
    if alert is not None:
        rows.append(new_alert(habit, owner, **alert))
    if rows:
        save(db_session, *rows)
    return habit


def text_of(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    assert part is not None
    return part.get_content()


def stored_alert(db_session: Session, habit: Habit, user: User) -> Alert | None:
    db_session.rollback()
    return db_session.get(Alert, (habit.id, user.id), populate_existing=True)


def set_status(db_session: Session, habit: Habit, status: HabitStatus) -> None:
    with write_transaction(db_session):
        row = db_session.get(Habit, habit.id, populate_existing=True)
        row.status = status.value
        row.archived_at = WEDNESDAY_8 - DAY if status is HabitStatus.ARCHIVED else None


# --- Configuração pela API ---


@pytest.fixture(autouse=True)
def clock() -> Iterator[time_machine.Traveller]:
    with time_machine.travel(WEDNESDAY_8, tick=False) as traveller:
        yield traveller


@pytest.fixture
def client(settings, database, make_client, outbox, clock):
    return make_client(create_app(settings, mail_backend=outbox))


@pytest.fixture
def ana(make_account):
    return make_account("ana@example.com")


@pytest.fixture
def bia(make_account):
    return make_account("bia@example.com")


@pytest.fixture
def habit(db_session, ana) -> Habit:
    habit = new_habit(ana.user, created_at=CREATED)
    save(db_session, habit)
    return habit


def url(habit: Habit | int) -> str:
    habit_id = habit if isinstance(habit, int) else habit.id
    return f"/habits/{habit_id}/alerts"


def test_both_switches_start_off(client, ana, habit, db_session):
    response = client.get(url(habit), headers=ana.headers)

    assert (response.status_code, response.json()) == (200, DEFAULT)
    # Ler não grava nada
    assert count(db_session, Alert) == 0


def test_save_stores_the_config_and_audits_the_changes(client, ana, habit, db_session):
    body = CONFIG | {"cost_enabled": True, "frequency": "weekly", "weekday": 4}

    response = client.put(url(habit), json=body, headers=ana.headers)

    assert response.status_code == 200
    assert response.json() == body | {"last_sent_at": None}
    alert = stored_alert(db_session, habit, ana.user)
    assert (alert.goal_enabled, alert.cost_enabled, alert.hour, alert.frequency, alert.weekday) == (
        True,
        True,
        8,
        "weekly",
        4,
    )
    # Âncora: a ocorrência de hoje que já passou não é avaliada atrasada
    assert alert.last_evaluated_at == WEDNESDAY_8
    assert client.get(url(habit), headers=ana.headers).json() == response.json()
    [entry] = events(db_session, AuditEvent.ALERT_UPDATED)
    assert (entry.user_id, entry.habit_id) == (ana.user.id, habit.id)
    assert entry.details == {
        "changes": [
            {"field": "goal_enabled", "old": False, "new": True},
            {"field": "cost_enabled", "old": False, "new": True},
            {"field": "hour", "old": DEFAULT_HOUR, "new": 8},
            {"field": "frequency", "old": "daily", "new": "weekly"},
            {"field": "weekday", "old": None, "new": 4},
        ]
    }


def test_saving_the_same_config_changes_nothing(client, ana, bia, habit, db_session):
    save(db_session, new_member(habit, bia.user, "editor"))
    assert client.put(url(habit), json=CONFIG, headers=ana.headers).status_code == 200

    with time_machine.travel(WEDNESDAY_8 + HOUR, tick=False):
        again = client.put(url(habit), json=CONFIG, headers=ana.headers)
        defaults = {key: value for key, value in DEFAULT.items() if key != "last_sent_at"}
        untouched = client.put(url(habit), json=defaults, headers=bia.headers)

    assert again.status_code == 200
    assert len(events(db_session, AuditEvent.ALERT_UPDATED)) == 1
    # Nem a âncora da avaliação muda
    assert stored_alert(db_session, habit, ana.user).last_evaluated_at == WEDNESDAY_8
    # A configuração padrão, sem nada salvo antes, não cria linha
    assert untouched.json() == DEFAULT
    assert count(db_session, Alert) == 1


def test_daily_drops_the_stored_weekday(client, ana, habit, db_session):
    weekly = CONFIG | {"frequency": "weekly", "weekday": 2}
    assert client.put(url(habit), json=weekly, headers=ana.headers).status_code == 200

    response = client.put(url(habit), json=CONFIG, headers=ana.headers)

    assert response.json()["weekday"] is None
    assert stored_alert(db_session, habit, ana.user).weekday is None


def test_daily_row_with_a_stored_weekday_shows_none(client, ana, habit, db_session):
    # O banco aceita guardar o dia no diário; a API mostra só o que vale
    save(db_session, new_alert(habit, ana.user, weekday=3))

    assert client.get(url(habit), headers=ana.headers).json()["weekday"] is None


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"hour": 24}, "hour"),
        ({"hour": -1}, "hour"),
        ({"hour": "9"}, "hour"),
        ({"hour": 9.0}, "hour"),
        ({"hour": 9.5}, "hour"),
        ({"hour": True}, "hour"),
        ({"hour": None}, "hour"),
        ({"goal_enabled": "true"}, "goal_enabled"),
        ({"cost_enabled": 1}, "cost_enabled"),
        ({"frequency": "monthly"}, "frequency"),
        ({"frequency": "weekly"}, "weekday"),
        ({"frequency": "weekly", "weekday": None}, "weekday"),
        ({"frequency": "weekly", "weekday": 7}, "weekday"),
        ({"frequency": "weekly", "weekday": -1}, "weekday"),
        ({"frequency": "weekly", "weekday": "1"}, "weekday"),
        ({"weekday": 2}, "weekday"),
        ({"last_sent_at": None}, "last_sent_at"),
        ({"user_id": 1}, "user_id"),
    ],
)
def test_invalid_config_is_refused(client, ana, habit, db_session, changes, field):
    response = client.put(url(habit), json=CONFIG | changes, headers=ana.headers)

    assert (response.status_code, response.json()) == (422, invalid(field))
    assert count(db_session, Alert) == 0


@pytest.mark.parametrize("missing", ["goal_enabled", "cost_enabled", "hour", "frequency"])
def test_required_fields(client, ana, habit, missing):
    body = {key: value for key, value in CONFIG.items() if key != missing}

    response = client.put(url(habit), json=body, headers=ana.headers)

    assert (response.status_code, response.json()) == (422, invalid(missing))


def test_weekly_without_weekday_key_is_refused(client, ana, habit):
    body = {key: value for key, value in CONFIG.items() if key != "weekday"}
    body["frequency"] = "weekly"

    response = client.put(url(habit), json=body, headers=ana.headers)

    assert (response.status_code, response.json()) == (422, invalid("weekday"))


def test_owner_and_editor_have_separate_configs(client, ana, bia, habit, db_session):
    save(db_session, new_member(habit, bia.user, "editor"))

    assert client.put(url(habit), json=CONFIG, headers=bia.headers).status_code == 200

    assert client.get(url(habit), headers=ana.headers).json() == DEFAULT
    assert client.get(url(habit), headers=bia.headers).json()["goal_enabled"] is True
    [entry] = events(db_session, AuditEvent.ALERT_UPDATED)
    assert entry.user_id == bia.user.id


def test_viewer_gets_403_on_read_and_save(client, bia, habit, db_session):
    save(db_session, new_member(habit, bia.user, "viewer"))

    read = client.get(url(habit), headers=bia.headers)
    saved = client.put(url(habit), json=CONFIG, headers=bia.headers)

    assert (read.status_code, read.json()) == (403, FORBIDDEN)
    assert (saved.status_code, saved.json()) == (403, FORBIDDEN)
    assert count(db_session, Alert) == 0


def test_stranger_and_missing_habit_get_404(client, bia, ana, habit):
    for headers, habit_id in ((bia.headers, habit.id), (ana.headers, habit.id + 1000)):
        assert client.get(url(habit_id), headers=headers).json() == NOT_FOUND
        response = client.put(url(habit_id), json=CONFIG, headers=headers)
        assert (response.status_code, response.json()) == (404, NOT_FOUND)


def test_archived_habit_reads_but_refuses_save(client, ana, habit, db_session):
    save(db_session, new_alert(habit, ana.user))
    set_status(db_session, habit, HabitStatus.ARCHIVED)

    read = client.get(url(habit), headers=ana.headers)
    saved = client.put(url(habit), json=CONFIG | {"hour": 9}, headers=ana.headers)

    assert read.json()["goal_enabled"] is True
    assert (saved.status_code, saved.json()) == (409, ARCHIVED)
    assert stored_alert(db_session, habit, ana.user).hour == 8


def test_paused_habit_saves(client, ana, habit, db_session):
    set_status(db_session, habit, HabitStatus.PAUSED)

    assert client.put(url(habit), json=CONFIG, headers=ana.headers).status_code == 200


def test_alert_updated_stays_out_of_the_history(client, ana, habit):
    assert client.put(url(habit), json=CONFIG, headers=ana.headers).status_code == 200

    history = client.get("/history", params={"habit_id": habit.id}, headers=ana.headers)

    assert history.status_code == 200
    assert [event["event"] for event in history.json()["events"]] == []


def test_demoted_editor_loses_the_alert_and_gets_no_email(
    client, ana, bia, habit, db_session, outbox, run
):
    save(db_session, new_member(habit, bia.user, "editor"))
    assert client.put(url(habit), json=CONFIG | {"hour": 9}, headers=bia.headers).status_code == 200

    demoted = client.patch(
        f"/habits/{habit.id}/members/{bia.user.id}", json={"role": "viewer"}, headers=ana.headers
    )

    assert demoted.status_code == 200
    assert stored_alert(db_session, habit, bia.user) is None
    # 09:00 do mesmo dia: o hábito está atrasado, mas a bia não tem mais alerta
    assert run(WEDNESDAY_8 + HOUR) == RunResult(evaluated=0, sent=0, failed=0)
    assert outbox.messages == []


# --- Regras de disparo ---


def assert_sent(outbox: Outbox, to: str, *lines: str) -> str:
    [message] = outbox.messages
    assert message["To"] == to
    assert message["Subject"] == "Alerta de hábito no ethos"
    text = text_of(message)
    for line in lines:
        assert line in text
    return text


@pytest.mark.parametrize(
    ("now", "marks", "fires"),
    [
        # Quarta 08:00: esperado 1
        (WEDNESDAY_8, 0, True),
        (WEDNESDAY_8, 1, False),
        # Quarta 07:00 (alerta das 07:00): 3 * 55 // 168 = 0, ainda não está atrasado
        (WEDNESDAY_8 - HOUR, 0, False),
    ],
)
def test_min_goal_fires_when_behind_pace(db_session, outbox, run, now, marks, fires):
    ana = make_user(db_session)
    hour = now.astimezone(SP).hour
    habit = make_habit(db_session, ana, alert={"hour": hour}, marks=(MONDAY + HOUR,) * marks)

    result = run(now)

    assert result == RunResult(evaluated=1, sent=int(fires), failed=0)
    if fires:
        text = assert_sent(outbox, "ana@example.com", "Meta atrasada: 0 de 3 nesta semana")
        assert f"{APP_URL}/habits/{habit.id}/alerts" in text
        assert "Exercício" in text
        assert stored_alert(db_session, habit, ana).last_sent_at == now
    else:
        assert outbox.messages == []
        assert stored_alert(db_session, habit, ana).last_sent_at is None


@pytest.mark.parametrize(
    ("marks", "line"),
    [
        (1, None),
        (2, "Máximo atingido: 2 de no máximo 2 nesta semana"),
        (3, "Meta ultrapassada: 3 nesta semana, acima de 2"),
    ],
)
def test_max_goal_fires_when_reached_or_passed(db_session, outbox, run, marks, line):
    ana = make_user(db_session)
    days = tuple(MONDAY + HOUR + index * HOUR for index in range(marks))
    make_habit(
        db_session, ana, alert={}, marks=days, goal_type="max", goal_count=2, multi_mark=True
    )

    run()

    if line is None:
        assert outbox.messages == []
    else:
        assert_sent(outbox, "ana@example.com", line)


def test_max_zero_fires_on_the_first_mark(db_session, outbox, run):
    ana = make_user(db_session)
    make_habit(db_session, ana, alert={}, goal_type="max", goal_count=0)
    other = make_user(db_session, "bia@example.com")
    make_habit(db_session, other, alert={}, marks=(MONDAY + HOUR,), goal_type="max", goal_count=0)

    run()

    assert_sent(outbox, "bia@example.com", "Meta ultrapassada: 1 nesta semana, acima de 0")


# Sábado, 12:00 em São Paulo: 2 * 132 h // 168 h = 1
SATURDAY_12 = datetime(2026, 3, 28, 15, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("marks", "line"),
    [
        (0, "Meta atrasada: 0 de 2 nesta semana"),
        (1, None),
        (2, None),
        (3, "Meta ultrapassada: 3 nesta semana, acima de 2"),
    ],
)
def test_exact_goal_fires_when_behind_or_passed(db_session, outbox, run, marks, line):
    ana = make_user(db_session)
    days = tuple(MONDAY + HOUR + index * HOUR for index in range(marks))
    make_habit(
        db_session,
        ana,
        alert={"hour": 12},
        marks=days,
        goal_type="exact",
        goal_count=2,
        multi_mark=True,
    )

    run(SATURDAY_12)

    if line is None:
        assert outbox.messages == []
    else:
        assert_sent(outbox, "ana@example.com", line)


@pytest.mark.parametrize(
    ("spent", "line"),
    [
        (7_999, None),
        (8_000, "Custo perto do limite: 80,00 de 100,00 nesta semana"),
        (10_000, "Custo perto do limite: 100,00 de 100,00 nesta semana"),
        (10_001, "Limite de custo ultrapassado: 100,01 de 100,00 nesta semana"),
    ],
)
def test_cost_warns_at_80_percent_and_alerts_past_the_limit(db_session, outbox, run, spent, line):
    ana = make_user(db_session)
    make_habit(
        db_session,
        ana,
        alert={"goal_enabled": False, "cost_enabled": True},
        marks=(MONDAY + HOUR,),
        mark_cost=spent,
        **COST,
    )

    run()

    if line is None:
        assert outbox.messages == []
    else:
        text = assert_sent(outbox, "ana@example.com", line)
        assert "Meta atrasada" not in text


def test_goal_behind_and_cost_warning_together_in_one_email(db_session, outbox, run):
    # Uma marcação de 90,00 na segunda. No sábado às 08:00, o esperado é 3 * 128 h // 168 h = 2:
    # 1 de 3 está atrasado, e o gasto passou de 80% do limite
    ana = make_user(db_session)
    make_habit(
        db_session,
        ana,
        alert={"cost_enabled": True},
        marks=(MONDAY + HOUR,),
        mark_cost=9_000,
        **COST,
    )
    saturday_8 = datetime(2026, 3, 28, 11, 0, tzinfo=UTC)

    assert run(saturday_8) == RunResult(evaluated=1, sent=1, failed=0)

    assert_sent(
        outbox,
        "ana@example.com",
        "Meta atrasada: 1 de 3 nesta semana",
        "Custo perto do limite: 90,00 de 100,00 nesta semana",
    )


def test_only_cost_switch_ignores_a_late_goal(db_session, outbox, run):
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={"goal_enabled": False, "cost_enabled": True}, **COST)

    # Atrasado na meta (0 de 3), sem gasto
    assert run() == RunResult(evaluated=1, sent=0, failed=0)

    assert outbox.messages == []
    assert stored_alert(db_session, habit, ana).last_evaluated_at == WEDNESDAY_8


def test_switches_off_are_not_evaluated(db_session, outbox, run):
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={"goal_enabled": False})

    assert run() == RunResult(evaluated=0, sent=0, failed=0)
    assert stored_alert(db_session, habit, ana).last_evaluated_at is None


def test_nothing_fires_in_the_creation_period(db_session, outbox, run):
    # Criado na segunda e atrasado na quarta da mesma semana: nenhum email
    ana = make_user(db_session)
    make_habit(db_session, ana, alert={"cost_enabled": True}, created_at=MONDAY + HOUR, **COST)
    with write_transaction(db_session):
        habit = db_session.scalars(select(Habit)).one()
        db_session.add(new_mark(habit, MONDAY + 2 * HOUR, cost_cents=50_000))

    assert run() == RunResult(evaluated=1, sent=0, failed=0)
    # Na semana seguinte, sim
    next_wednesday = WEDNESDAY_8 + 7 * DAY
    assert run(next_wednesday) == RunResult(evaluated=1, sent=1, failed=0)
    assert_sent(outbox, "ana@example.com", "Meta atrasada: 0 de 3 nesta semana")


@pytest.mark.parametrize("status", [HabitStatus.PAUSED, HabitStatus.ARCHIVED])
def test_paused_and_archived_habits_do_not_fire(db_session, outbox, run, status):
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={})
    set_status(db_session, habit, status)

    assert run() == RunResult(evaluated=0, sent=0, failed=0)
    assert outbox.messages == []


def test_pause_earlier_in_the_period_blocks_the_alert(db_session, outbox, run):
    # Ativo de novo, mas a semana teve pausa: o score.py não avalia o ritmo
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={})
    save(db_session, new_pause(habit, MONDAY, MONDAY + DAY))

    assert run() == RunResult(evaluated=1, sent=0, failed=0)
    assert outbox.messages == []


def test_blocked_account_gets_no_alert(db_session, outbox, run):
    ana = make_user(db_session, is_active=False)
    make_habit(db_session, ana, alert={})

    assert run() == RunResult(evaluated=0, sent=0, failed=0)


def test_editor_gets_the_alert_in_their_own_locale(db_session, outbox, run):
    ana = make_user(db_session)
    bia = make_user(db_session, "bia@example.com", locale="en", timezone="UTC")
    habit = make_habit(db_session, ana)
    # 11:00 UTC é a hora da bia
    save(db_session, new_member(habit, bia, "editor"), new_alert(habit, bia, hour=11))

    assert run() == RunResult(evaluated=1, sent=1, failed=0)

    [message] = outbox.messages
    assert (message["To"], message["Subject"]) == ("bia@example.com", "Habit alert from ethos")
    assert "Goal behind pace: 0 of 3 this week." in text_of(message)


def test_leftover_alert_of_a_viewer_is_not_sent(db_session, outbox, run):
    # Rede de segurança: rebaixar apaga o alerta, mas uma linha que sobrasse não manda nada
    ana = make_user(db_session)
    bia = make_user(db_session, "bia@example.com")
    habit = make_habit(db_session, ana)
    save(db_session, new_member(habit, bia, "viewer"), new_alert(habit, bia))

    assert run() == RunResult(evaluated=0, sent=0, failed=0)
    assert outbox.messages == []


# --- Hora, dia e repetição ---


@pytest.mark.parametrize(("weekday", "fires"), [(2, True), (1, False), (3, False)])
def test_weekly_fires_only_on_its_day(db_session, outbox, run, weekday, fires):
    ana = make_user(db_session)
    make_habit(db_session, ana, alert={"frequency": "weekly", "weekday": weekday})

    assert run().sent == int(fires)


def test_two_runs_in_a_row_send_one_email(db_session, outbox, run):
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={})

    assert run().sent == 1
    assert run(WEDNESDAY_8 + timedelta(minutes=1)).sent == 0
    # O resto do dia também não manda de novo, nem com a hora trocada para mais tarde
    with write_transaction(db_session):
        db_session.get(Alert, (habit.id, ana.id), populate_existing=True).hour = 15
    for hours in range(1, 12):
        run(WEDNESDAY_8 + hours * HOUR)
    assert len(outbox.messages) == 1
    # No dia seguinte, sim
    assert run(WEDNESDAY_8 + DAY + 7 * HOUR).sent == 1


def test_evaluated_without_email_is_not_reevaluated_later_that_day(db_session, outbox, run):
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={"hour": 7})

    # 07:00: ainda no ritmo (esperado 0)
    assert run(WEDNESDAY_8 - HOUR) == RunResult(evaluated=1, sent=0, failed=0)
    # 08:00: já estaria atrasado, mas o alerta das 07:00 já foi avaliado hoje
    assert run() == RunResult(evaluated=0, sent=0, failed=0)
    assert outbox.messages == []
    assert stored_alert(db_session, habit, ana).last_evaluated_at == WEDNESDAY_8 - HOUR


def test_late_run_still_sends_the_same_day(db_session, outbox, run):
    ana = make_user(db_session)
    make_habit(db_session, ana, alert={"hour": 6})

    # O timer das 06:00 e o das 07:00 não rodaram; o das 08:00 rodou às 08:05
    assert run(WEDNESDAY_8 + timedelta(minutes=5)).sent == 1
    assert run(WEDNESDAY_8 + HOUR).sent == 0


def test_occurrence_of_a_day_without_runs_is_lost(db_session, outbox, run):
    ana = make_user(db_session)
    make_habit(db_session, ana, alert={"hour": 23})

    # Nenhuma execução entre 23:00 e a meia-noite; à 01:00 é outro dia e a hora não chegou
    assert run(WEDNESDAY_8 + 18 * HOUR).sent == 0
    assert outbox.messages == []


def test_saving_after_the_hour_starts_tomorrow(client, ana, habit, outbox, run):
    # Salvo às 08:00 com a hora 07:00: a ocorrência de hoje já passou
    assert client.put(url(habit), json=CONFIG | {"hour": 7}, headers=ana.headers).status_code == 200

    assert run(WEDNESDAY_8 + HOUR).evaluated == 0
    assert run(WEDNESDAY_8 + DAY - HOUR).sent == 1


def test_saving_before_the_hour_fires_today(client, ana, habit, outbox, run):
    assert client.put(url(habit), json=CONFIG | {"hour": 9}, headers=ana.headers).status_code == 200

    assert run(WEDNESDAY_8 + HOUR).sent == 1


def test_hour_is_read_in_the_user_timezone(db_session, outbox, run):
    tokyo = make_user(db_session, "ana@example.com", timezone="Asia/Tokyo")
    # 11:00 UTC = 20:00 em Tóquio
    make_habit(db_session, tokyo, alert={"hour": 20})
    other = make_user(db_session, "bia@example.com", timezone="Asia/Tokyo")
    make_habit(db_session, other, alert={"hour": 21})

    run()

    assert [message["To"] for message in outbox.messages] == ["ana@example.com"]


def hourly(start: datetime, hours: int) -> list[datetime]:
    return [start + index * HOUR for index in range(hours)]


def test_dst_gap_fires_once_right_after_the_jump(db_session, outbox, run):
    # 2026-03-08 em Nova York: 02:00 vira 03:00 (07:00 UTC). O alerta das 02:00 sai às 03:00
    ana = make_user(db_session, timezone="America/New_York")
    make_habit(
        db_session,
        ana,
        alert={"goal_enabled": False, "cost_enabled": True, "hour": 2},
        marks=(datetime(2026, 3, 3, 15, 0, tzinfo=UTC),),
        mark_cost=20_000,
        created_at=datetime(2026, 2, 2, 15, 0, tzinfo=UTC),
        **COST,
    )

    # De hora em hora, da meia-noite de domingo (05:00 UTC) às 09:00 EDT
    sent_at = [now for now in hourly(datetime(2026, 3, 8, 5, 0, tzinfo=UTC), 9) if run(now).sent]

    assert sent_at == [datetime(2026, 3, 8, 7, 0, tzinfo=UTC)]
    assert sent_at[0].astimezone(NY).hour == 3


def test_dst_repeated_hour_fires_once_on_the_first(db_session, outbox, run):
    # 2026-11-01 em Nova York: 01:00 acontece duas vezes (05:00 e 06:00 UTC)
    ana = make_user(db_session, timezone="America/New_York")
    make_habit(
        db_session,
        ana,
        alert={"goal_enabled": False, "cost_enabled": True, "hour": 1},
        marks=(datetime(2026, 10, 27, 15, 0, tzinfo=UTC),),
        mark_cost=20_000,
        created_at=datetime(2026, 10, 1, 15, 0, tzinfo=UTC),
        **COST,
    )

    # De hora em hora, da meia-noite de domingo (04:00 UTC) às 04:00 EST
    sent_at = [now for now in hourly(datetime(2026, 11, 1, 4, 0, tzinfo=UTC), 6) if run(now).sent]

    assert sent_at == [datetime(2026, 11, 1, 5, 0, tzinfo=UTC)]


def test_is_due_in_the_repeated_hour_without_email():
    # Avaliada na primeira 01:00 sem email: a segunda 01:00 não reavalia
    first = datetime(2026, 11, 1, 5, 0, tzinfo=UTC)
    second = first + HOUR
    assert scheduled_at(first.astimezone(NY).date(), 1, NY) == first
    common = {"hour": 1, "frequency": "daily", "weekday": None, "last_sent_at": None, "tz": NY}

    assert is_due(**common, last_evaluated_at=None, now=first)
    assert not is_due(**common, last_evaluated_at=first, now=second)


def test_is_due_in_the_missing_hour():
    jump = datetime(2026, 3, 8, 7, 0, tzinfo=UTC)
    assert scheduled_at(jump.astimezone(NY).date(), 2, NY) == jump
    assert scheduled_at(jump.astimezone(NY).date(), 3, NY) == jump
    common = {"frequency": "daily", "weekday": None, "last_sent_at": None, "tz": NY}

    assert not is_due(**common, hour=2, last_evaluated_at=None, now=jump - timedelta(seconds=1))
    assert is_due(**common, hour=2, last_evaluated_at=None, now=jump)


def test_run_refuses_a_naive_now(engine, outbox_mailer):
    with pytest.raises(ValueError, match="fuso"):
        run_alerts(create_session_factory(engine), outbox_mailer, now=datetime(2026, 3, 25, 11))


# --- Falhas ---


class Refusing:
    """Backend que recusa um destinatário e entrega o resto por outro backend."""

    def __init__(self, refused: str, deliver: Any) -> None:
        self.refused = refused
        self.deliver = deliver

    def send(self, message: EmailMessage) -> None:
        if message["To"] == self.refused:
            raise ConnectionError(f"recusado: {self.refused}")
        self.deliver.send(message)


def test_smtp_error_in_one_alert_does_not_stop_the_others(
    db_session, settings, smtp_server, run, caplog
):
    users = [make_user(db_session, f"{name}@example.com") for name in ("ana", "bia", "caio")]
    habits = [make_habit(db_session, user, alert={}) for user in users]
    mailer = Mailer(settings, Refusing("bia@example.com", smtp_server.backend()))

    with caplog.at_level(logging.INFO, logger="app"):
        result = run(mailer=mailer)

    assert result == RunResult(evaluated=2, sent=2, failed=1)
    received = sorted(rcpt for email in smtp_server.received for rcpt in email.rcpt_tos)
    assert received == ["ana@example.com", "caio@example.com"]
    # O envio que falhou é desfeito e tentado de novo na próxima execução
    assert stored_alert(db_session, habits[1], users[1]).last_sent_at is None
    assert stored_alert(db_session, habits[1], users[1]).last_evaluated_at is None
    lines = [record.getMessage() for record in caplog.records]
    assert (
        f"alerta do hábito {habits[1].id} (usuário {users[1].id}) não enviado; "
        "nova tentativa na próxima execução"
    ) in lines
    assert all("bia@" not in line and "Exercício" not in line for line in lines)

    assert run(WEDNESDAY_8 + HOUR, mailer=Mailer(settings, smtp_server.backend())).sent == 1
    assert len(smtp_server.received) == 3


def test_release_keeps_a_config_saved_during_the_send(db_session, settings, engine, outbox, run):
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={})
    saved_at = WEDNESDAY_8 + timedelta(seconds=30)

    class SaveWhileSending:
        def send(self, message: EmailMessage) -> None:
            # O usuário salva a configuração enquanto o email sai, e o envio falha
            with create_session_factory(engine)() as other:
                service.save_alert(
                    other,
                    user_id=ana.id,
                    habit_id=habit.id,
                    values=CONFIG | {"hour": 10},
                    ip=None,
                    now=saved_at,
                )
            raise ConnectionError

    assert run(mailer=Mailer(settings, SaveWhileSending())).failed == 1

    alert = stored_alert(db_session, habit, ana)
    # O envio volta a "não enviado"; a âncora do salvar fica
    assert (alert.hour, alert.last_sent_at, alert.last_evaluated_at) == (10, None, saved_at)
    # A nova hora, mais tarde no mesmo dia, ainda manda o email
    assert run(WEDNESDAY_8 + HOUR).evaluated == 0
    assert run(WEDNESDAY_8 + 2 * HOUR).sent == 1


@pytest.mark.parametrize("recreate", [False, True])
def test_release_after_the_alert_was_deleted(db_session, settings, engine, run, recreate):
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={})

    class DeleteWhileSending:
        def send(self, message: EmailMessage) -> None:
            # O alerta sai (ex.: o membro saiu do hábito) e, talvez, é salvo de novo
            with create_session_factory(engine)() as other:
                with write_transaction(other):
                    other.delete(other.get(Alert, (habit.id, ana.id)))
                if recreate:
                    service.save_alert(
                        other, user_id=ana.id, habit_id=habit.id, values=CONFIG, ip=None, now=MONDAY
                    )
            raise ConnectionError

    assert run(mailer=Mailer(settings, DeleteWhileSending())).failed == 1

    alert = stored_alert(db_session, habit, ana)
    if recreate:
        assert (alert.last_sent_at, alert.last_evaluated_at) == (None, MONDAY)
    else:
        assert alert is None


def test_unexpected_error_in_one_alert_is_logged_and_skipped(db_session, outbox, run, caplog):
    ana = make_user(db_session, timezone="Nao/Existe")
    broken = make_habit(db_session, ana, alert={})
    bia = make_user(db_session, "bia@example.com")
    make_habit(db_session, bia, alert={})

    with caplog.at_level(logging.ERROR, logger="app"):
        result = run()

    assert result == RunResult(evaluated=1, sent=1, failed=1)
    assert [message["To"] for message in outbox.messages] == ["bia@example.com"]
    [line] = [record.getMessage() for record in caplog.records]
    assert re.fullmatch(rf"alerta do hábito {broken.id} \(usuário {ana.id}\) falhou \(\w+\)", line)


def test_concurrent_run_sees_the_claim(db_session, outbox, run, engine):
    # Outra execução marcou o alerta entre a leitura inicial e a transação desta
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={})
    original = service._candidates

    def candidates_then_claim(session):
        rows = original(session)
        with create_session_factory(engine)() as other, write_transaction(other):
            other.get(Alert, (habit.id, ana.id)).last_evaluated_at = WEDNESDAY_8
        return rows

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service, "_candidates", candidates_then_claim)
        assert run() == RunResult(evaluated=0, sent=0, failed=0)
    assert outbox.messages == []


def test_parallel_runs_send_one_email(db_session, engine, outbox_mailer, outbox):
    # Duas execuções ao mesmo tempo, em threads e sessões separadas, contra o banco em arquivo
    users = [make_user(db_session, f"{name}@example.com") for name in ("ana", "bia", "caio")]
    for user in users:
        make_habit(db_session, user, alert={})
    factory = create_session_factory(engine)
    barrier = threading.Barrier(4)

    def task(_index: int) -> RunResult:
        barrier.wait()
        return run_alerts(factory, outbox_mailer, now=WEDNESDAY_8)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(task, range(4)))

    assert sum(result.sent for result in results) == 3
    assert sum(result.failed for result in results) == 0
    assert sorted(message["To"] for message in outbox.messages) == [
        "ana@example.com",
        "bia@example.com",
        "caio@example.com",
    ]


def test_alert_deleted_between_reads_is_skipped(db_session, outbox, run, engine):
    ana = make_user(db_session)
    habit = make_habit(db_session, ana, alert={})
    original = service._candidates

    def candidates_then_delete(session):
        rows = original(session)
        with create_session_factory(engine)() as other, write_transaction(other):
            other.delete(other.get(Alert, (habit.id, ana.id)))
        return rows

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service, "_candidates", candidates_then_delete)
        assert run() == RunResult(evaluated=0, sent=0, failed=0)


# --- CLI ---


def test_cli_run_alerts_exits_0_and_prints_the_counts(
    db_session, settings, database, outbox, monkeypatch, capsys
):
    ana = make_user(db_session)
    make_habit(db_session, ana, alert={})
    monkeypatch.setattr(cli, "build_backend", lambda _settings: outbox)

    with time_machine.travel(WEDNESDAY_8, tick=False):
        assert cli.main(["run-alerts"], env_for(settings)) == 0
        assert cli.main(["run-alerts"], env_for(settings)) == 0

    assert capsys.readouterr().out == (
        "run-alerts: 1 alertas avaliados, 1 emails enviados, 0 falhas\n"
        "run-alerts: 0 alertas avaliados, 0 emails enviados, 0 falhas\n"
    )
    assert len(outbox.messages) == 1


def test_cli_run_alerts_exits_0_when_one_alert_fails(
    db_session, settings, database, monkeypatch, capsys
):
    ana = make_user(db_session)
    make_habit(db_session, ana, alert={})
    monkeypatch.setattr(cli, "build_backend", lambda _settings: Refusing("ana@example.com", None))

    with time_machine.travel(WEDNESDAY_8, tick=False):
        assert cli.main(["run-alerts"], env_for(settings)) == 0

    assert capsys.readouterr().out.endswith("0 emails enviados, 1 falhas\n")


def test_cli_run_alerts_exits_1_on_a_general_error(settings, database, tmp_path, capsys):
    # Banco sem as tabelas: a leitura inicial falha
    empty = tmp_path / "vazio.db"
    empty.touch()

    assert cli.main(["run-alerts"], env_for(settings) | {"DATABASE_PATH": str(empty)}) == 1
    assert capsys.readouterr().err.startswith("erro: falha no banco de dados (OperationalError")
    # Config inválida também
    assert cli.main(["run-alerts"], env_for(settings) | {"APP_URL": ""}) == 1
