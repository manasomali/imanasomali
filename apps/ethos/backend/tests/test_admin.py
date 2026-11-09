"""Painel de admin (ETH-28): quem usa o ethos, conteúdo dos hábitos e banners (`app/admin/`).

As contas (bloquear, trocar email, excluir) são do imago: o ethos não tem essas rotas."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from sqlalchemy import select

from app.admin import banners
from app.admin.accounts import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.admin.routes import router as admin_router
from app.audit import AuditEvent
from app.models import AuditLog, Banner
from tests.factories import new_habit, new_mark, new_member, save
from tests.fake_imago import INTERNAL_TOKEN
from tests.habit_helpers import FORBIDDEN, NOT_FOUND, Account, events, invalid
from tests.identity_helpers import identity_headers

# Quarta-feira, 12:00 em São Paulo
NOW = datetime(2026, 3, 25, 15, 0, tzinfo=UTC)
ROOT = "root@example.com"
ANA = "ana@example.com"
BIA = "bia@example.com"
UNAUTHORIZED = {"error": "not_authenticated", "field": None}

# Todas as rotas do router do admin, para os testes de permissão não esquecerem nenhuma
ADMIN_ROUTES = sorted(
    (method, route.path) for route in admin_router.routes for method in route.methods
)


@pytest.fixture(autouse=True)
def clock() -> Iterator[time_machine.Traveller]:
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def client(app, make_client):
    return make_client(app)


@pytest.fixture
def root(make_account) -> Account:
    return make_account(ROOT, admin=True, first_seen_at=NOW - timedelta(days=30))


@pytest.fixture
def ana(make_account) -> Account:
    return make_account(ANA)


@pytest.fixture
def bia(make_account) -> Account:
    return make_account(BIA)


def admin_events(db_session) -> list[AuditLog]:
    db_session.rollback()
    names = [
        AuditEvent.ADMIN_VIEWED_HABITS,
        AuditEvent.BANNER_CREATED,
        AuditEvent.BANNER_UPDATED,
        AuditEvent.BANNER_ENDED,
    ]
    query = select(AuditLog).where(AuditLog.event.in_([name.value for name in names]))
    return list(db_session.scalars(query.execution_options(populate_existing=True)))


def concrete(path: str, value: int) -> str:
    return re.sub(r"\{[a-z_]+\}", str(value), path)


def call(client, method: str, path: str, headers: dict[str, str] | None = None):
    body = {} if method in {"POST", "PATCH"} else None
    return client.request(method, path, json=body, headers=headers or {})


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


# --- permissões ---


def test_admin_router_has_every_endpoint():
    assert (
        sorted(
            [
                ("GET", "/admin/users"),
                ("GET", "/admin/users/{user_id}/habits"),
                ("GET", "/admin/banners"),
                ("POST", "/admin/banners"),
                ("PATCH", "/admin/banners/{banner_id}"),
                ("POST", "/admin/banners/{banner_id}/end"),
            ]
        )
        == ADMIN_ROUTES
    )


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_common_user_gets_403_on_every_endpoint(client, db_session, root, ana, bia, method, path):
    save(db_session, Banner(text_pt="a", text_en="a", starts_at=NOW, ends_at=NOW + timedelta(1)))
    response = call(client, method, concrete(path, bia.user.id), ana.headers)
    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    # Nada mudou
    assert admin_events(db_session) == []


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_without_user_gets_401_on_every_endpoint(client, method, path):
    response = call(client, method, concrete(path, 1))
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


def test_admin_comes_only_from_the_header(client, root):
    # A mesma pessoa, sem o X-User-Admin (o imago tirou o admin): 403 no request seguinte
    assert client.get("/admin/users", headers=root.headers).status_code == 200
    plain = identity_headers(root.user)
    assert client.get("/admin/users", headers=plain).json() == FORBIDDEN


# --- quem usa o ethos ---


def listed(client, root: Account, **params: Any) -> dict:
    response = client.get("/admin/users", params=params, headers=root.headers)
    assert response.status_code == 200, response.json()
    return response.json()


def emails(body: dict) -> list[str]:
    return [user["email"] for user in body["users"]]


def test_list_shows_app_users_with_counts(client, db_session, root, ana, make_account):
    bia = make_account(BIA, locale="en", timezone="Europe/Lisbon")
    owned = new_habit(ana.user)
    archived = new_habit(ana.user, status="archived", archived_at=NOW)
    bias = new_habit(bia.user)
    save(db_session, owned, archived, bias)
    save(db_session, new_member(bias, ana.user))
    save(
        db_session,
        new_mark(owned, NOW, user_id=ana.user.id),
        new_mark(owned, NOW - timedelta(days=1), user_id=ana.user.id),
        # Marcação dela no hábito da Bia conta; a da Bia no hábito dela, não
        new_mark(bias, NOW, user_id=ana.user.id),
        new_mark(owned, NOW - timedelta(days=2), user_id=bia.user.id),
    )

    body = listed(client, root)
    assert body["next_cursor"] is None
    # Mesmo primeiro acesso (relógio parado): o id maior, criado depois, vem antes
    assert emails(body) == [BIA, ANA, ROOT]
    assert body["users"][1] == {
        "id": ana.user.id,
        "email": ANA,
        "locale": "pt",
        "timezone": "America/Sao_Paulo",
        "first_seen_at": iso(NOW),
        "habit_count": 2,
        "mark_count": 3,
    }
    assert body["users"][0] | {"id": 0} == {
        "id": 0,
        "email": BIA,
        "locale": "en",
        "timezone": "Europe/Lisbon",
        "first_seen_at": iso(NOW),
        "habit_count": 1,
        "mark_count": 1,
    }


def test_list_has_no_n_plus_one(client, db_session, root, make_account, selects):
    def scene(start: int, total: int) -> None:
        for index in range(start, start + total):
            account = make_account(f"user{index}@example.com")
            habit = new_habit(account.user)
            save(db_session, habit)
            save(db_session, new_mark(habit, NOW, user_id=account.user.id))

    scene(0, 2)
    selects()
    listed(client, root)
    few = selects()
    scene(2, 8)
    selects()
    listed(client, root)
    many = selects()
    assert few == many


def test_list_pagination(client, root, make_account):
    for index in range(4):
        make_account(f"user{index}@example.com")
    first = listed(client, root, limit=2)
    assert emails(first) == ["user3@example.com", "user2@example.com"]
    second = listed(client, root, limit=2, cursor=first["next_cursor"])
    assert emails(second) == ["user1@example.com", "user0@example.com"]
    last = listed(client, root, limit=2, cursor=second["next_cursor"])
    assert emails(last) == [ROOT]
    assert last["next_cursor"] is None


def test_list_page_sizes(client, root, make_account):
    for index in range(DEFAULT_PAGE_SIZE + 1):
        make_account(f"user{index}@example.com")
    body = listed(client, root)
    assert len(body["users"]) == DEFAULT_PAGE_SIZE
    assert body["next_cursor"] is not None
    assert len(listed(client, root, limit=MAX_PAGE_SIZE)["users"]) == DEFAULT_PAGE_SIZE + 2
    for limit in (0, MAX_PAGE_SIZE + 1):
        response = client.get("/admin/users", params={"limit": limit}, headers=root.headers)
        assert response.status_code == 422
        assert response.json() == invalid("limit")


@pytest.mark.parametrize("cursor", ["x", "1", "1.", "1.99999999999999999999", "a" * 65])
def test_list_invalid_cursor(client, root, cursor):
    response = client.get("/admin/users", params={"cursor": cursor}, headers=root.headers)
    assert response.status_code == 422
    assert response.json() == invalid("cursor")


def test_list_search_by_email(client, root, make_account):
    make_account("ana.silva@example.com")
    make_account("bia@ana.org")
    make_account("caio@example.com")
    make_account("100%_real@example.com")
    assert emails(listed(client, root, email="  ANA ")) == ["bia@ana.org", "ana.silva@example.com"]
    # `%` e `_` não são curingas
    assert emails(listed(client, root, email="%_")) == ["100%_real@example.com"]
    assert emails(listed(client, root, email="_")) == ["100%_real@example.com"]
    assert emails(listed(client, root, email="nobody")) == []
    # Só espaços: sem filtro
    assert len(listed(client, root, email="  ")["users"]) == 5


def test_list_filters_by_first_access_in_the_admin_timezone(client, root, make_account):
    # 23:00 de 19/3 em São Paulo
    late = datetime(2026, 3, 20, 2, 0, tzinfo=UTC)
    make_account("late@example.com", first_seen_at=late)
    make_account("next@example.com", first_seen_at=late + timedelta(hours=2))
    make_account("old@example.com", first_seen_at=late - timedelta(days=5))
    only_20 = listed(client, root, first_seen_from="2026-03-20", first_seen_to="2026-03-20")
    assert emails(only_20) == ["next@example.com"]
    until_19 = listed(client, root, first_seen_from="2026-03-01", first_seen_to="2026-03-19")
    assert emails(until_19) == ["late@example.com", "old@example.com"]
    only_19 = listed(client, root, first_seen_from="2026-03-19", first_seen_to="2026-03-19")
    assert emails(only_19) == ["late@example.com"]


def test_list_refuses_inverted_ranges(client, root):
    params = {"first_seen_from": "2026-03-20", "first_seen_to": "2026-03-19"}
    response = client.get("/admin/users", params=params, headers=root.headers)
    assert response.status_code == 422
    assert response.json() == invalid("first_seen_to")


@pytest.mark.parametrize("value", ["2026-3-1", "2026-02-30", "2026-03-01T00:00:00", "1"])
def test_list_refuses_invalid_dates(client, root, value):
    response = client.get("/admin/users", params={"first_seen_from": value}, headers=root.headers)
    assert response.json() == invalid("first_seen_from")


def test_list_refuses_long_email_search(client, root):
    response = client.get("/admin/users", params={"email": "a" * 255}, headers=root.headers)
    assert response.json() == invalid("email")


def test_list_ignores_removed_filters(client, root, make_account):
    # status e datas de login eram do login próprio: agora são ignorados como qualquer parâmetro
    make_account("x@example.com")
    assert len(listed(client, root, status="blocked", last_login_from="2026-01-01")["users"]) == 2


# --- conteúdo dos hábitos ---


def view(client, root: Account, user_id: int, **params: Any):
    return client.get(f"/admin/users/{user_id}/habits", params=params, headers=root.headers)


def test_view_habits_shows_config_marks_and_notes(client, db_session, root, ana, bia):
    owned = new_habit(ana.user, name="Leitura", notes_enabled=True)
    archived = new_habit(ana.user, name="Velho", status="archived", archived_at=NOW)
    bias = new_habit(bia.user, name="Da Bia")
    save(db_session, owned, archived, bias)
    save(db_session, new_member(owned, bia.user), new_member(bias, ana.user))
    save(
        db_session,
        new_mark(owned, NOW - timedelta(days=2), user_id=ana.user.id, note="capítulo 3"),
        new_mark(owned, NOW - timedelta(days=1), user_id=bia.user.id),
        new_mark(archived, NOW - timedelta(days=3), user_id=ana.user.id),
        # Marcação dela em hábito de outra pessoa: fica na página da dona
        new_mark(bias, NOW, user_id=ana.user.id),
    )

    response = view(client, root, ana.user.id)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["user"]["email"] == ANA
    assert body["user"]["habit_count"] == 2
    assert [habit["name"] for habit in body["habits"]] == ["Leitura", "Velho"]
    assert {habit["role"] for habit in body["habits"]} == {"owner"}
    assert body["habits"][0]["notes_enabled"] is True
    assert body["habits"][1]["status"] == "archived"
    assert "score" not in body["habits"][0]
    marks = body["marks"]
    assert [mark["habit_id"] for mark in marks] == [owned.id, owned.id, archived.id]
    assert marks[0]["author"] == {"id": bia.user.id, "email": BIA}
    assert marks[1]["note"] == "capítulo 3"
    assert marks[1]["author"] == {"id": ana.user.id, "email": ANA}
    assert body["next_cursor"] is None


def test_view_habits_records_the_access(client, db_session, root, ana):
    habit = new_habit(ana.user)
    save(db_session, habit)
    assert view(client, root, ana.user.id).status_code == 200
    assert view(client, root, ana.user.id, habit_id=habit.id).status_code == 200
    rows = events(db_session, AuditEvent.ADMIN_VIEWED_HABITS)
    assert [(row.user_id, row.habit_id, row.ip, row.details) for row in rows] == [
        (root.user.id, None, None, {"target_user_id": ana.user.id}),
        (root.user.id, None, None, {"target_user_id": ana.user.id, "habit_id": habit.id}),
    ]


def test_view_habits_filters_by_habit_and_paginates(client, db_session, root, ana):
    first, second = new_habit(ana.user), new_habit(ana.user)
    save(db_session, first, second)
    save(
        db_session,
        *[new_mark(first, NOW - timedelta(days=day), user_id=ana.user.id) for day in range(3)],
        new_mark(second, NOW, user_id=ana.user.id),
    )
    body = view(client, root, ana.user.id, habit_id=first.id, limit=2).json()
    assert [mark["habit_id"] for mark in body["marks"]] == [first.id, first.id]
    assert len(body["habits"]) == 2
    page = view(client, root, ana.user.id, habit_id=first.id, cursor=body["next_cursor"]).json()
    assert [mark["marked_at"] for mark in page["marks"]] == [iso(NOW - timedelta(days=2))]
    assert page["next_cursor"] is None
    assert len(view(client, root, ana.user.id).json()["marks"]) == 4


def test_view_habits_of_unknown_user_or_foreign_habit(client, db_session, root, ana, bia):
    bias = new_habit(bia.user)
    save(db_session, bias)
    # Quem nunca abriu o ethos (só no imago) também é 404
    response = view(client, root, 999)
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    response = view(client, root, ana.user.id, habit_id=bias.id)
    assert response.json() == NOT_FOUND
    assert events(db_session, AuditEvent.ADMIN_VIEWED_HABITS) == []


def test_view_habits_invalid_params(client, root, ana):
    assert view(client, root, ana.user.id, cursor="x").json() == invalid("cursor")
    assert view(client, root, ana.user.id, habit_id=0).json() == invalid("habit_id")
    assert view(client, root, ana.user.id, limit=MAX_PAGE_SIZE + 1).json() == invalid("limit")
    for user_id in (0, 2**53):
        response = client.get(f"/admin/users/{user_id}/habits", headers=root.headers)
        assert response.json() == invalid("user_id")
    assert view(client, root, 2**53 - 1).json() == NOT_FOUND


# --- banners ---

BANNER = {
    "text_pt": "Manutenção às 22h",
    "text_en": "Maintenance at 10 pm",
    "starts_at": "2026-03-25T12:00:00Z",
    "ends_at": "2026-03-26T12:00:00Z",
}


def create(client, root: Account, **fields: Any):
    return client.post("/admin/banners", json=BANNER | fields, headers=root.headers)


def created(client, root: Account, **fields: Any) -> dict:
    response = create(client, root, **fields)
    assert response.status_code == 201, response.json()
    return response.json()


def active(client, **kwargs: Any) -> dict | None:
    response = client.get("/banners/active", **kwargs)
    assert response.status_code == 200
    return response.json()["banner"]


def test_create_banner(client, db_session, root):
    body = created(
        client, root, text_pt="  <b>Oi</b> & tchau ", starts_at="2026-03-25T09:00:00-03:00"
    )
    assert body == {
        "id": body["id"],
        "text_pt": "<b>Oi</b> & tchau",
        "text_en": BANNER["text_en"],
        "starts_at": "2026-03-25T12:00:00Z",
        "ends_at": BANNER["ends_at"],
        "created_by": root.user.id,
        "created_at": iso(NOW),
        "updated_at": iso(NOW),
    }
    [row] = events(db_session, AuditEvent.BANNER_CREATED)
    assert (row.user_id, row.ip) == (root.user.id, None)
    assert row.details == {
        "banner_id": body["id"],
        "text_pt": "<b>Oi</b> & tchau",
        "text_en": BANNER["text_en"],
        "starts_at": "2026-03-25T12:00:00+00:00",
        "ends_at": "2026-03-26T12:00:00+00:00",
    }


def test_banner_text_limits(client, root):
    assert created(client, root, text_pt="a" * 280, text_en="b" * 280)["text_pt"] == "a" * 280
    for field in ("text_pt", "text_en"):
        for value in ("a" * 281, "", "   ", "linha\noutra", "‮texto", None, 1):
            response = create(client, root, **{field: value})
            assert response.status_code == 422, (field, value)
            assert response.json() == invalid(field)


def test_banner_window(client, root):
    for ends_at in (BANNER["starts_at"], "2026-03-25T11:59:59Z"):
        response = create(client, root, ends_at=ends_at)
        assert response.json() == invalid("ends_at")
    for value in ("2026-03-25T12:00:00", "1899-12-31T23:59:59Z", 1774440000, None):
        assert create(client, root, starts_at=value).json() == invalid("starts_at")
    response = client.post("/admin/banners", json=BANNER | {"color": "red"}, headers=root.headers)
    assert response.json() == invalid("color")
    body = dict(BANNER)
    del body["ends_at"]
    response = client.post("/admin/banners", json=body, headers=root.headers)
    assert response.json() == invalid("ends_at")


def test_active_banner_needs_no_login(client, make_client, app, root):
    banner = created(client, root)
    anonymous = make_client(app, origin=False)
    shown = active(anonymous)
    assert shown == {
        key: banner[key] for key in ("id", "text_pt", "text_en", "starts_at", "ends_at")
    }
    # O cookie antigo do ethos não atrapalha (e sai apagado)
    legacy = anonymous.get("/banners/active", headers={"Cookie": "__Host-ethos_session=x"})
    assert legacy.json()["banner"]["id"] == banner["id"]
    assert "Max-Age=0" in legacy.headers["set-cookie"]


def test_banner_outside_the_window_does_not_appear(client, clock, root):
    assert active(client) is None
    created(client, root, starts_at="2026-03-25T15:00:01Z", ends_at="2026-03-26T00:00:00Z")
    created(client, root, starts_at="2026-03-24T00:00:00Z", ends_at="2026-03-25T15:00:00Z")
    assert active(client) is None
    # O início entra na janela; o fim, não
    clock.move_to(datetime(2026, 3, 25, 15, 0, 1, tzinfo=UTC))
    assert active(client)["starts_at"] == "2026-03-25T15:00:01Z"
    clock.move_to(datetime(2026, 3, 26, tzinfo=UTC))
    assert active(client) is None


def test_two_banners_in_the_window_only_the_latest_appears(client, root):
    newer = created(client, root, starts_at="2026-03-25T14:00:00Z")
    created(client, root, starts_at="2026-03-25T10:00:00Z")
    assert active(client)["id"] == newer["id"]
    # Mesmo início: o criado depois
    tie = created(client, root, starts_at="2026-03-25T14:00:00Z")
    assert active(client)["id"] == tie["id"]


def test_update_banner(client, db_session, clock, root):
    banner = created(client, root)
    clock.shift(timedelta(minutes=5))
    response = client.patch(
        f"/admin/banners/{banner['id']}",
        json={"text_en": "Down at 10 pm", "ends_at": "2026-03-27T12:00:00Z"},
        headers=root.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text_en"] == "Down at 10 pm"
    assert body["text_pt"] == BANNER["text_pt"]
    assert body["ends_at"] == "2026-03-27T12:00:00Z"
    assert body["updated_at"] == iso(NOW + timedelta(minutes=5))
    [row] = events(db_session, AuditEvent.BANNER_UPDATED)
    assert row.user_id == root.user.id
    assert row.details == {
        "banner_id": banner["id"],
        "changes": [
            {"field": "text_en", "old": BANNER["text_en"], "new": "Down at 10 pm"},
            {
                "field": "ends_at",
                "old": "2026-03-26T12:00:00+00:00",
                "new": "2026-03-27T12:00:00+00:00",
            },
        ],
    }
    # Sem mudança de verdade: não grava
    response = client.patch(
        f"/admin/banners/{banner['id']}", json={"text_pt": BANNER["text_pt"]}, headers=root.headers
    )
    assert response.status_code == 200
    assert (
        client.patch(f"/admin/banners/{banner['id']}", json={}, headers=root.headers).status_code
        == 200
    )
    assert len(events(db_session, AuditEvent.BANNER_UPDATED)) == 1


def test_update_banner_invalid(client, db_session, root):
    banner = created(client, root)
    path = f"/admin/banners/{banner['id']}"
    # A janela confere com o que está gravado
    response = client.patch(path, json={"starts_at": BANNER["ends_at"]}, headers=root.headers)
    assert response.json() == invalid("ends_at")
    response = client.patch(path, json={"ends_at": "2026-03-25T11:00:00Z"}, headers=root.headers)
    assert response.json() == invalid("ends_at")
    for field in ("text_pt", "text_en", "starts_at", "ends_at"):
        assert client.patch(path, json={field: None}, headers=root.headers).json() == invalid(field)
    assert client.patch(path, json={"x": 1}, headers=root.headers).json() == invalid("x")
    response = client.patch("/admin/banners/999", json={"text_pt": "x"}, headers=root.headers)
    assert response.json() == NOT_FOUND
    assert events(db_session, AuditEvent.BANNER_UPDATED) == []
    response = client.patch("/admin/banners/0", json={}, headers=root.headers)
    assert response.json() == invalid("banner_id")


def test_end_banner(client, db_session, root):
    banner = created(client, root)
    assert active(client)["id"] == banner["id"]
    response = client.post(f"/admin/banners/{banner['id']}/end", headers=root.headers)
    assert response.status_code == 200
    assert response.json()["ends_at"] == iso(NOW)
    assert response.json()["starts_at"] == BANNER["starts_at"]
    assert active(client) is None
    [row] = events(db_session, AuditEvent.BANNER_ENDED)
    assert row.details == {
        "banner_id": banner["id"],
        "changes": [
            {"field": "ends_at", "old": "2026-03-26T12:00:00+00:00", "new": NOW.isoformat()}
        ],
    }
    # Já encerrado: nada muda
    client.post(f"/admin/banners/{banner['id']}/end", headers=root.headers)
    assert len(events(db_session, AuditEvent.BANNER_ENDED)) == 1


def test_end_scheduled_banner_never_appears(client, db_session, clock, root):
    banner = created(client, root, starts_at="2026-03-26T00:00:00Z")
    body = client.post(f"/admin/banners/{banner['id']}/end", headers=root.headers).json()
    assert body["ends_at"] == iso(NOW)
    assert body["starts_at"] == "2026-03-25T14:59:59.999999Z"
    clock.move_to(datetime(2026, 3, 26, 1, tzinfo=UTC))
    assert active(client) is None
    [row] = events(db_session, AuditEvent.BANNER_ENDED)
    assert [change["field"] for change in row.details["changes"]] == ["starts_at", "ends_at"]


def test_end_unknown_banner(client, root):
    assert client.post("/admin/banners/999/end", headers=root.headers).json() == NOT_FOUND


def test_list_banners(client, clock, root):
    assert client.get("/admin/banners", headers=root.headers).json() == {
        "banners": [],
        "next_cursor": None,
    }
    ids = []
    for _ in range(3):
        ids.append(created(client, root)["id"])
        clock.shift(timedelta(seconds=1))
    first = client.get("/admin/banners", params={"limit": 2}, headers=root.headers).json()
    assert [banner["id"] for banner in first["banners"]] == ids[:0:-1]
    second = client.get(
        "/admin/banners", params={"cursor": first["next_cursor"]}, headers=root.headers
    ).json()
    assert [banner["id"] for banner in second["banners"]] == [ids[0]]
    assert second["next_cursor"] is None
    response = client.get("/admin/banners", params={"cursor": "x"}, headers=root.headers)
    assert response.json() == invalid("cursor")


def test_banner_survives_the_deletion_of_its_author(
    client, make_client, app, db_session, root, make_account
):
    other = make_account("other.root@example.com", admin=True)
    banner = created(client, other)
    # A conta do outro admin é excluída pelo imago, que chama a API interna do ethos
    internal = make_client(app, origin=False)
    headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}
    response = internal.post(f"/internal/users/{other.user.id}/delete", headers=headers)
    assert response.status_code == 200
    body = client.get("/admin/banners", headers=root.headers).json()
    assert body["banners"][0]["id"] == banner["id"]
    assert body["banners"][0]["created_by"] is None


def test_active_banner_service_takes_an_instant(db_session):
    save(db_session, Banner(text_pt="a", text_en="a", starts_at=NOW, ends_at=NOW + timedelta(1)))
    assert banners.active_banner(db_session, NOW - timedelta(seconds=1)) is None
    assert banners.active_banner(db_session, NOW) is not None
