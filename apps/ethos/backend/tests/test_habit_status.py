"""Pausar, retomar, arquivar e desarquivar hábitos (ETH-21)."""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from sqlalchemy import select

from app.audit import AuditEvent
from app.db import create_session_factory
from app.errors import ApiError
from app.habits import service
from app.habits.access import HabitAccess, HabitRole, require_writable
from app.main import create_app
from app.models import Habit, HabitPause
from tests.factories import count, new_habit, new_mark, new_pause, save
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
# Quarta-feira
NOW = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
# Segunda-feira: a semana da criação (2 a 8 de fevereiro) é a primeira da pontuação
CREATED = datetime(2026, 2, 2, 13, 0, tzinfo=UTC)
ACTIONS = ("pause", "resume", "archive", "unarchive")
ARCHIVED = {"error": "habit_archived", "field": None}
LIMIT_REACHED = {"error": "habit_limit_reached", "field": None}
STATUS_EVENTS = (
    AuditEvent.HABIT_PAUSED,
    AuditEvent.HABIT_RESUMED,
    AuditEvent.HABIT_ARCHIVED,
    AuditEvent.HABIT_UNARCHIVED,
)


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
    return make_account("bia@example.com")


def act(client, account: Account, habit_id: int, action: str):
    return client.post(f"/habits/{habit_id}/{action}", headers=account.headers)


def done(client, account: Account, habit_id: int, action: str) -> dict:
    response = act(client, account, habit_id, action)
    assert response.status_code == 200, response.json()
    return response.json()


def pauses(db_session, habit_id: int) -> list[tuple[datetime, datetime | None]]:
    db_session.rollback()
    query = (
        select(HabitPause.started_at, HabitPause.ended_at)
        .where(HabitPause.habit_id == habit_id)
        .order_by(HabitPause.id)
    )
    return [tuple(row) for row in db_session.execute(query)]


def status_events(db_session) -> list[str]:
    return [entry.event for name in STATUS_EVENTS for entry in events(db_session, name)]


def scored_habit(db_session, owner: Account, *marks: datetime, **fields) -> Habit:
    """Hábito semanal "pelo menos 1", com pontuação, criado em `CREATED` e com as marcações."""
    habit = new_habit(
        owner.user,
        **(
            {"score_enabled": True, "goal_type": "min", "goal_count": 1, "created_at": CREATED}
            | fields
        ),
    )
    save(db_session, habit)
    save(db_session, *[new_mark(habit, instant) for instant in marks])
    return habit


def score_of(client, account: Account, habit_id: int) -> dict:
    return client.get(f"/habits/{habit_id}", headers=account.headers).json()["score"]


def at(day: int, month: int = 3) -> datetime:
    return datetime(2026, month, day, 12, 0, tzinfo=UTC)


# --- pausar e retomar ---


def test_pause_and_resume(client, ana, db_session, clock):
    habit = created(client, ana)

    paused = done(client, ana, habit["id"], "pause")

    assert paused == habit | {"status": "paused"}
    assert stored(db_session, habit["id"]).status == "paused"
    assert pauses(db_session, habit["id"]) == [(NOW, None)]
    [entry] = events(db_session, AuditEvent.HABIT_PAUSED)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        ana.user.id,
        habit["id"],
        IP,
        {},
    )

    clock.shift(timedelta(days=2))
    resumed = done(client, ana, habit["id"], "resume")

    assert resumed["status"] == "active"
    assert resumed["updated_at"] == "2026-03-27T12:00:00Z"
    assert pauses(db_session, habit["id"]) == [(NOW, NOW + timedelta(days=2))]
    [entry] = events(db_session, AuditEvent.HABIT_RESUMED)
    assert (entry.user_id, entry.habit_id, entry.ip) == (ana.user.id, habit["id"], IP)


def test_pause_twice_keeps_one_open_interval(client, ana, db_session, clock):
    habit = created(client, ana)
    done(client, ana, habit["id"], "pause")
    clock.shift(timedelta(hours=1))

    again = done(client, ana, habit["id"], "pause")

    assert again["status"] == "paused"
    # Nada mudou: nem o intervalo, nem o updated_at, nem a auditoria
    assert again["updated_at"] == habit["updated_at"]
    assert pauses(db_session, habit["id"]) == [(NOW, None)]
    assert status_events(db_session) == ["habit_paused"]


def test_resume_active_changes_nothing(client, ana, db_session):
    habit = created(client, ana)

    assert done(client, ana, habit["id"], "resume") == habit
    assert pauses(db_session, habit["id"]) == []
    assert status_events(db_session) == []


def test_repeated_pause_and_resume_record_each_interval(client, ana, db_session, clock):
    habit = created(client, ana)
    expected = []
    for _ in range(3):
        start = datetime.now(UTC)
        done(client, ana, habit["id"], "pause")
        clock.shift(timedelta(days=3))
        done(client, ana, habit["id"], "resume")
        expected.append((start, start + timedelta(days=3)))
        clock.shift(timedelta(days=1))

    done(client, ana, habit["id"], "pause")

    assert pauses(db_session, habit["id"]) == [*expected, (NOW + timedelta(days=12), None)]
    assert stored(db_session, habit["id"]).status == "paused"
    assert status_events(db_session) == ["habit_paused"] * 4 + ["habit_resumed"] * 3


def test_resume_paused_habit_without_open_pause(client, ana, db_session):
    # Status pausado sem a linha da pausa (dado montado fora da API): retomar só volta a ativo
    habit = new_habit(ana.user, status="paused")
    save(db_session, habit)

    assert done(client, ana, habit.id, "resume")["status"] == "active"
    assert pauses(db_session, habit.id) == []


def test_resume_never_ends_a_pause_before_it_started(client, ana, db_session):
    # Relógio que voltou: a pausa começou "depois" de agora. O intervalo fica com duração zero
    habit = new_habit(ana.user, status="paused")
    save(db_session, habit)
    later = NOW + timedelta(hours=1)
    save(db_session, new_pause(habit, later))

    assert done(client, ana, habit.id, "resume")["status"] == "active"
    assert pauses(db_session, habit.id) == [(later, later)]


def test_parallel_pauses_open_one_interval(engine, db_session, ana):
    habit = new_habit(ana.user)
    save(db_session, habit)
    factory = create_session_factory(engine)
    calls = 6
    barrier = threading.Barrier(calls)

    def task(_index):
        with factory() as session:
            barrier.wait()
            access = service.pause_habit(session, user_id=ana.user.id, habit_id=habit.id, ip=None)
            return access.habit.status

    with ThreadPoolExecutor(max_workers=calls) as executor:
        results = list(executor.map(task, range(calls)))

    assert results == ["paused"] * calls
    assert pauses(db_session, habit.id) == [(NOW, None)]
    assert len(events(db_session, AuditEvent.HABIT_PAUSED)) == 1


def test_paused_periods_are_left_out_of_the_score(client, ana, db_session, clock):
    # Semanas consideradas em 25/03: da criação (2/02) até a atual (23/03), 8. Marcadas: as 4
    # de fevereiro e a atual
    marks = (at(3, 2), at(10, 2), at(17, 2), at(24, 2), at(24))
    habit = scored_habit(db_session, ana, *marks)
    control = scored_habit(db_session, ana, *marks)

    # Pausado de 2/03 (segunda) a 21/03 (sábado): as semanas de 2, 9 e 16/03 saem da conta
    clock.move_to(at(2))
    done(client, ana, habit.id, "pause")
    clock.move_to(at(21))
    done(client, ana, habit.id, "resume")
    clock.move_to(NOW)

    assert score_of(client, ana, habit.id) == {"value": 100, "success": True}
    # 5 de 8 = 62,5
    assert score_of(client, ana, control.id) == {"value": 63, "success": False}


def test_paused_habit_is_still_writable(ana):
    # Pausado continua marcável: a checagem de escrita das marcações (ETH-22) deixa passar
    for status in ("active", "paused"):
        habit = new_habit(ana.user, status=status)
        assert require_writable(HabitAccess(habit, HabitRole.EDITOR)) is habit


# --- arquivar e desarquivar ---


def test_archive_and_unarchive(client, ana, db_session, clock):
    habit = created(client, ana)

    archived = done(client, ana, habit["id"], "archive")

    assert archived == habit | {"status": "archived", "archived_at": "2026-03-25T12:00:00Z"}
    stored_habit = stored(db_session, habit["id"])
    assert (stored_habit.status, stored_habit.archived_at) == ("archived", NOW)
    [entry] = events(db_session, AuditEvent.HABIT_ARCHIVED)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        ana.user.id,
        habit["id"],
        IP,
        {},
    )

    clock.shift(timedelta(days=10))
    unarchived = done(client, ana, habit["id"], "unarchive")

    assert (unarchived["status"], unarchived["archived_at"]) == ("active", None)
    # O tempo arquivado (sem poder marcar) vira pausa: não conta como meta não cumprida
    assert pauses(db_session, habit["id"]) == [(NOW, NOW + timedelta(days=10))]
    [entry] = events(db_session, AuditEvent.HABIT_UNARCHIVED)
    assert (entry.user_id, entry.habit_id, entry.ip) == (ana.user.id, habit["id"], IP)


def test_unarchive_in_the_same_instant_records_no_pause(client, ana, db_session):
    habit = created(client, ana)
    done(client, ana, habit["id"], "archive")

    assert done(client, ana, habit["id"], "unarchive")["status"] == "active"
    assert pauses(db_session, habit["id"]) == []


def test_archive_paused_habit_comes_back_paused(client, ana, db_session, clock):
    habit = created(client, ana)
    done(client, ana, habit["id"], "pause")
    clock.shift(timedelta(days=1))
    archived = done(client, ana, habit["id"], "archive")
    clock.shift(timedelta(days=1))

    unarchived = done(client, ana, habit["id"], "unarchive")
    clock.shift(timedelta(days=1))
    done(client, ana, habit["id"], "resume")

    assert archived["status"] == "archived"
    assert (unarchived["status"], unarchived["archived_at"]) == ("paused", None)
    # Uma pausa só, do pausar ao retomar, cobrindo o tempo arquivado
    assert pauses(db_session, habit["id"]) == [(NOW, NOW + timedelta(days=3))]
    assert status_events(db_session) == [
        "habit_paused",
        "habit_resumed",
        "habit_archived",
        "habit_unarchived",
    ]


def test_archive_twice_keeps_the_first_date(client, ana, db_session, clock):
    habit = created(client, ana)
    done(client, ana, habit["id"], "archive")
    clock.shift(timedelta(days=1))

    again = done(client, ana, habit["id"], "archive")

    assert again["archived_at"] == "2026-03-25T12:00:00Z"
    assert stored(db_session, habit["id"]).archived_at == NOW
    assert status_events(db_session) == ["habit_archived"]


def test_unarchive_not_archived_changes_nothing(client, ana, db_session):
    # Nem confere o limite: o hábito já conta nele
    save(db_session, *[new_habit(ana.user) for _ in range(9)])
    habit = created(client, ana)

    assert done(client, ana, habit["id"], "unarchive") == habit
    assert status_events(db_session) == []


def test_score_frozen_after_archive_while_time_passes(client, ana, db_session, clock):
    # Cumpridas as semanas de 2, 9, 16 e 23/02 (esta na terça, antes do arquivamento)
    habit = scored_habit(db_session, ana, at(3, 2), at(10, 2), at(17, 2), at(24, 2))
    clock.move_to(at(25, 2))
    done(client, ana, habit.id, "archive")

    # Arquivado numa quarta (25/02): a semana de 23/02 é a "atual", com o valor até ali
    expected = {"value": 100, "success": True}
    for instant in (at(25, 2), NOW, NOW + timedelta(days=50)):
        clock.move_to(instant)
        assert score_of(client, ana, habit.id) == expected
        listed = client.get("/habits?archived=true", headers=ana.headers).json()["habits"]
        assert listed[0]["score"] == expected


def test_score_without_archive_keeps_counting(client, ana, db_session):
    # Contraprova do teste acima: sem arquivar, as semanas vazias de 2/03 a 23/03 entram
    habit = scored_habit(db_session, ana, at(3, 2), at(10, 2), at(17, 2), at(24, 2))
    assert score_of(client, ana, habit.id) == {"value": 50, "success": False}


def test_unarchived_time_stays_out_of_the_score(client, ana, db_session, clock):
    habit = scored_habit(db_session, ana, at(3, 2), at(10, 2), at(17, 2))
    clock.move_to(at(25, 2))
    done(client, ana, habit.id, "archive")
    clock.move_to(at(18))
    done(client, ana, habit.id, "unarchive")

    # Semanas de 23/02 a 16/03 pausadas (o tempo arquivado); a de 23/03 é a atual, ainda sem
    # marcação: 3 de 4
    clock.move_to(NOW)
    assert score_of(client, ana, habit.id) == {"value": 75, "success": True}
    # Uma semana depois, a de 30/03 também conta (sem marcação): 3 de 5
    clock.move_to(NOW + timedelta(days=7))
    assert score_of(client, ana, habit.id) == {"value": 60, "success": False}


# --- limite de hábitos ao desarquivar ---


def test_unarchive_with_ten_active_is_refused(client, ana, db_session):
    save(db_session, *[new_habit(ana.user) for _ in range(10)])
    habit = new_habit(ana.user, status="archived", archived_at=NOW - timedelta(days=1))
    save(db_session, habit)

    response = act(client, ana, habit.id, "unarchive")

    assert response.status_code == 409
    assert response.json() == LIMIT_REACHED
    assert stored(db_session, habit.id).status == "archived"
    assert pauses(db_session, habit.id) == []
    assert status_events(db_session) == []


def test_unarchive_limit_counts_paused_and_frees_up_after_archive(client, ana, db_session):
    save(db_session, *[new_habit(ana.user) for _ in range(9)])
    paused = created(client, ana)
    done(client, ana, paused["id"], "pause")
    habit = new_habit(ana.user, status="archived", archived_at=NOW)
    save(db_session, habit)

    assert act(client, ana, habit.id, "unarchive").json() == LIMIT_REACHED

    done(client, ana, paused["id"], "archive")
    assert done(client, ana, habit.id, "unarchive")["status"] == "active"


def test_unarchive_limit_follows_config(make_settings, database, make_client, ana, db_session):
    client = make_client(create_app(make_settings(database_path=database, max_habits_per_user=1)))
    first, second = (new_habit(ana.user, status="archived", archived_at=NOW) for _ in range(2))
    save(db_session, first, second)

    assert done(client, ana, first.id, "unarchive")["status"] == "active"
    assert act(client, ana, second.id, "unarchive").json() == LIMIT_REACHED


def test_parallel_unarchive_never_passes_the_limit(engine, db_session, settings, ana):
    save(db_session, *[new_habit(ana.user) for _ in range(8)])
    archived = [new_habit(ana.user, status="archived", archived_at=NOW) for _ in range(5)]
    save(db_session, *archived)
    factory = create_session_factory(engine)
    barrier = threading.Barrier(len(archived))

    def task(habit_id):
        with factory() as session:
            barrier.wait()
            try:
                service.unarchive_habit(
                    session, settings, user_id=ana.user.id, habit_id=habit_id, ip=None
                )
            except ApiError as error:
                return error.code.value
            return "unarchived"

    with ThreadPoolExecutor(max_workers=len(archived)) as executor:
        results = list(executor.map(task, [habit.id for habit in archived]))

    assert sorted(results) == ["habit_limit_reached"] * 3 + ["unarchived"] * 2
    db_session.rollback()
    assert count(db_session, Habit, Habit.status == "active") == 10


# --- arquivado é só leitura ---


def test_archived_habit_is_read_only(client, ana, db_session):
    habit = created(client, ana)
    archived = done(client, ana, habit["id"], "archive")

    patched = client.patch(f"/habits/{habit['id']}", json={"name": "Novo"}, headers=ana.headers)

    assert patched.status_code == 409
    assert patched.json() == ARCHIVED
    for action in ("pause", "resume"):
        response = act(client, ana, habit["id"], action)
        assert (response.status_code, response.json()) == (409, ARCHIVED)
    assert stored(db_session, habit["id"]).name == "Exercício"
    assert pauses(db_session, habit["id"]) == []
    assert events(db_session, AuditEvent.HABIT_UPDATED) == []
    assert status_events(db_session) == ["habit_archived"]
    # Continua visível
    assert client.get(f"/habits/{habit['id']}", headers=ana.headers).json() == archived


def test_archived_habit_can_be_deleted(client, ana, db_session):
    habit = created(client, ana)
    done(client, ana, habit["id"], "archive")

    response = client.delete(f"/habits/{habit['id']}", headers=ana.headers)

    assert response.status_code == 204
    assert stored(db_session, habit["id"]) is None


def test_require_writable_refuses_archived(ana):
    habit = new_habit(ana.user, status="archived", archived_at=NOW)
    with pytest.raises(ApiError) as caught:
        require_writable(HabitAccess(habit, HabitRole.OWNER))
    assert (caught.value.status_code, caught.value.code) == (409, "habit_archived")


# --- listagem ---


def test_archived_leave_the_main_list(client, ana, bia, db_session):
    active = created(client, ana, name="Ativo")
    paused = created(client, ana, name="Pausado")
    gone = created(client, ana, name="Arquivado")
    shared = created(client, bia, name="Da Bia, arquivado")
    share(db_session, shared["id"], ana, "viewer")
    done(client, ana, paused["id"], "pause")
    done(client, ana, gone["id"], "archive")
    done(client, bia, shared["id"], "archive")

    def names(query: str) -> list[tuple[str, str, str]]:
        response = client.get(f"/habits{query}", headers=ana.headers)
        assert response.status_code == 200
        return [(item["name"], item["status"], item["role"]) for item in response.json()["habits"]]

    main = [("Ativo", "active", "owner"), ("Pausado", "paused", "owner")]
    assert names("") == names("?archived=false") == main
    assert names("?archived=true") == [
        ("Arquivado", "archived", "owner"),
        ("Da Bia, arquivado", "archived", "viewer"),
    ]
    assert active["status"] == "active"


def test_list_archived_filter_must_be_a_boolean(client, ana):
    response = client.get("/habits?archived=talvez", headers=ana.headers)
    assert response.status_code == 422
    assert response.json() == invalid("archived")


# --- permissões ---


@pytest.mark.parametrize("role", ["editor", "viewer"])
@pytest.mark.parametrize("action", ACTIONS)
def test_members_cannot_change_status(client, ana, bia, db_session, role, action):
    habit = created(client, ana)
    share(db_session, habit["id"], bia, role)
    if action in ("resume", "unarchive"):
        done(client, ana, habit["id"], "pause" if action == "resume" else "archive")
    before = stored(db_session, habit["id"]).status

    response = act(client, bia, habit["id"], action)

    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert stored(db_session, habit["id"]).status == before


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_member_editing_archived_gets_403(client, ana, bia, db_session, role):
    # O papel vem antes: quem não pode editar não descobre nada além disso
    habit = created(client, ana)
    share(db_session, habit["id"], bia, role)
    done(client, ana, habit["id"], "archive")

    response = client.patch(f"/habits/{habit['id']}", json={"name": "X"}, headers=bia.headers)

    assert (response.status_code, response.json()) == (403, FORBIDDEN)


@pytest.mark.parametrize("action", ACTIONS)
def test_stranger_gets_404(client, ana, bia, db_session, action):
    habit = created(client, ana)

    hidden = act(client, bia, habit["id"], action)
    missing = act(client, bia, habit["id"] + 1, action)

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json() == NOT_FOUND
    assert stored(db_session, habit["id"]).status == "active"


@pytest.mark.parametrize("action", ACTIONS)
def test_requires_session(client, action):
    response = client.post(f"/habits/1/{action}")
    assert (response.status_code, response.json()) == (
        401,
        {"error": "unauthorized", "field": None},
    )


@pytest.mark.parametrize("action", ACTIONS)
def test_requires_origin(settings, database, make_client, ana, db_session, action):
    habit = new_habit(ana.user)
    save(db_session, habit)
    client = make_client(create_app(settings), origin=False)

    response = client.post(f"/habits/{habit.id}/{action}", headers=ana.headers)

    assert (response.status_code, response.json()) == (403, FORBIDDEN)
    assert status_events(db_session) == []


@pytest.mark.parametrize("action", ACTIONS)
def test_invalid_habit_id(client, ana, action):
    response = act(client, ana, 0, action)
    assert (response.status_code, response.json()) == (422, invalid("habit_id"))
