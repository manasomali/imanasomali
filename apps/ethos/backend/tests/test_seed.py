"""Dados de exemplo: `python -m app.cli seed` (ETH-22)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
import time_machine
from sqlalchemy import func, select

from app.audit import AuditEvent
from app.cli import main
from app.models import AuditLog, Habit, HabitMember, HabitPause, Mark, User
from app.seed import SEED_EMAILS
from app.terms import TERMS_VERSION
from tests.auth_helpers import cookie, open_session
from tests.factories import count, new_user, save
from tests.test_cli import env_for

NOW = datetime(2026, 3, 25, 15, 0, tzinfo=UTC)
PROD = {
    "APP_ENV": "prod",
    "APP_URL": "https://manasomali.com/ethos",
    "EMAIL_BACKEND": "smtp",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "usuario",
    "SMTP_PASSWORD": "senha",
}


@pytest.fixture(autouse=True)
def clock() -> Iterator[time_machine.Traveller]:
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def env(settings, database) -> dict[str, str]:
    return env_for(settings)


def totals(db_session) -> dict[str, int]:
    db_session.rollback()
    return {
        model.__tablename__: count(db_session, model)
        for model in (User, Habit, HabitMember, HabitPause, Mark, AuditLog)
    }


def test_seed_creates_example_data(db_session, env, capsys):
    assert main(["seed"], env) == 0

    marks = count(db_session, Mark)
    assert capsys.readouterr().out == f"seed: 3 contas, 8 hábitos e {marks} marcações criados\n"
    db_session.rollback()
    users = {user.email: user for user in db_session.scalars(select(User))}
    assert set(users) == set(SEED_EMAILS)
    assert {user.terms_version for user in users.values()} == {TERMS_VERSION}
    habits = list(db_session.scalars(select(Habit)))
    assert len(habits) == 8
    # Varia os tipos de configuração
    assert {h.multi_mark for h in habits} == {True, False}
    assert {h.goal_type for h in habits} == {"min", "max", "exact"}
    assert {h.cost_level for h in habits if h.cost_enabled} == {"habit", "mark"}
    assert {h.status for h in habits} == {"active", "paused", "archived"}
    assert any(h.duration_enabled for h in habits)
    assert any(h.notes_enabled for h in habits)
    assert any(h.score_enabled for h in habits)
    roles = set(db_session.scalars(select(HabitMember.role)))
    assert roles == {"editor", "viewer"}
    # Pausado com a pausa aberta; arquivado com a data
    for habit in habits:
        open_pauses = count(
            db_session,
            HabitPause,
            HabitPause.habit_id == habit.id,
            HabitPause.ended_at.is_(None),
        )
        assert open_pauses == (habit.status == "paused")
        assert (habit.archived_at is not None) == (habit.status == "archived")
    # Marcações no passado, de autores com acesso, com a auditoria de cada uma
    assert marks > 100
    assert db_session.scalar(select(func.max(Mark.marked_at))) < NOW
    authors = {(mark.habit_id, mark.user_id) for mark in db_session.scalars(select(Mark))}
    access = {(h.id, h.owner_id) for h in habits} | set(
        db_session.execute(
            select(HabitMember.habit_id, HabitMember.user_id).where(HabitMember.role == "editor")
        )
    )
    assert authors <= access
    assert count(db_session, AuditLog, AuditLog.event == AuditEvent.MARK_CREATED) == marks
    assert count(db_session, AuditLog, AuditLog.event == AuditEvent.HABIT_CREATED) == 8


def test_seed_marks_follow_the_habit_rules(db_session, env):
    assert main(["seed"], env) == 0

    db_session.rollback()
    habits = {habit.id: habit for habit in db_session.scalars(select(Habit))}
    timezones = dict(db_session.execute(select(User.id, User.timezone)).all())
    per_day: dict[tuple[int, object], int] = {}
    for mark in db_session.scalars(select(Mark)):
        habit = habits[mark.habit_id]
        assert (mark.duration_minutes is not None) == habit.duration_enabled
        if habit.duration_enabled:
            assert mark.duration_minutes == habit.duration_minutes
        if not habit.cost_enabled:
            assert mark.cost_cents is None
        elif habit.cost_level == "habit":
            assert mark.cost_cents == habit.cost_cents
        assert mark.note is None or habit.notes_enabled
        assert mark.marked_at >= habit.created_at
        if habit.archived_at is not None:
            assert mark.marked_at < habit.archived_at
        day = mark.marked_at.astimezone(ZoneInfo(timezones[mark.user_id])).date()
        per_day[mark.habit_id, day] = per_day.get((mark.habit_id, day), 0) + 1
    # Toggle: uma marcação por dia
    for (habit_id, _day), total in per_day.items():
        assert total == 1 or habits[habit_id].multi_mark


def test_seed_twice_changes_nothing(db_session, env, capsys):
    assert main(["seed"], env) == 0
    before = totals(db_session)
    capsys.readouterr()

    assert main(["seed"], env) == 0

    assert capsys.readouterr().out == (
        "seed: as contas de exemplo já existem; nada mudou "
        "(para recriar, apague o banco de dev e rode as migrações)\n"
    )
    assert totals(db_session) == before


def test_seed_with_one_example_account_changes_nothing(db_session, env):
    save(db_session, new_user(SEED_EMAILS[-1]))
    before = totals(db_session)

    assert main(["seed"], env) == 0

    assert totals(db_session) == before


def test_seed_keeps_other_accounts(db_session, env):
    save(db_session, new_user("outra@example.com"))

    assert main(["seed"], env) == 0

    assert count(db_session, User) == 4


def test_seed_outside_dev_fails_without_writing(db_session, env, capsys):
    before = totals(db_session)

    assert main(["seed"], env | PROD) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "erro: seed só roda com APP_ENV=dev; nada foi gravado\n"
    assert totals(db_session) == before == dict.fromkeys(before, 0)


def test_seeded_accounts_use_the_api(db_session, env, client):
    assert main(["seed"], env) == 0
    db_session.rollback()
    ana = db_session.scalar(select(User).where(User.email == SEED_EMAILS[0]))
    headers = cookie(open_session(db_session, ana))

    habits = client.get("/habits", headers=headers).json()["habits"]
    shared = next(h for h in habits if h["role"] == "viewer")
    marks = client.get(
        f"/habits/{shared['id']}/marks",
        params={"from": "2026-01-01T00:00:00Z", "to": "2026-03-26T00:00:00Z"},
        headers=headers,
    ).json()["marks"]

    # Ativos e pausados (o arquivado fica na outra lista), mais o compartilhado da Bia
    assert len(habits) == 7
    assert marks
    assert {mark["author"]["email"] for mark in marks} == {SEED_EMAILS[1]}
