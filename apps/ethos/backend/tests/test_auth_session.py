"""Sessão (current_user, renovação), termos, admin, logout e /auth/me (ETH-18)."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
import time_machine
from fastapi import APIRouter
from sqlalchemy import Engine, delete, event, select, update

from app.audit import AuditEvent
from app.auth import deps, routes, service
from app.auth.cookies import SESSION_COOKIE_NAME
from app.auth.deps import AdminUser, CurrentUser
from app.auth.security import generate_token, hash_secret
from app.db import write_transaction
from app.main import create_app
from app.models import AuditLog, User, UserSession, utcnow
from app.terms import TERMS_VERSION
from tests.auth_helpers import login, session_token
from tests.factories import TERMS_ACCEPTED_AT, count, new_user, save

IP = "203.0.113.7"
ANA = "ana@example.com"
T0 = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
LIFETIME = timedelta(days=60)
UNAUTHORIZED = {"error": "unauthorized", "field": None}
TERMS_NOT_ACCEPTED = {"error": "terms_not_accepted", "field": None}
FORBIDDEN = {"error": "forbidden", "field": None}

# Rotas só dos testes: um endpoint do app (CurrentUser) e um de admin (AdminUser)
probe = APIRouter(prefix="/test")


@probe.get("/app")
def app_endpoint(user: CurrentUser) -> dict[str, int]:
    return {"id": user.id}


@probe.get("/admin")
def admin_endpoint(user: AdminUser) -> dict[str, int]:
    return {"id": user.id}


@pytest.fixture
def client(settings, database, make_client, outbox):
    app = create_app(settings, mail_backend=outbox)
    app.include_router(probe)
    return make_client(app, client=(IP, 50000))


@pytest.fixture
def make_user(db_session) -> Callable[..., User]:
    def build(email: str = ANA, **fields) -> User:
        user = new_user(email, **({"terms_version": TERMS_VERSION} | fields))
        save(db_session, user)
        return user

    return build


@pytest.fixture
def ana(make_user) -> User:
    return make_user()


@pytest.fixture
def open_session(db_session) -> Callable[[User], str]:
    """Cria uma sessão do usuário agora (pela função do login) e devolve o token."""

    def build(user: User) -> str:
        with write_transaction(db_session):
            return service.create_session(
                db_session, user.id, now=utcnow(), ip=None, user_agent=None
            )

    return build


@pytest.fixture
def session_writes() -> Iterator[Callable[[], int]]:
    """Quantos UPDATE em `sessions` foram executados (em qualquer engine) durante o teste."""
    statements: list[str] = []

    def listener(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", listener)
    try:
        yield lambda: sum(1 for s in statements if s.lstrip().startswith("UPDATE sessions"))
    finally:
        event.remove(Engine, "before_cursor_execute", listener)


def cookie(token: str) -> dict[str, str]:
    # O cookie é Secure e o TestClient roda em http: vai no header
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def stored_session(db_session, token: str) -> UserSession | None:
    db_session.rollback()
    query = select(UserSession).where(UserSession.token_hash == hash_secret(token))
    return db_session.scalar(query.execution_options(populate_existing=True))


def reload(db_session, user: User) -> User:
    db_session.rollback()
    query = select(User).where(User.id == user.id).execution_options(populate_existing=True)
    return db_session.scalar(query)


def events(db_session, event_name: AuditEvent) -> list[AuditLog]:
    db_session.rollback()
    return list(db_session.scalars(select(AuditLog).where(AuditLog.event == event_name.value)))


def set_user(db_session, user: User, **values) -> None:
    with write_transaction(db_session):
        db_session.execute(update(User).where(User.id == user.id).values(**values))


def race(monkeypatch, module, action: Callable[[], None]) -> None:
    """Roda `action` (outro request) logo antes do `write_transaction` de `module`."""
    original = module.write_transaction

    @contextmanager
    def racing(session):
        action()
        with original(session) as inner:
            yield inner

    monkeypatch.setattr(module, "write_transaction", racing)


# --- /auth/me ---


def test_me_after_login(client, outbox, db_session):
    token = login(client, outbox, ANA, timezone="Europe/Lisbon", locale="en")

    response = client.get("/auth/me", headers=cookie(token))

    assert response.status_code == 200
    user = db_session.scalar(select(User))
    # Nada sensível: nem sessão, nem datas de login, nem flags internas além do admin
    assert response.json() == {
        "id": user.id,
        "email": ANA,
        "timezone": "Europe/Lisbon",
        "locale": "en",
        "is_admin": False,
        "terms_version": TERMS_VERSION,
        "current_terms_version": TERMS_VERSION,
        "terms_pending": False,
    }


@pytest.mark.parametrize("path", ["/auth/me", "/test/app", "/test/admin"])
def test_without_cookie_is_401(client, path):
    response = client.get(path)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


@pytest.mark.parametrize("token", ["", "x", generate_token(), "a" * 4000])
def test_unknown_token_is_401(client, ana, open_session, token):
    open_session(ana)

    response = client.get("/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


def test_cookie_with_another_name_is_401(client, ana, open_session):
    token = open_session(ana)

    response = client.get("/auth/me", headers={"Cookie": f"ethos_session={token}"})

    assert response.status_code == 401


def test_expired_session_is_401_and_not_written(client, ana, open_session, session_writes):
    second = timedelta(seconds=1)
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(ana)
        traveller.shift(LIFETIME - second)
        # Ainda vale e renova: passa a vencer em T0 + 120 dias - 1 s
        assert client.get("/auth/me", headers=cookie(token)).status_code == 200
        traveller.move_to(T0 + 2 * LIFETIME - second)
        expired = client.get("/auth/me", headers=cookie(token))

    # Só a renovação escreveu: a sessão vencida é recusada sem escrita
    assert session_writes() == 1
    assert expired.status_code == 401
    assert expired.json() == UNAUTHORIZED
    assert "set-cookie" not in expired.headers


def test_session_expires_at_exactly_sixty_days_without_use(client, ana, open_session, db_session):
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(ana)
        traveller.shift(LIFETIME)
        response = client.get("/auth/me", headers=cookie(token))

    assert response.status_code == 401
    # A vencida fica para o cleanup: a request não escreve
    assert stored_session(db_session, token).expires_at == T0 + LIFETIME


def test_inactive_user_is_401(client, ana, open_session, db_session):
    token = open_session(ana)
    set_user(db_session, ana, is_active=False)

    for path in ("/auth/me", "/test/app"):
        response = client.get(path, headers=cookie(token))
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED
    assert client.post("/auth/logout", headers=cookie(token)).status_code == 401


# --- renovação ---


def test_renewal_writes_at_most_once_a_day(client, ana, open_session, db_session, session_writes):
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(ana)
        traveller.shift(timedelta(hours=23, minutes=59))
        same_day = client.get("/auth/me", headers=cookie(token))
        assert session_writes() == 0
        assert stored_session(db_session, token).last_seen_at == T0

        traveller.move_to(T0 + timedelta(days=1))
        renewed = client.get("/auth/me", headers=cookie(token))
        traveller.shift(timedelta(hours=5))
        again = client.get("/test/app", headers=cookie(token))

    assert [same_day.status_code, renewed.status_code, again.status_code] == [200, 200, 200]
    # Dois requests no mesmo dia (o que renovou e o seguinte): uma escrita só
    assert session_writes() == 1
    stored = stored_session(db_session, token)
    assert stored.last_seen_at == T0 + timedelta(days=1)
    assert stored.expires_at == T0 + timedelta(days=1) + LIFETIME
    assert stored.created_at == T0
    # O cookie sai de novo, com o mesmo token e o Max-Age cheio, só no request que renovou
    assert "set-cookie" not in same_day.headers
    assert "set-cookie" not in again.headers
    assert session_token(renewed) == token
    morsel = SimpleCookie(renewed.headers["set-cookie"])[SESSION_COOKIE_NAME]
    assert morsel["max-age"] == str(int(LIFETIME.total_seconds()))
    assert morsel["secure"] is True
    assert morsel["httponly"] is True


def test_session_lives_while_used(client, ana, open_session):
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(ana)
        statuses = []
        # Um uso a cada 59 dias mantém a sessão por mais de um ano
        for _ in range(7):
            traveller.shift(LIFETIME - timedelta(days=1))
            statuses.append(client.get("/auth/me", headers=cookie(token)).status_code)

    assert statuses == [200] * 7


def test_logout_does_not_renew(client, ana, open_session, session_writes):
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(ana)
        traveller.shift(timedelta(days=2))
        response = client.post("/auth/logout", headers=cookie(token))

    assert response.status_code == 204
    assert session_writes() == 0
    # Um Set-Cookie só: o que apaga
    assert len(response.headers.get_list("set-cookie")) == 1


def test_renewal_already_done_by_another_request(
    client, ana, open_session, db_session, session_writes, monkeypatch
):
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(ana)
        traveller.shift(timedelta(days=3))

        def other_request_renews() -> None:
            with write_transaction(db_session):
                db_session.execute(
                    update(UserSession)
                    .where(UserSession.token_hash == hash_secret(token))
                    .values(last_seen_at=utcnow(), expires_at=utcnow() + LIFETIME)
                )

        race(monkeypatch, deps, other_request_renews)
        response = client.get("/auth/me", headers=cookie(token))

    assert response.status_code == 200
    # Só a escrita do outro request; esta não renova de novo nem manda o cookie
    assert session_writes() == 1
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("change", ["delete_session", "block_user"])
def test_session_ended_while_renewing_is_401(
    client, ana, open_session, db_session, monkeypatch, change
):
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(ana)
        traveller.shift(timedelta(days=3))

        def other_request() -> None:
            if change == "delete_session":
                with write_transaction(db_session):
                    db_session.execute(
                        delete(UserSession).where(UserSession.token_hash == hash_secret(token))
                    )
            else:
                set_user(db_session, ana, is_active=False)

        race(monkeypatch, deps, other_request)
        response = client.get("/auth/me", headers=cookie(token))

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


# --- logout ---


def test_logout_deletes_only_the_current_session(client, ana, open_session, db_session):
    current, other = open_session(ana), open_session(ana)

    response = client.post("/auth/logout", headers=cookie(current))

    assert response.status_code == 204
    assert response.content == b""
    header = response.headers["set-cookie"]
    morsel = SimpleCookie(header)[SESSION_COOKIE_NAME]
    assert morsel.value == ""
    assert morsel["max-age"] == "0"
    assert morsel["path"] == "/"
    assert morsel["secure"] is True
    assert morsel["httponly"] is True
    assert morsel["samesite"].lower() == "lax"
    assert stored_session(db_session, current) is None
    assert client.get("/auth/me", headers=cookie(current)).status_code == 401
    assert client.get("/auth/me", headers=cookie(other)).status_code == 200
    [entry] = events(db_session, AuditEvent.LOGOUT)
    assert (entry.user_id, entry.ip, entry.details) == (ana.id, IP, {})


def test_logout_without_session_is_401(client):
    response = client.post("/auth/logout")

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_logout_all_ends_every_session_of_the_user(
    client, ana, make_user, open_session, db_session
):
    sessions = [open_session(ana) for _ in range(3)]
    bia = make_user("bia@example.com")
    bia_session = open_session(bia)

    response = client.post("/auth/logout-all", headers=cookie(sessions[0]))

    assert response.status_code == 204
    assert SimpleCookie(response.headers["set-cookie"])[SESSION_COOKIE_NAME]["max-age"] == "0"
    # A outra sessão do mesmo usuário (o aparelho perdido) passa a dar 401
    for token in sessions:
        assert client.get("/auth/me", headers=cookie(token)).status_code == 401
    assert count(db_session, UserSession, UserSession.user_id == ana.id) == 0
    # Outro usuário não é afetado
    assert client.get("/auth/me", headers=cookie(bia_session)).status_code == 200
    [entry] = events(db_session, AuditEvent.LOGOUT_ALL)
    assert (entry.user_id, entry.ip, entry.details) == (ana.id, IP, {"sessions": 3})


@pytest.mark.parametrize("path", ["/auth/logout", "/auth/logout-all"])
def test_logout_when_sessions_vanished_meanwhile(
    client, ana, open_session, db_session, monkeypatch, path
):
    token = open_session(ana)

    def account_deleted() -> None:
        with write_transaction(db_session):
            db_session.execute(delete(User).where(User.id == ana.id))

    race(monkeypatch, routes, account_deleted)
    response = client.post(path, headers=cookie(token))

    assert response.status_code == 204
    # Nada a auditar: a conta (e as sessões) já não existem
    assert count(db_session, AuditLog) == 0


# --- termos ---


def test_new_terms_block_the_app_until_accepted(client, make_user, open_session, db_session):
    user = make_user(terms_version="2026-01-01")
    token = open_session(user)

    blocked = client.get("/test/app", headers=cookie(token))
    me = client.get("/auth/me", headers=cookie(token))
    accepted = client.post(
        "/auth/me/terms", json={"terms_version": TERMS_VERSION}, headers=cookie(token)
    )
    unblocked = client.get("/test/app", headers=cookie(token))

    assert blocked.status_code == 403
    assert blocked.json() == TERMS_NOT_ACCEPTED
    assert me.status_code == 200
    assert me.json()["terms_pending"] is True
    assert me.json()["terms_version"] == "2026-01-01"
    assert accepted.status_code == 200
    assert accepted.json()["terms_pending"] is False
    assert accepted.json()["terms_version"] == TERMS_VERSION
    assert unblocked.status_code == 200
    stored = reload(db_session, user)
    assert stored.terms_version == TERMS_VERSION
    assert stored.terms_accepted_at > TERMS_ACCEPTED_AT
    [entry] = events(db_session, AuditEvent.TERMS_ACCEPTED)
    assert (entry.user_id, entry.ip, entry.details) == (
        user.id,
        IP,
        {"terms_version": TERMS_VERSION},
    )


def test_publishing_a_new_version_blocks_who_accepted_the_old_one(
    client, ana, open_session, monkeypatch
):
    token = open_session(ana)
    assert client.get("/test/app", headers=cookie(token)).status_code == 200
    for module in (deps, routes):
        monkeypatch.setattr(module, "TERMS_VERSION", "2099-01-01")

    blocked = client.get("/test/app", headers=cookie(token))
    me = client.get("/auth/me", headers=cookie(token)).json()
    accepted = client.post(
        "/auth/me/terms", json={"terms_version": "2099-01-01"}, headers=cookie(token)
    )

    assert blocked.json() == TERMS_NOT_ACCEPTED
    assert (me["terms_pending"], me["current_terms_version"]) == (True, "2099-01-01")
    assert accepted.status_code == 200
    assert client.get("/test/app", headers=cookie(token)).status_code == 200


def test_accepting_another_version_is_409(client, make_user, open_session, db_session):
    user = make_user(terms_version="2026-01-01")
    token = open_session(user)

    response = client.post(
        "/auth/me/terms", json={"terms_version": "2026-01-01"}, headers=cookie(token)
    )

    assert response.status_code == 409
    assert response.json() == {"error": "conflict", "field": "terms_version"}
    assert reload(db_session, user).terms_version == "2026-01-01"
    assert events(db_session, AuditEvent.TERMS_ACCEPTED) == []


@pytest.mark.parametrize("body", [{}, {"terms_version": ""}, {"terms_version": "x" * 33}])
def test_accept_terms_needs_the_version(client, ana, open_session, body):
    response = client.post("/auth/me/terms", json=body, headers=cookie(open_session(ana)))

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": "terms_version"}


def test_accepting_twice_changes_nothing(client, ana, open_session, db_session):
    token = open_session(ana)

    response = client.post(
        "/auth/me/terms", json={"terms_version": TERMS_VERSION}, headers=cookie(token)
    )

    assert response.status_code == 200
    assert reload(db_session, ana).terms_accepted_at == ana.terms_accepted_at
    assert events(db_session, AuditEvent.TERMS_ACCEPTED) == []


def test_pending_terms_still_allow_profile_and_logout(client, make_user, open_session):
    user = make_user(terms_version="2026-01-01")
    token = open_session(user)

    patched = client.patch("/auth/me", json={"locale": "en"}, headers=cookie(token))
    logged_out = client.post("/auth/logout", headers=cookie(token))

    assert patched.status_code == 200
    assert logged_out.status_code == 204


# --- admin ---


def test_common_user_on_admin_route_is_403(client, ana, open_session):
    response = client.get("/test/admin", headers=cookie(open_session(ana)))

    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_admin_is_read_from_the_database_on_every_request(
    client, make_user, open_session, db_session
):
    admin = make_user(is_admin=True)
    token = open_session(admin)

    allowed = client.get("/test/admin", headers=cookie(token))
    set_user(db_session, admin, is_admin=False)
    revoked = client.get("/test/admin", headers=cookie(token))

    assert allowed.status_code == 200
    assert allowed.json() == {"id": admin.id}
    assert client.get("/auth/me", headers=cookie(token)).json()["is_admin"] is False
    assert revoked.status_code == 403


def test_admin_also_needs_the_current_terms(client, make_user, open_session):
    admin = make_user(is_admin=True, terms_version="2026-01-01")

    response = client.get("/test/admin", headers=cookie(open_session(admin)))

    assert response.json() == TERMS_NOT_ACCEPTED


# --- PATCH /auth/me ---


def test_update_timezone_and_locale(client, ana, open_session, db_session):
    token = open_session(ana)

    response = client.patch(
        "/auth/me", json={"timezone": "Asia/Tokyo", "locale": "en"}, headers=cookie(token)
    )

    assert response.status_code == 200
    assert (response.json()["timezone"], response.json()["locale"]) == ("Asia/Tokyo", "en")
    stored = reload(db_session, ana)
    assert (stored.timezone, stored.locale) == ("Asia/Tokyo", "en")
    [entry] = events(db_session, AuditEvent.PROFILE_UPDATED)
    assert (entry.user_id, entry.ip) == (ana.id, IP)
    assert entry.details == {
        "changes": [
            {"field": "timezone", "old": "America/Sao_Paulo", "new": "Asia/Tokyo"},
            {"field": "locale", "old": "pt", "new": "en"},
        ]
    }


def test_update_only_one_field(client, ana, open_session, db_session):
    token = open_session(ana)

    response = client.patch("/auth/me", json={"timezone": "UTC"}, headers=cookie(token))

    assert response.status_code == 200
    stored = reload(db_session, ana)
    assert (stored.timezone, stored.locale) == ("UTC", "pt")
    [entry] = events(db_session, AuditEvent.PROFILE_UPDATED)
    assert entry.details == {
        "changes": [{"field": "timezone", "old": "America/Sao_Paulo", "new": "UTC"}]
    }


@pytest.mark.parametrize("body", [{}, {"timezone": "America/Sao_Paulo", "locale": "pt"}])
def test_update_without_changes_records_nothing(client, ana, open_session, db_session, body):
    response = client.patch("/auth/me", json=body, headers=cookie(open_session(ana)))

    assert response.status_code == 200
    assert response.json()["timezone"] == "America/Sao_Paulo"
    assert reload(db_session, ana).updated_at == ana.updated_at
    assert events(db_session, AuditEvent.PROFILE_UPDATED) == []


@pytest.mark.parametrize("timezone", ["Mars/Base", "america/sao_paulo", "Etc", "../UTC"])
def test_unknown_timezone_is_refused(client, ana, open_session, db_session, timezone):
    response = client.patch(
        "/auth/me", json={"timezone": timezone, "locale": "en"}, headers=cookie(open_session(ana))
    )

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_timezone", "field": "timezone"}
    stored = reload(db_session, ana)
    assert (stored.timezone, stored.locale) == ("America/Sao_Paulo", "pt")


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"locale": "fr"}, "locale"),
        ({"timezone": None}, "timezone"),
        ({"locale": None}, "locale"),
        ({"timezone": ""}, "timezone"),
        ({"timezone": "A" * 65}, "timezone"),
        ({"timezone": 3}, "timezone"),
        ({"is_admin": True}, "is_admin"),
        ({"email": "outro@example.com"}, "email"),
    ],
)
def test_invalid_profile_body_is_422(client, ana, open_session, db_session, body, field):
    response = client.patch("/auth/me", json=body, headers=cookie(open_session(ana)))

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": field}
    stored = reload(db_session, ana)
    assert (stored.email, stored.is_admin, stored.locale) == (ANA, False, "pt")


@pytest.mark.parametrize("path", ["/auth/me", "/auth/me/terms"])
def test_account_blocked_while_writing_is_401(
    client, make_user, open_session, db_session, monkeypatch, path
):
    user = make_user(terms_version="2026-01-01")
    token = open_session(user)
    race(monkeypatch, routes, lambda: set_user(db_session, user, is_active=False))

    if path == "/auth/me":
        response = client.patch(path, json={"locale": "en"}, headers=cookie(token))
    else:
        response = client.post(path, json={"terms_version": TERMS_VERSION}, headers=cookie(token))

    assert response.status_code == 401
    stored = reload(db_session, user)
    assert (stored.locale, stored.terms_version) == ("pt", "2026-01-01")
    assert count(db_session, AuditLog) == 0


def test_login_of_existing_account_never_changes_the_timezone(client, outbox, db_session):
    with time_machine.travel(T0, tick=False) as traveller:
        token = login(client, outbox, ANA, timezone="America/Sao_Paulo")
        client.patch("/auth/me", json={"timezone": "Europe/Paris"}, headers=cookie(token))
        traveller.shift(timedelta(minutes=2))
        login(client, outbox, ANA, timezone="Asia/Tokyo", locale="en")

    user = db_session.scalar(select(User).execution_options(populate_existing=True))
    assert (user.timezone, user.locale) == ("Europe/Paris", "pt")
