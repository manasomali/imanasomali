"""Matriz de permissões (ETH-24): dono, editor, viewer, estranho e sem sessão em todos os
endpoints de hábito (ETH-20 a 24).

Cada caso monta o mesmo cenário (hábito da ana com a bia editora, o caio viewer, a eva viewer,
uma marcação e um convite pendente; a dani não tem acesso) e chama um endpoint com uma conta.
O estranho recebe o mesmo 404 de um id que não existe; quem vê mas não pode fazer a ação, 403.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import time_machine

from app.main import create_app
from tests.factories import new_habit, new_invite, new_mark, new_member, save
from tests.habit_helpers import FORBIDDEN, NOT_FOUND, Account, stored

# 12:00 em São Paulo
NOW = datetime(2026, 3, 25, 15, 0, tzinfo=UTC)
DAY_START = datetime(2026, 3, 25, 3, 0, tzinfo=UTC)
UNAUTHORIZED = {"error": "unauthorized", "field": None}
ROLES = ("owner", "editor", "viewer", "stranger", "anonymous")
MULTI = {"multi_mark": True, "goal_count": 10}

TOGGLE = {
    "day_start": DAY_START.isoformat(),
    "day_end": (DAY_START + timedelta(days=1)).isoformat(),
    "marked_at": NOW.isoformat(),
}
RANGE = f"from={(NOW - timedelta(days=7)).isoformat()}&to={NOW.isoformat()}".replace("+", "%2B")


@dataclass(frozen=True)
class Case:
    method: str
    path: str
    # Status esperado para dono, editor, viewer e estranho (sem sessão: sempre 401)
    expected: tuple[int, int, int, int]
    body: dict | None = None
    # Hábito com várias marcações por dia (senão, toggle)
    multi: bool = False


CASES = {
    # ETH-20
    "get": Case("GET", "/habits/{habit}", (200, 200, 200, 404)),
    "patch": Case("PATCH", "/habits/{habit}", (200, 403, 403, 404), {"name": "Novo"}),
    "delete": Case("DELETE", "/habits/{habit}", (204, 403, 403, 404)),
    # ETH-21
    "pause": Case("POST", "/habits/{habit}/pause", (200, 403, 403, 404)),
    "resume": Case("POST", "/habits/{habit}/resume", (200, 403, 403, 404)),
    "archive": Case("POST", "/habits/{habit}/archive", (200, 403, 403, 404)),
    "unarchive": Case("POST", "/habits/{habit}/unarchive", (200, 403, 403, 404)),
    # ETH-22
    "toggle": Case("POST", "/habits/{habit}/toggle", (200, 200, 403, 404), TOGGLE),
    "add_mark": Case(
        "POST",
        "/habits/{habit}/marks",
        (201, 201, 403, 404),
        {"marked_at": NOW.isoformat()},
        multi=True,
    ),
    "list_marks": Case("GET", "/habits/{habit}/marks?" + RANGE, (200, 200, 200, 404)),
    "patch_mark": Case("PATCH", "/habits/{habit}/marks/{mark}", (200, 200, 403, 404), {}),
    "delete_mark": Case("DELETE", "/habits/{habit}/marks/{mark}", (204, 204, 403, 404)),
    # ETH-24
    "invite": Case(
        "POST",
        "/habits/{habit}/invites",
        (202, 403, 403, 404),
        {"email": "novo@example.com", "role": "viewer"},
    ),
    "list_invites": Case("GET", "/habits/{habit}/invites", (200, 403, 403, 404)),
    "cancel_invite": Case("DELETE", "/habits/{habit}/invites/{invite}", (204, 403, 403, 404)),
    "list_members": Case("GET", "/habits/{habit}/members", (200, 200, 200, 404)),
    "change_role": Case(
        "PATCH", "/habits/{habit}/members/{target}", (200, 403, 403, 404), {"role": "editor"}
    ),
    "remove_member": Case("DELETE", "/habits/{habit}/members/{target}", (204, 403, 403, 404)),
    "leave": Case("POST", "/habits/{habit}/leave", (403, 204, 204, 404)),
}


@pytest.fixture(autouse=True)
def clock() -> Iterator[time_machine.Traveller]:
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def client(settings, database, make_client, outbox):
    return make_client(create_app(settings, mail_backend=outbox))


@dataclass(frozen=True)
class Scene:
    accounts: dict[str, Account | None]
    ids: dict[str, int]


def build_scene(db_session, make_account, *, multi: bool) -> Scene:
    ana = make_account("ana@example.com")
    bia = make_account("bia@example.com")
    caio = make_account("caio@example.com")
    dani = make_account("dani@example.com")
    eva = make_account("eva@example.com")
    habit = new_habit(ana.user, **(MULTI if multi else {}))
    save(db_session, habit)
    mark = new_mark(habit, NOW - timedelta(hours=1), user_id=ana.user.id)
    invite = new_invite(habit, "fulano@example.com")
    save(
        db_session,
        new_member(habit, bia.user, "editor"),
        new_member(habit, caio.user, "viewer"),
        new_member(habit, eva.user, "viewer"),
        mark,
        invite,
    )
    return Scene(
        accounts={"owner": ana, "editor": bia, "viewer": caio, "stranger": dani, "anonymous": None},
        ids={"habit": habit.id, "mark": mark.id, "invite": invite.id, "target": eva.user.id},
    )


def expected_body(status: int) -> dict | None:
    return {401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND}.get(status)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("name", CASES)
def test_permission_matrix(client, db_session, make_account, name, role):
    case = CASES[name]
    scene = build_scene(db_session, make_account, multi=case.multi)
    account = scene.accounts[role]
    headers = {} if account is None else account.headers

    response = client.request(
        case.method, case.path.format(**scene.ids), json=case.body, headers=headers
    )

    status = 401 if account is None else case.expected[ROLES.index(role)]
    assert response.status_code == status, response.json()
    body = expected_body(status)
    if body is not None:
        assert response.json() == body
        # Recusado: o hábito continua lá, igual
        assert stored(db_session, scene.ids["habit"]).name == "Exercício"


@pytest.mark.parametrize("name", CASES)
def test_missing_habit_is_the_same_404(client, db_session, make_account, name):
    case = CASES[name]
    scene = build_scene(db_session, make_account, multi=case.multi)
    ids = scene.ids | {"habit": scene.ids["habit"] + 1000}

    response = client.request(
        case.method,
        case.path.format(**ids),
        json=case.body,
        headers=scene.accounts["owner"].headers,
    )

    assert (response.status_code, response.json()) == (404, NOT_FOUND)


@pytest.mark.parametrize(
    ("role", "listed"), [("owner", True), ("editor", True), ("viewer", True), ("stranger", False)]
)
def test_list_shows_habit_to_whoever_has_access(client, db_session, make_account, role, listed):
    scene = build_scene(db_session, make_account, multi=False)

    response = client.get("/habits", headers=scene.accounts[role].headers)

    assert response.status_code == 200
    ids = [habit["id"] for habit in response.json()["habits"]]
    assert (scene.ids["habit"] in ids) is listed


@pytest.mark.parametrize(
    ("role", "listed"), [("owner", True), ("editor", True), ("viewer", True), ("stranger", False)]
)
def test_progress_shows_habit_to_whoever_has_access(client, db_session, make_account, role, listed):
    # GET /habits/progress (ETH-23): hábito sem acesso some da resposta, sem erro
    scene = build_scene(db_session, make_account, multi=False)
    query = {"from": "2026-03-01", "to": "2026-03-31", "habit_ids": scene.ids["habit"]}

    response = client.get("/habits/progress", params=query, headers=scene.accounts[role].headers)
    anonymous = client.get("/habits/progress", params=query)

    assert response.status_code == 200
    ids = [item["habit"]["id"] for item in response.json()["habits"]]
    assert ids == ([scene.ids["habit"]] if listed else [])
    assert (anonymous.status_code, anonymous.json()) == (401, UNAUTHORIZED)
