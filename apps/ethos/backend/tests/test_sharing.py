"""Compartilhamento (ETH-24): convidar, cancelar, aceitar, recusar, sair, trocar papel e remover.

A matriz de permissões de todos os endpoints de hábito fica em `tests/test_permissions.py`.
"""

import statistics
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from sqlalchemy import Engine, event, select

from app.audit import AuditEvent
from app.db import create_session_factory
from app.errors import ApiError
from app.main import create_app
from app.models import Alert, AuditLog, HabitInvite, HabitMember, Mark, MemberRole
from app.sharing import service
from app.sharing.quota import INVITE_WINDOW
from tests.factories import (
    count,
    new_alert,
    new_habit,
    new_invite,
    new_mark,
    new_member,
    save,
)
from tests.habit_helpers import (
    NOT_FOUND,
    Account,
    create,
    created,
    events,
    invalid,
    share,
    stored,
)

IP = "203.0.113.7"
NOW = datetime(2026, 3, 25, 15, 0, tzinfo=UTC)
SENT = {"status": "sent"}
ARCHIVED = {"error": "habit_archived", "field": None}
INVITE_LIMIT = {"error": "invite_limit_reached", "field": None}
GUEST_LIMIT = {"error": "guest_limit_reached", "field": None}
SHARED_LIMIT = {"error": "shared_habit_limit_reached", "field": None}


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
    return make_account("bia@example.com", locale="en")


@pytest.fixture
def caio(make_account) -> Account:
    return make_account("caio@example.com")


@pytest.fixture
def habit_id(client, ana) -> int:
    return created(client, ana)["id"]


def invite(client, account: Account, habit_id: int, email: str, role: str = "editor"):
    body = {"email": email, "role": role}
    return client.post(f"/habits/{habit_id}/invites", json=body, headers=account.headers)


def invited(client, account: Account, habit_id: int, email: str, role: str = "editor") -> None:
    response = invite(client, account, habit_id, email, role)
    assert (response.status_code, response.json()) == (202, SENT)


def pending(db_session, habit_id: int) -> list[HabitInvite]:
    db_session.rollback()
    query = select(HabitInvite).where(HabitInvite.habit_id == habit_id).order_by(HabitInvite.id)
    return list(db_session.scalars(query.execution_options(populate_existing=True)))


def members(db_session, habit_id: int) -> dict[int, str]:
    db_session.rollback()
    query = select(HabitMember).where(HabitMember.habit_id == habit_id)
    rows = db_session.scalars(query.execution_options(populate_existing=True))
    return {row.user_id: row.role for row in rows}


def alerts(db_session, user_id: int) -> list[int]:
    db_session.rollback()
    query = select(Alert.habit_id).where(Alert.user_id == user_id).order_by(Alert.habit_id)
    return list(db_session.scalars(query))


def invite_id_for(db_session, habit_id: int, email: str) -> int:
    [row] = [row for row in pending(db_session, habit_id) if row.email == email]
    return row.id


def members_of(db_session, user_id: int) -> list[int]:
    db_session.rollback()
    query = select(HabitMember.habit_id).where(HabitMember.user_id == user_id)
    return list(db_session.scalars(query))


def accept(client, account: Account, invite_id: int):
    return client.post(f"/invites/{invite_id}/accept", headers=account.headers)


def decline(client, account: Account, invite_id: int):
    return client.post(f"/invites/{invite_id}/decline", headers=account.headers)


def owned_habit(db_session, owner: Account, **fields) -> int:
    habit = new_habit(owner.user, **fields)
    save(db_session, habit)
    return habit.id


# --- convidar ---


def test_invite_with_account(client, ana, bia, habit_id, outbox, db_session):
    outbox.messages.clear()

    response = invite(client, ana, habit_id, "  BIA@example.com ", "viewer")

    assert (response.status_code, response.json()) == (202, SENT)
    [row] = pending(db_session, habit_id)
    assert (row.email, row.invited_user_id, row.role, row.created_at) == (
        "bia@example.com",
        bia.user.id,
        "viewer",
        NOW,
    )
    [entry] = events(db_session, AuditEvent.INVITE_CREATED)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        ana.user.id,
        habit_id,
        IP,
        {"invite_id": row.id, "role": "viewer"},
    )
    # O email vai no idioma do convidado, com quem convidou e o papel
    [message] = outbox.to("bia@example.com")
    assert message["Subject"] == "You've been invited on ethos"
    text = message.get_body(preferencelist=("plain",)).get_content()
    assert "ana@example.com" in text
    assert "Exercício" in text


def test_invite_without_account(client, ana, habit_id, outbox, db_session):
    outbox.messages.clear()

    response = invite(client, ana, habit_id, "ninguem@example.com")

    assert (response.status_code, response.json()) == (202, SENT)
    [row] = pending(db_session, habit_id)
    assert (row.email, row.invited_user_id, row.role) == ("ninguem@example.com", None, "editor")
    assert len(events(db_session, AuditEvent.INVITE_CREATED)) == 1
    assert outbox.messages == []


def test_invite_to_blocked_account_stays_pending_without_email(
    client, ana, habit_id, outbox, make_account, db_session
):
    blocked = make_account("bloq@example.com", is_active=False)
    outbox.messages.clear()

    invited(client, ana, habit_id, "bloq@example.com")

    [row] = pending(db_session, habit_id)
    assert row.invited_user_id == blocked.user.id
    assert outbox.messages == []


def test_same_response_with_and_without_account(client, ana, bia, db_session):
    with_account = owned_habit(db_session, ana)
    without_account = owned_habit(db_session, ana)

    first = invite(client, ana, with_account, "bia@example.com")
    second = invite(client, ana, without_account, "ninguem@example.com")

    assert first.status_code == second.status_code == 202
    assert first.content == second.content
    assert dict(first.headers) == dict(second.headers)


@pytest.fixture
def statements() -> Iterator[list[str]]:
    """O SQL executado (em qualquer engine) durante o teste."""
    executed: list[str] = []

    def listener(_conn, _cursor, statement, *_args) -> None:
        executed.append(statement)

    event.listen(Engine, "before_cursor_execute", listener)
    try:
        yield executed
    finally:
        event.remove(Engine, "before_cursor_execute", listener)


def test_same_work_with_and_without_account(make_settings, ana, bia, db_session, statements):
    settings = make_settings()
    habits = [owned_habit(db_session, ana), owned_habit(db_session, ana)]
    executed = []
    for habit, email in zip(habits, ["bia@example.com", "ninguem@example.com"], strict=True):
        statements.clear()
        service.invite(
            db_session,
            settings,
            owner_id=ana.user.id,
            habit_id=habit,
            email=email,
            role=MemberRole.EDITOR,
            ip=None,
        )
        executed.append(list(statements))

    # As mesmas consultas e escritas, com o mesmo SQL, nos dois ramos
    assert executed[0] == executed[1]
    assert any(statement.startswith("INSERT INTO habit_invites") for statement in executed[0])


def test_same_time_with_and_without_account(make_settings, make_account, ana, db_session):
    settings = make_settings(max_guests_per_habit=100, max_invites_per_day=1000)
    habit = owned_habit(db_session, ana)
    rounds = 15
    for index in range(rounds):
        make_account(f"conta{index}@example.com")

    def timed(email: str) -> float:
        start = time.perf_counter()
        service.invite(
            db_session,
            settings,
            owner_id=ana.user.id,
            habit_id=habit,
            email=email,
            role=MemberRole.VIEWER,
            ip=None,
        )
        return time.perf_counter() - start

    # Alternados, para que ruído do sistema pese igual nos dois
    with_account, without_account = [], []
    for index in range(rounds):
        with_account.append(timed(f"conta{index}@example.com"))
        without_account.append(timed(f"semconta{index}@example.com"))

    fast, slow = sorted([statistics.median(with_account), statistics.median(without_account)])
    assert slow <= fast * 1.5 + 0.002


def test_invite_is_never_delivered_to_account_created_later(
    client, ana, habit_id, make_account, db_session
):
    invited(client, ana, habit_id, "depois@example.com")
    [row] = pending(db_session, habit_id)
    later = make_account("depois@example.com")

    listing = client.get("/invites", headers=later.headers)
    accepted = accept(client, later, row.id)
    declined = decline(client, later, row.id)

    assert listing.json() == {"invites": []}
    assert (accepted.status_code, accepted.json()) == (404, NOT_FOUND)
    assert (declined.status_code, declined.json()) == (404, NOT_FOUND)
    # Continua pendente, sem conta, para sempre (até o dono cancelar)
    [still] = pending(db_session, habit_id)
    assert (still.id, still.invited_user_id) == (row.id, None)
    assert members(db_session, habit_id) == {}


def test_inviting_self_member_or_pending_changes_nothing(
    client, ana, bia, caio, habit_id, outbox, db_session
):
    share(db_session, habit_id, bia, "viewer")
    invited(client, ana, habit_id, "caio@example.com", "viewer")
    outbox.messages.clear()

    for email, role in [
        ("ana@example.com", "editor"),
        ("bia@example.com", "editor"),
        ("caio@example.com", "editor"),
    ]:
        invited(client, ana, habit_id, email, role)

    [row] = pending(db_session, habit_id)
    assert (row.email, row.role) == ("caio@example.com", "viewer")
    assert members(db_session, habit_id) == {bia.user.id: "viewer"}
    assert len(events(db_session, AuditEvent.INVITE_CREATED)) == 1
    assert outbox.messages == []


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "sem-arroba", "role": "editor"}, "email"),
        ({"email": "a@b.co", "role": "owner"}, "role"),
        ({"email": "a@b.co"}, "role"),
        ({"role": "editor"}, "email"),
        ({"email": "a@b.co", "role": "editor", "extra": 1}, "extra"),
    ],
)
def test_invite_validation(client, ana, habit_id, db_session, body, field):
    response = client.post(f"/habits/{habit_id}/invites", json=body, headers=ana.headers)

    assert (response.status_code, response.json()) == (422, invalid(field))
    assert pending(db_session, habit_id) == []


def test_invite_to_archived_habit_is_refused(client, ana, habit_id, db_session):
    client.post(f"/habits/{habit_id}/archive", headers=ana.headers)

    response = invite(client, ana, habit_id, "bia@example.com")

    assert (response.status_code, response.json()) == (409, ARCHIVED)
    assert pending(db_session, habit_id) == []


# --- limites de convidados e de convites ---


def test_sixth_guest_is_refused_and_pending_counts(client, ana, bia, caio, habit_id, db_session):
    share(db_session, habit_id, bia, "editor")
    share(db_session, habit_id, caio, "viewer")
    for index in range(3):
        invited(client, ana, habit_id, f"convidado{index}@example.com")

    refused = invite(client, ana, habit_id, "sexto@example.com")

    assert (refused.status_code, refused.json()) == (409, GUEST_LIMIT)
    assert len(pending(db_session, habit_id)) == 3
    # Cancelar um pendente libera a vaga
    first = pending(db_session, habit_id)[0].id
    client.delete(f"/habits/{habit_id}/invites/{first}", headers=ana.headers)
    invited(client, ana, habit_id, "sexto@example.com")


def test_guest_limit_is_per_habit(client, ana, db_session):
    full = owned_habit(db_session, ana)
    other = owned_habit(db_session, ana)
    for index in range(5):
        invited(client, ana, full, f"convidado{index}@example.com")

    invited(client, ana, other, "convidado0@example.com")


def test_twenty_first_invite_of_the_day_is_refused(client, ana, clock, db_session):
    # 5 por hábito (MAX_GUESTS_PER_HABIT): o limite do dia soma todos os hábitos do dono
    habits = [owned_habit(db_session, ana) for _ in range(4)]
    for index in range(20):
        clock.shift(timedelta(minutes=1))
        invited(client, ana, habits[index // 5], f"convidado{index}@example.com")
    fresh = owned_habit(db_session, ana)

    refused = invite(client, ana, fresh, "vinte-e-um@example.com")

    assert (refused.status_code, refused.json()) == (409, INVITE_LIMIT)
    assert pending(db_session, fresh) == []
    # Cancelar não devolve o convite do dia
    cancelled = pending(db_session, habits[0])[0].id
    client.delete(f"/habits/{habits[0]}/invites/{cancelled}", headers=ana.headers)
    assert invite(client, ana, fresh, "vinte-e-um@example.com").json() == INVITE_LIMIT
    # Janela móvel de 24 h: o primeiro convite sai dela e libera uma vaga só
    clock.move_to(NOW + timedelta(minutes=1, seconds=1) + INVITE_WINDOW)
    invited(client, ana, fresh, "vinte-e-um@example.com")
    assert invite(client, ana, fresh, "vinte-e-dois@example.com").json() == INVITE_LIMIT


def test_invite_limit_is_per_owner(make_app_client, ana, bia, db_session):
    client = make_app_client(max_invites_per_day=1)
    invited(client, ana, owned_habit(db_session, ana), "x@example.com")

    invited(client, bia, owned_habit(db_session, bia), "x@example.com")


def test_invite_limit_survives_habit_deletion(make_app_client, ana, clock, db_session):
    client = make_app_client(max_invites_per_day=3)
    doomed = owned_habit(db_session, ana)
    for index in range(3):
        invited(client, ana, doomed, f"convidado{index}@example.com")
    clock.shift(timedelta(hours=1))
    assert client.delete(f"/habits/{doomed}", headers=ana.headers).status_code == 204
    other = owned_habit(db_session, ana)

    refused = invite(client, ana, other, "outro@example.com")

    assert refused.json() == INVITE_LIMIT
    [entry] = events(db_session, AuditEvent.HABIT_DELETED)
    assert entry.details == {"habit_id": doomed, "recent_invites": 3}
    # Conservador: contam até 24 h depois da exclusão
    clock.move_to(NOW + INVITE_WINDOW + timedelta(minutes=30))
    assert invite(client, ana, other, "outro@example.com").json() == INVITE_LIMIT
    clock.move_to(NOW + INVITE_WINDOW + timedelta(hours=1, seconds=1))
    invited(client, ana, other, "outro@example.com")


def test_deleting_habit_carries_only_invites_in_the_window(client, ana, clock, db_session):
    old = owned_habit(db_session, ana)
    invited(client, ana, old, "antigo@example.com")
    clock.shift(INVITE_WINDOW + timedelta(seconds=1))

    client.delete(f"/habits/{old}", headers=ana.headers)

    [entry] = events(db_session, AuditEvent.HABIT_DELETED)
    assert entry.details == {"habit_id": old}


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


def test_parallel_invites_respect_the_limits(make_settings, engine, ana, db_session):
    settings = make_settings(max_invites_per_day=2)
    habit = owned_habit(db_session, ana)
    owner_id = ana.user.id

    def action(session, index: int) -> Any:
        return service.invite(
            session,
            settings,
            owner_id=owner_id,
            habit_id=habit,
            email=f"paralelo{index}@example.com",
            role=MemberRole.EDITOR,
            ip=None,
        )

    results = run_parallel(engine, 5, action)

    assert sorted(map(str, results)) == ["None", "None"] + ["invite_limit_reached"] * 3
    assert len(pending(db_session, habit)) == 2


def test_parallel_accepts_respect_the_shared_limit(make_settings, engine, ana, bia, db_session):
    settings = make_settings(max_shared_habits_per_user=1)
    invites = []
    for _ in range(4):
        habit = new_habit(ana.user)
        save(db_session, habit)
        row = new_invite(habit, "bia@example.com", invited_user_id=bia.user.id)
        save(db_session, row)
        invites.append(row.id)
    user_id = bia.user.id

    def action(session, index: int) -> Any:
        access = service.accept_invite(
            session, settings, user_id=user_id, invite_id=invites[index], ip=None
        )
        return access.role.value

    results = run_parallel(engine, 4, action)

    assert sorted(results) == ["editor"] + ["shared_habit_limit_reached"] * 3
    assert count(db_session, HabitMember, HabitMember.user_id == user_id) == 1


# --- convites: listar, aceitar, recusar, cancelar ---


def test_owner_lists_pending_invites_without_revealing_accounts(client, ana, bia, habit_id):
    invited(client, ana, habit_id, "bia@example.com", "viewer")
    invited(client, ana, habit_id, "ninguem@example.com")

    response = client.get(f"/habits/{habit_id}/invites", headers=ana.headers)

    assert response.status_code == 200
    body = response.json()
    assert [
        {key: invite[key] for key in ("email", "role", "created_at")} for invite in body["invites"]
    ] == [
        {"email": "bia@example.com", "role": "viewer", "created_at": "2026-03-25T15:00:00Z"},
        {"email": "ninguem@example.com", "role": "editor", "created_at": "2026-03-25T15:00:00Z"},
    ]
    assert all(set(invite) == {"id", "email", "role", "created_at"} for invite in body["invites"])


def test_received_invites_are_only_mine(client, ana, bia, caio, db_session):
    first = owned_habit(db_session, ana, name="Ler", color="violet")
    second = owned_habit(db_session, caio, name="Correr")
    invited(client, ana, first, "bia@example.com", "viewer")
    invited(client, caio, second, "bia@example.com")
    invited(client, ana, first, "caio@example.com")

    response = client.get("/invites", headers=bia.headers)

    assert response.status_code == 200
    invites = response.json()["invites"]
    assert [
        (item["habit"], item["owner"], item["role"], item["created_at"]) for item in invites
    ] == [
        (
            {"id": first, "name": "Ler", "color": "violet"},
            {"id": ana.user.id, "email": "ana@example.com"},
            "viewer",
            "2026-03-25T15:00:00Z",
        ),
        (
            {"id": second, "name": "Correr", "color": "teal"},
            {"id": caio.user.id, "email": "caio@example.com"},
            "editor",
            "2026-03-25T15:00:00Z",
        ),
    ]
    assert [item["id"] for item in invites] == [
        invite_id_for(db_session, first, "bia@example.com"),
        invite_id_for(db_session, second, "bia@example.com"),
    ]


def test_accept_makes_member_and_removes_invite(client, ana, bia, habit_id, db_session):
    invited(client, ana, habit_id, "bia@example.com", "viewer")
    invite_id = invite_id_for(db_session, habit_id, "bia@example.com")

    response = accept(client, bia, invite_id)

    assert response.status_code == 200
    assert (response.json()["id"], response.json()["role"]) == (habit_id, "viewer")
    assert members(db_session, habit_id) == {bia.user.id: "viewer"}
    assert pending(db_session, habit_id) == []
    [entry] = events(db_session, AuditEvent.INVITE_ACCEPTED)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        bia.user.id,
        habit_id,
        IP,
        {"invite_id": invite_id, "role": "viewer"},
    )
    habits = client.get("/habits", headers=bia.headers).json()["habits"]
    assert [(habit["id"], habit["role"]) for habit in habits] == [(habit_id, "viewer")]
    assert client.get("/invites", headers=bia.headers).json() == {"invites": []}
    # Aceitar de novo: o convite não existe mais
    assert accept(client, bia, invite_id).json() == NOT_FOUND


def test_decline_removes_invite(client, ana, bia, habit_id, db_session):
    invited(client, ana, habit_id, "bia@example.com")
    invite_id = invite_id_for(db_session, habit_id, "bia@example.com")

    response = decline(client, bia, invite_id)

    assert response.status_code == 204
    assert pending(db_session, habit_id) == []
    assert members(db_session, habit_id) == {}
    [entry] = events(db_session, AuditEvent.INVITE_DECLINED)
    assert (entry.user_id, entry.habit_id, entry.details) == (
        bia.user.id,
        habit_id,
        {"invite_id": invite_id, "role": "editor"},
    )
    assert client.get(f"/habits/{habit_id}", headers=bia.headers).json() == NOT_FOUND
    # Depois de recusar, o dono pode convidar de novo
    invited(client, ana, habit_id, "bia@example.com")
    assert len(pending(db_session, habit_id)) == 1


def test_cancel_removes_invite(client, ana, bia, habit_id, db_session):
    invited(client, ana, habit_id, "bia@example.com")
    invite_id = invite_id_for(db_session, habit_id, "bia@example.com")

    response = client.delete(f"/habits/{habit_id}/invites/{invite_id}", headers=ana.headers)

    assert response.status_code == 204
    assert pending(db_session, habit_id) == []
    [entry] = events(db_session, AuditEvent.INVITE_CANCELED)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        ana.user.id,
        habit_id,
        IP,
        {"invite_id": invite_id, "role": "editor"},
    )
    assert accept(client, bia, invite_id).json() == NOT_FOUND
    again = client.delete(f"/habits/{habit_id}/invites/{invite_id}", headers=ana.headers)
    assert (again.status_code, again.json()) == (404, NOT_FOUND)


def test_cancel_needs_the_invite_of_that_habit(client, ana, db_session):
    first = owned_habit(db_session, ana)
    second = owned_habit(db_session, ana)
    invited(client, ana, first, "bia@example.com")
    invite_id = invite_id_for(db_session, first, "bia@example.com")

    response = client.delete(f"/habits/{second}/invites/{invite_id}", headers=ana.headers)

    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert len(pending(db_session, first)) == 1


def test_invite_of_another_user_is_refused(client, ana, bia, caio, habit_id, db_session):
    invited(client, ana, habit_id, "bia@example.com")
    invite_id = invite_id_for(db_session, habit_id, "bia@example.com")

    for response in (accept(client, caio, invite_id), decline(client, caio, invite_id)):
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    # Igual a um convite que não existe
    assert accept(client, caio, invite_id + 1000).json() == NOT_FOUND
    # Nem o dono aceita pelo convidado
    assert accept(client, ana, invite_id).json() == NOT_FOUND
    assert len(pending(db_session, habit_id)) == 1
    assert members(db_session, habit_id) == {}


@pytest.mark.parametrize("invite_id", ["0", "abc", str(2**63)])
def test_invalid_invite_id(client, bia, invite_id):
    response = client.post(f"/invites/{invite_id}/accept", headers=bia.headers)

    assert (response.status_code, response.json()["error"]) == (422, "validation_error")


def test_twenty_first_accept_is_refused(client, ana, bia, caio, db_session):
    for _ in range(20):
        habit = new_habit(caio.user)
        save(db_session, habit)
        save(db_session, new_member(habit, bia.user, "viewer"))
    habit_id = owned_habit(db_session, ana)
    invited(client, ana, habit_id, "bia@example.com")
    invite_id = invite_id_for(db_session, habit_id, "bia@example.com")

    refused = accept(client, bia, invite_id)

    assert (refused.status_code, refused.json()) == (409, SHARED_LIMIT)
    # O convite continua pendente: saindo de outro hábito, o aceite passa
    assert len(pending(db_session, habit_id)) == 1
    some = next(iter(set(members_of(db_session, bia.user.id)) - {habit_id}))
    assert client.post(f"/habits/{some}/leave", headers=bia.headers).status_code == 204
    assert accept(client, bia, invite_id).status_code == 200


def test_shared_habit_counts_only_for_the_owner(make_app_client, ana, bia, db_session):
    client = make_app_client(max_habits_per_user=1)
    habit_id = created(client, ana)["id"]
    invited(client, ana, habit_id, "bia@example.com")
    accept(client, bia, invite_id_for(db_session, habit_id, "bia@example.com"))

    # A bia participa de um hábito e ainda cria o dela; a ana já está no limite
    assert create(client, bia).status_code == 201
    assert create(client, ana).json()["error"] == "habit_limit_reached"


def test_accept_when_already_with_access_only_drops_invite(client, ana, bia, habit_id, db_session):
    # Ex.: o email da conta mudou depois do convite e ela já entrou por outro
    share(db_session, habit_id, bia, "viewer")
    habit = stored(db_session, habit_id)
    stale = new_invite(habit, "antigo@example.com", invited_user_id=bia.user.id)
    own = new_invite(habit, "ana-antigo@example.com", invited_user_id=ana.user.id)
    save(db_session, stale, own)

    as_member = accept(client, bia, stale.id)
    as_owner = accept(client, ana, own.id)

    assert (as_member.status_code, as_member.json()["role"]) == (200, "viewer")
    assert (as_owner.status_code, as_owner.json()["role"]) == (200, "owner")
    assert pending(db_session, habit_id) == []
    assert members(db_session, habit_id) == {bia.user.id: "viewer"}
    assert events(db_session, AuditEvent.INVITE_ACCEPTED) == []


def test_accepted_invite_to_archived_habit(client, ana, bia, habit_id, db_session):
    invited(client, ana, habit_id, "bia@example.com")
    client.post(f"/habits/{habit_id}/archive", headers=ana.headers)

    response = accept(client, bia, invite_id_for(db_session, habit_id, "bia@example.com"))

    assert (response.status_code, response.json()["status"]) == (200, "archived")
    assert members(db_session, habit_id) == {bia.user.id: "editor"}


# --- membros: listar, sair, remover, trocar papel ---


def test_members_list_owner_first(client, ana, bia, caio, habit_id, clock):
    for account, role in ((caio, "viewer"), (bia, "editor")):
        clock.shift(timedelta(minutes=5))
        invited(client, ana, habit_id, account.user.email, role)
        [item] = client.get("/invites", headers=account.headers).json()["invites"]
        accept(client, account, item["id"])

    response = client.get(f"/habits/{habit_id}/members", headers=caio.headers)

    assert response.status_code == 200
    assert response.json() == {
        "members": [
            {
                "user": {"id": ana.user.id, "email": "ana@example.com"},
                "role": "owner",
                "joined_at": "2026-03-25T15:00:00Z",
            },
            {
                "user": {"id": caio.user.id, "email": "caio@example.com"},
                "role": "viewer",
                "joined_at": "2026-03-25T15:05:00Z",
            },
            {
                "user": {"id": bia.user.id, "email": "bia@example.com"},
                "role": "editor",
                "joined_at": "2026-03-25T15:10:00Z",
            },
        ],
        "guest_limit": 5,
    }


def test_members_list_reports_the_configured_guest_limit(make_app_client, ana, bia, db_session):
    client = make_app_client(max_guests_per_habit=7)
    habit_id = created(client, ana)["id"]
    share(db_session, habit_id, bia, "viewer")

    for account in (ana, bia):
        response = client.get(f"/habits/{habit_id}/members", headers=account.headers)
        assert response.status_code == 200
        assert response.json()["guest_limit"] == 7


@pytest.fixture
def busy(client, ana, bia, habit_id, db_session) -> int:
    """Hábito da ana com a bia editora, uma marcação dela e alertas dela ali e em outro hábito."""
    share(db_session, habit_id, bia, "editor")
    habit = stored(db_session, habit_id)
    other = new_habit(ana.user)
    save(db_session, other)
    save(
        db_session,
        new_member(other, bia.user, "editor"),
        new_mark(habit, NOW - timedelta(hours=2), user_id=bia.user.id),
        new_alert(habit, bia.user),
        new_alert(habit, ana.user),
        new_alert(other, bia.user),
    )
    return other.id


def test_leave_keeps_marks_and_drops_alerts(client, ana, bia, habit_id, busy, db_session):
    response = client.post(f"/habits/{habit_id}/leave", headers=bia.headers)

    assert response.status_code == 204
    assert members(db_session, habit_id) == {}
    assert count(db_session, Mark, Mark.habit_id == habit_id, Mark.user_id == bia.user.id) == 1
    assert alerts(db_session, bia.user.id) == [busy]
    assert alerts(db_session, ana.user.id) == [habit_id]
    [entry] = events(db_session, AuditEvent.MEMBER_LEFT)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        bia.user.id,
        habit_id,
        IP,
        {"role": "editor"},
    )
    assert client.get(f"/habits/{habit_id}", headers=bia.headers).json() == NOT_FOUND
    # A marcação continua aparecendo para o dono, com a autora
    marks = client.get(
        f"/habits/{habit_id}/marks",
        params={"from": "2026-03-01T00:00:00Z", "to": "2026-04-01T00:00:00Z"},
        headers=ana.headers,
    ).json()["marks"]
    assert [mark["author"] for mark in marks] == [{"id": bia.user.id, "email": "bia@example.com"}]


def test_remove_member_keeps_marks_and_drops_alerts(client, ana, bia, habit_id, busy, db_session):
    response = client.delete(f"/habits/{habit_id}/members/{bia.user.id}", headers=ana.headers)

    assert response.status_code == 204
    assert members(db_session, habit_id) == {}
    assert count(db_session, Mark, Mark.habit_id == habit_id, Mark.user_id == bia.user.id) == 1
    assert alerts(db_session, bia.user.id) == [busy]
    assert alerts(db_session, ana.user.id) == [habit_id]
    [entry] = events(db_session, AuditEvent.MEMBER_REMOVED)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        ana.user.id,
        habit_id,
        IP,
        {"member_id": bia.user.id, "role": "editor"},
    )
    again = client.delete(f"/habits/{habit_id}/members/{bia.user.id}", headers=ana.headers)
    assert (again.status_code, again.json()) == (404, NOT_FOUND)


def test_owner_is_not_a_removable_member(client, ana, caio, habit_id, db_session):
    for target in (ana.user.id, caio.user.id, 2**40):
        response = client.delete(f"/habits/{habit_id}/members/{target}", headers=ana.headers)
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        patched = client.patch(
            f"/habits/{habit_id}/members/{target}", json={"role": "viewer"}, headers=ana.headers
        )
        assert (patched.status_code, patched.json()) == (404, NOT_FOUND)


def test_demote_editor_drops_alerts(client, ana, bia, habit_id, busy, db_session):
    response = client.patch(
        f"/habits/{habit_id}/members/{bia.user.id}", json={"role": "viewer"}, headers=ana.headers
    )

    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": bia.user.id, "email": "bia@example.com"},
        "role": "viewer",
        "joined_at": "2026-03-25T15:00:00Z",
    }
    assert members(db_session, habit_id) == {bia.user.id: "viewer"}
    # Só os alertas dela, e só neste hábito
    assert alerts(db_session, bia.user.id) == [busy]
    assert alerts(db_session, ana.user.id) == [habit_id]
    [entry] = events(db_session, AuditEvent.MEMBER_ROLE_CHANGED)
    assert (entry.user_id, entry.habit_id, entry.ip, entry.details) == (
        ana.user.id,
        habit_id,
        IP,
        {
            "member_id": bia.user.id,
            "changes": [{"field": "role", "old": "editor", "new": "viewer"}],
        },
    )
    # A viewer não marca mais
    assert (
        client.post(
            f"/habits/{habit_id}/toggle",
            json={
                "day_start": "2026-03-25T03:00:00Z",
                "day_end": "2026-03-26T03:00:00Z",
                "marked_at": "2026-03-25T15:00:00Z",
            },
            headers=bia.headers,
        ).status_code
        == 403
    )


def test_promote_viewer_and_same_role(client, ana, bia, habit_id, db_session):
    share(db_session, habit_id, bia, "viewer")
    path = f"/habits/{habit_id}/members/{bia.user.id}"

    promoted = client.patch(path, json={"role": "editor"}, headers=ana.headers)
    same = client.patch(path, json={"role": "editor"}, headers=ana.headers)

    assert promoted.json()["role"] == same.json()["role"] == "editor"
    assert members(db_session, habit_id) == {bia.user.id: "editor"}
    # Pedir o papel atual não grava evento
    assert len(events(db_session, AuditEvent.MEMBER_ROLE_CHANGED)) == 1


@pytest.mark.parametrize("body", [{"role": "owner"}, {}, {"role": "editor", "x": 1}])
def test_role_validation(client, ana, bia, habit_id, db_session, body):
    share(db_session, habit_id, bia, "viewer")

    response = client.patch(
        f"/habits/{habit_id}/members/{bia.user.id}", json=body, headers=ana.headers
    )

    assert response.status_code == 422
    assert members(db_session, habit_id) == {bia.user.id: "viewer"}


def test_membership_changes_on_archived_habit(client, ana, bia, caio, habit_id, db_session):
    share(db_session, habit_id, bia, "editor")
    share(db_session, habit_id, caio, "viewer")
    invited(client, ana, habit_id, "dani@example.com")
    client.post(f"/habits/{habit_id}/archive", headers=ana.headers)
    invite_id = invite_id_for(db_session, habit_id, "dani@example.com")
    member = f"/habits/{habit_id}/members/{bia.user.id}"

    canceled = client.delete(f"/habits/{habit_id}/invites/{invite_id}", headers=ana.headers)
    demoted = client.patch(member, json={"role": "viewer"}, headers=ana.headers)
    removed = client.delete(member, headers=ana.headers)
    left = client.post(f"/habits/{habit_id}/leave", headers=caio.headers)

    statuses = [r.status_code for r in (canceled, demoted, removed, left)]
    assert statuses == [204, 200, 204, 204]
    assert members(db_session, habit_id) == {}
    assert pending(db_session, habit_id) == []


def test_deleting_habit_removes_invites_and_members(client, ana, bia, habit_id, db_session):
    share(db_session, habit_id, bia, "editor")
    invited(client, ana, habit_id, "caio@example.com")

    client.delete(f"/habits/{habit_id}", headers=ana.headers)

    assert count(db_session, HabitInvite) == 0
    assert count(db_session, HabitMember) == 0
    # A auditoria do hábito sai junto; só o habit_deleted fica
    assert [entry.event for entry in db_session.scalars(select(AuditLog))] == ["habit_deleted"]
