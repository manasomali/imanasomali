"""Admin de contas (`app/admin/`), ETH-62."""

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from sqlalchemy import select, update

from app.admin import accounts
from app.admin.accounts import decode_cursor, encode_cursor, ensure_admin
from app.audit import AuditEvent
from app.db import create_session_factory, write_transaction
from app.errors import ApiError, ErrorCode
from app.main import create_app
from app.models import MAX_ACCOUNT_ID, AppTask, AuditLog, LoginCode, MailLog, User, UserSession
from tests.auth_helpers import Account, code_in
from tests.factories import count, new_user, save

ROOT = "root@example.com"
BIA = "bia@example.com"
NOW = datetime(2026, 10, 20, 15, 30, tzinfo=UTC)
FORBIDDEN = {"error": "forbidden", "field": None}
NOT_FOUND = {"error": "not_found", "field": None}
IP = "203.0.113.7"


@pytest.fixture
def client(app, make_client):
    return make_client(app, client=(IP, 50000))


@pytest.fixture
def root(make_account) -> Account:
    return make_account(ROOT, is_admin=True)


@pytest.fixture
def bia(make_account) -> Account:
    return make_account(BIA, locale="en")


def events(db_session, event: AuditEvent) -> list[AuditLog]:
    db_session.rollback()
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(AuditLog.event == event.value)
            .order_by(AuditLog.id)
            .execution_options(populate_existing=True)
        )
    )


def stored(db_session, user_id: int) -> User | None:
    db_session.rollback()
    return db_session.get(User, user_id, populate_existing=True)


def admin_routes(app) -> list[tuple[str, str]]:
    return [
        (method.upper(), re.sub(r"\{[^}]+\}", "1", path))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/admin")
        for method in operations
    ]


# --- acesso ---


def test_every_admin_route_needs_an_admin(app, client, make_account):
    routes = admin_routes(app)
    assert sorted(routes) == [
        ("DELETE", "/admin/users/1"),
        ("GET", "/admin/mail"),
        ("GET", "/admin/users"),
        ("PATCH", "/admin/users/1"),
        ("PATCH", "/admin/users/1/email"),
    ]
    common = make_account(BIA)
    pending = make_account("velho@example.com", is_admin=True, terms_version="2020-01-01")
    for method, url in routes:
        assert client.request(method, url, json={}).status_code == 401, url
        response = client.request(method, url, json={}, headers=common.headers)
        assert response.json() == FORBIDDEN, url
        response = client.request(method, url, json={}, headers=pending.headers)
        assert response.json() == {"error": "terms_not_accepted", "field": None}, url


def test_ensure_admin_rechecks_inside_the_transaction(db_session, root):
    for change, code in (
        ({"is_admin": False}, ErrorCode.FORBIDDEN),
        ({"is_active": False}, ErrorCode.UNAUTHORIZED),
        ({"status": "deleting"}, ErrorCode.UNAUTHORIZED),
    ):
        with write_transaction(db_session):
            db_session.execute(update(User).where(User.id == root.user.id).values(**change))
        with pytest.raises(ApiError) as raised, write_transaction(db_session):
            ensure_admin(db_session, root.user.id)
        assert raised.value.code is code
        with write_transaction(db_session):
            db_session.execute(
                update(User)
                .where(User.id == root.user.id)
                .values(is_admin=True, is_active=True, status="active")
            )
    with pytest.raises(ApiError) as raised, write_transaction(db_session):
        ensure_admin(db_session, root.user.id + 1)
    assert raised.value.code is ErrorCode.UNAUTHORIZED


# --- listagem ---


def test_list_shows_the_contract_fields(client, root, db_session):
    with write_transaction(db_session):
        db_session.execute(update(User).values(created_at=NOW, last_login_at=None))

    response = client.get("/admin/users", headers=root.headers)

    assert response.status_code == 200
    assert response.json() == {
        "users": [
            {
                "id": root.user.id,
                "email": ROOT,
                "status": "active",
                "is_active": True,
                "is_admin": True,
                "timezone": "America/Sao_Paulo",
                "locale": "pt",
                "created_at": "2026-10-20T15:30:00Z",
                "last_login_at": None,
            }
        ],
        "next_cursor": None,
    }


def make_users(db_session, total: int, start: datetime = NOW) -> list[User]:
    users = [
        new_user(f"user{index}@example.com", created_at=start - timedelta(minutes=index))
        for index in range(total)
    ]
    save(db_session, *users)
    return users


def test_list_pages_with_a_cursor_newest_first(client, root, db_session):
    users = make_users(db_session, 5)
    # Duas contas no mesmo instante: o id desempata
    same = new_user("same@example.com", created_at=NOW - timedelta(minutes=2))
    save(db_session, same)
    expected = sorted(
        [*users, same, root.user], key=lambda user: (user.created_at, user.id), reverse=True
    )

    seen, cursor = [], None
    while True:
        query = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = client.get("/admin/users", params=query, headers=root.headers).json()
        seen += [user["id"] for user in page["users"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == [user.id for user in expected]


def test_default_page_size_is_50(client, root, db_session):
    make_users(db_session, 55)

    page = client.get("/admin/users", headers=root.headers).json()

    assert len(page["users"]) == 50
    assert page["next_cursor"] is not None


def test_max_page_size_is_200(client, root, db_session):
    make_users(db_session, 205)

    page = client.get("/admin/users", params={"limit": 200}, headers=root.headers).json()

    assert len(page["users"]) == 200


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 201}, "limit"),
        ({"status": "deleted"}, "status"),
        ({"cursor": "abc"}, "cursor"),
        ({"cursor": f"1.{MAX_ACCOUNT_ID + 1}"}, "cursor"),
        ({"cursor": "1.0"}, "cursor"),
        ({"cursor": f"{10**18 - 1}.1"}, "cursor"),
        ({"cursor": "x" * 65}, "cursor"),
        ({"email": "a" * 255}, "email"),
    ],
)
def test_list_validates_the_query(client, root, params, field):
    response = client.get("/admin/users", params=params, headers=root.headers)

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": field}


def test_cursor_round_trip():
    instant = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)

    assert decode_cursor(encode_cursor(instant, MAX_ACCOUNT_ID)) == (instant, MAX_ACCOUNT_ID)


def test_list_filters_by_email_and_status(client, root, db_session):
    save(
        db_session,
        new_user("ana_100%@example.com"),
        new_user("bloqueada@example.com", is_active=False),
        new_user("saindo@example.com", status="deleting"),
        new_user("saindo-bloqueada@example.com", status="deleting", is_active=False),
    )

    def emails(**params) -> list[str]:
        page = client.get("/admin/users", params=params, headers=root.headers).json()
        return sorted(user["email"] for user in page["users"])

    assert emails(email="  _100%@EXAMPLE ") == ["ana_100%@example.com"]
    # `%` e `_` são letras, não curingas
    assert emails(email="a%") == []
    assert emails(email="   ") == sorted(
        [
            ROOT,
            "ana_100%@example.com",
            "bloqueada@example.com",
            "saindo@example.com",
            "saindo-bloqueada@example.com",
        ]
    )
    assert emails(status="active") == sorted([ROOT, "ana_100%@example.com"])
    assert emails(status="blocked") == ["bloqueada@example.com"]
    assert emails(status="deleting") == ["saindo-bloqueada@example.com", "saindo@example.com"]
    assert emails(status="active", email="ana") == ["ana_100%@example.com"]


# --- bloquear e desbloquear ---


def set_active(client, admin: Account, user_id: int, value):
    return client.patch(f"/admin/users/{user_id}", json={"is_active": value}, headers=admin.headers)


def test_block_ends_the_sessions_and_the_access(client, outbox, db_session, root, bia):
    response = set_active(client, root, bia.user.id, False)

    assert response.status_code == 200
    assert (response.json()["id"], response.json()["is_active"]) == (bia.user.id, False)
    assert stored(db_session, bia.user.id).is_active is False
    assert count(db_session, UserSession, UserSession.user_id == bia.user.id) == 0
    [blocked] = events(db_session, AuditEvent.USER_BLOCKED)
    assert (blocked.user_id, blocked.ip, blocked.details) == (
        root.user.id,
        IP,
        {"target_user_id": bia.user.id, "sessions": 1},
    )
    # Bloqueado não entra nem recebe código
    assert client.get("/me", headers=bia.headers).status_code == 401
    assert client.post("/auth/code/request", json={"email": BIA}).status_code == 202
    assert outbox.to(BIA) == []

    # De novo: nada muda, nada é gravado
    assert set_active(client, root, bia.user.id, False).status_code == 200
    assert len(events(db_session, AuditEvent.USER_BLOCKED)) == 1


def test_unblock(client, db_session, root, make_account):
    bia = make_account(BIA, is_active=False)

    response = set_active(client, root, bia.user.id, True)

    assert response.json()["is_active"] is True
    [unblocked] = events(db_session, AuditEvent.USER_UNBLOCKED)
    assert (unblocked.user_id, unblocked.details) == (root.user.id, {"target_user_id": bia.user.id})
    assert set_active(client, root, bia.user.id, True).status_code == 200
    assert len(events(db_session, AuditEvent.USER_UNBLOCKED)) == 1


def test_admin_cannot_block_itself(client, db_session, root):
    response = set_active(client, root, root.user.id, False)

    assert (response.status_code, response.json()) == (
        409,
        {"error": "cannot_block_self", "field": None},
    )
    assert stored(db_session, root.user.id).is_active is True


def test_block_another_admin(client, db_session, root, make_account):
    other = make_account("outro@example.com", is_admin=True)

    assert set_active(client, root, other.user.id, False).status_code == 200
    assert stored(db_session, other.user.id).is_active is False


@pytest.mark.parametrize("change", [None, {"status": "deleting"}])
def test_block_missing_or_deleting_account_is_404(client, db_session, root, change):
    user = new_user(BIA, **(change or {}))
    if change:
        save(db_session, user)

    response = set_active(client, root, user.id, False)

    assert (response.status_code, response.json()) == (404, NOT_FOUND)


@pytest.mark.parametrize(
    ("body", "field"),
    [({"is_active": "false"}, "is_active"), ({}, "is_active"), ({"is_active": 0}, "is_active")],
)
def test_block_validates_the_body(client, root, bia, body, field):
    response = client.patch(f"/admin/users/{bia.user.id}", json=body, headers=root.headers)

    assert response.json() == {"error": "validation_error", "field": field}


def test_extra_field_is_refused(client, root, bia):
    body = {"is_active": False, "is_admin": True}
    response = client.patch(f"/admin/users/{bia.user.id}", json=body, headers=root.headers)

    assert response.json() == {"error": "validation_error", "field": "is_admin"}


@pytest.mark.parametrize("user_id", ["0", str(MAX_ACCOUNT_ID + 1), "x"])
def test_invalid_id_is_422(client, root, user_id):
    response = client.patch(
        f"/admin/users/{user_id}", json={"is_active": False}, headers=root.headers
    )

    assert response.json() == {"error": "validation_error", "field": "user_id"}


def test_two_admins_blocking_each_other_leave_one(settings, engine, db_session, root, make_account):
    other = make_account("outro@example.com", is_admin=True)
    factory = create_session_factory(engine)
    barrier = threading.Barrier(2, timeout=10)

    def block(pair: tuple[int, int]):
        admin_id, target_id = pair
        with factory() as session:
            barrier.wait()
            try:
                accounts.set_active(
                    session, admin_id=admin_id, account_id=target_id, is_active=False, ip=None
                )
            except ApiError as error:
                return error.code
            return "ok"

    pairs = [(root.user.id, other.user.id), (other.user.id, root.user.id)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(block, pairs))

    assert sorted(results) == sorted(["ok", ErrorCode.UNAUTHORIZED])
    db_session.rollback()
    active_admins = count(db_session, User, User.is_admin.is_(True), User.is_active.is_(True))
    assert active_admins == 1


# --- trocar o email ---


def change_email(client, admin: Account, user_id: int, new_email):
    return client.patch(
        f"/admin/users/{user_id}/email", json={"new_email": new_email}, headers=admin.headers
    )


def test_change_email(client, outbox, db_session, apps, root, bia):
    # Um código pendente no email antigo
    client.post("/auth/code/request", json={"email": BIA})
    outbox.messages.clear()

    response = change_email(client, root, bia.user.id, "  Bia.Nova@Example.com ")

    assert response.status_code == 200
    assert response.json()["email"] == "bia.nova@example.com"
    user = stored(db_session, bia.user.id)
    assert user.email == "bia.nova@example.com"
    assert count(db_session, UserSession, UserSession.user_id == bia.user.id) == 0
    [old_code] = db_session.scalars(select(LoginCode))
    assert old_code.expires_at <= datetime.now(UTC)
    [changed] = events(db_session, AuditEvent.EMAIL_CHANGED)
    assert (changed.user_id, changed.ip, changed.details) == (
        root.user.id,
        IP,
        {
            "target_user_id": bia.user.id,
            "old_email": BIA,
            "new_email": "bia.nova@example.com",
            "sessions": 1,
        },
    )
    # Os dois avisos, no idioma da conta, e um refresh por aplicação com o email novo
    assert [(m["To"], m["Subject"]) for m in outbox.messages] == [
        (BIA, "Your manasomali.com account email was changed"),
        ("bia.nova@example.com", "This is now your manasomali.com account email"),
    ]
    assert [(call.app, call.action, call.body["email"]) for call in apps.calls] == [
        ("ethos", "refresh", "bia.nova@example.com"),
        ("engrafi", "refresh", "bia.nova@example.com"),
    ]
    assert all(task.done_at is not None for task in db_session.scalars(select(AppTask)))
    assert sorted(db_session.scalars(select(MailLog.kind))) == ["account", "account", "code"]
    # A sessão antiga não vale mais; o email novo entra na mesma conta
    assert client.get("/me", headers=bia.headers).status_code == 401
    outbox.messages.clear()
    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=2)):
        client.post("/auth/code/request", json={"email": "bia.nova@example.com"})
        response = client.post(
            "/auth/code/verify",
            json={
                "email": "bia.nova@example.com",
                "code": code_in(outbox.messages[0]),
                "timezone": "UTC",
                "locale": "pt",
            },
        )
    assert response.json() == {"new_account": False}


@pytest.mark.parametrize("taken", [ROOT, BIA])
def test_email_in_use_changes_nothing(client, outbox, db_session, apps, root, bia, taken):
    response = change_email(client, root, bia.user.id, taken)

    assert (response.status_code, response.json()) == (
        409,
        {"error": "email_in_use", "field": "new_email"},
    )
    assert stored(db_session, bia.user.id).email == BIA
    assert count(db_session, UserSession, UserSession.user_id == bia.user.id) == 1
    assert events(db_session, AuditEvent.EMAIL_CHANGED) == []
    assert outbox.messages == []
    assert apps.calls == []


@pytest.mark.parametrize("value", ["bia", "joão@example.com", "", 3, None])
def test_change_email_validates_the_new_email(client, root, bia, value):
    response = change_email(client, root, bia.user.id, value)

    assert response.json() == {"error": "validation_error", "field": "new_email"}


def test_change_email_of_a_deleting_account_is_404(client, db_session, root):
    user = new_user(BIA, status="deleting")
    save(db_session, user)

    assert change_email(client, root, user.id, "nova@example.com").json() == NOT_FOUND


def test_change_email_notices_refused_by_the_cap_alert_support(
    make_settings, db_session, make_client, outbox, apps, make_account
):
    settings = make_settings(max_emails_per_hour=1, mail_reserved_for_codes_per_hour=0)
    client = make_client(create_app(settings, mail_backend=outbox, app_transport=apps.transport))
    root = make_account(ROOT, is_admin=True)
    bia = make_account(BIA)

    assert change_email(client, root, bia.user.id, "nova@example.com").status_code == 200

    # O primeiro aviso coube no teto; o segundo virou o aviso ao suporte
    assert [m["To"] for m in outbox.messages] == [BIA, "suporte@example.com"]
    assert stored(db_session, bia.user.id).email == "nova@example.com"


# --- excluir ---


def test_admin_deletes_an_account(client, outbox, db_session, apps, root, bia):
    response = client.delete(f"/admin/users/{bia.user.id}", headers=root.headers)

    assert response.status_code == 204
    assert stored(db_session, bia.user.id) is None
    assert apps.of("delete") == [("ethos", bia.user.id), ("engrafi", bia.user.id)]
    [deleted] = events(db_session, AuditEvent.ACCOUNT_DELETED)
    assert (deleted.user_id, deleted.details) == (
        root.user.id,
        {"account_id": bia.user.id, "by_admin": True},
    )
    assert [m["Subject"] for m in outbox.to(BIA)] == ["Your manasomali.com account was deleted"]


def test_admin_deletes_a_blocked_account(client, db_session, root, make_account):
    bia = make_account(BIA, is_active=False)

    assert client.delete(f"/admin/users/{bia.user.id}", headers=root.headers).status_code == 204
    assert stored(db_session, bia.user.id) is None


def test_deleting_again_retries_the_apps_without_recording(client, db_session, apps, root, bia):
    apps.down.add("ethos")
    assert client.delete(f"/admin/users/{bia.user.id}", headers=root.headers).status_code == 204
    assert stored(db_session, bia.user.id).status == "deleting"

    apps.down.clear()
    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=5)):
        response = client.delete(f"/admin/users/{bia.user.id}", headers=root.headers)

    assert response.status_code == 204
    assert stored(db_session, bia.user.id) is None
    # Um início só, e o fim
    assert len(events(db_session, AuditEvent.ACCOUNT_DELETED)) == 1


def test_delete_missing_account_is_404(client, root):
    response = client.delete(f"/admin/users/{root.user.id + 1}", headers=root.headers)

    assert (response.status_code, response.json()) == (404, NOT_FOUND)


def test_last_admin_cannot_delete_itself(client, db_session, root):
    response = client.delete(f"/admin/users/{root.user.id}", headers=root.headers)

    assert (response.status_code, response.json()) == (409, {"error": "last_admin", "field": None})
    assert stored(db_session, root.user.id).status == "active"


def test_admin_deleting_itself_is_a_self_deletion(client, outbox, db_session, root, make_account):
    make_account("outro@example.com", is_admin=True)

    assert client.delete(f"/admin/users/{root.user.id}", headers=root.headers).status_code == 204

    [deleted] = events(db_session, AuditEvent.ACCOUNT_DELETED)
    assert (deleted.user_id, deleted.details) == (
        None,
        {"account_id": root.user.id, "by_admin": False},
    )
    assert client.get("/me", headers=root.headers).status_code == 401


# --- envios de email ---


def test_mail_stats(client, db_session, root):
    rows = [
        ("imago", "code", timedelta(minutes=5)),
        ("imago", "code", timedelta(hours=3)),
        ("imago", "account", timedelta(hours=23)),
        ("ethos", "notification", timedelta(minutes=30)),
        ("ethos", "notification", timedelta(hours=25)),
        ("antiga", "notification", timedelta(hours=2)),
    ]
    save(
        db_session,
        *(MailLog(app=app, kind=kind, created_at=NOW - age) for app, kind, age in rows),
    )

    with time_machine.travel(NOW, tick=False):
        response = client.get("/admin/mail", headers=root.headers)

    assert response.status_code == 200
    assert response.json() == {
        "window_hours": 24,
        "by_app": [
            {"app": "imago", "code": 2, "account": 1, "notification": 0},
            {"app": "ethos", "code": 0, "account": 0, "notification": 1},
            {"app": "engrafi", "code": 0, "account": 0, "notification": 0},
            {"app": "antiga", "code": 0, "account": 0, "notification": 1},
        ],
        "day": {"sent": 5, "limit": 275, "notification_limit": 215},
        "hour": {"sent": 2, "limit": 60, "notification_limit": 45},
    }
