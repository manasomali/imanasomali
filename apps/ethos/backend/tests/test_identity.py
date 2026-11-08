"""Quem é o usuário (ETH-60): os headers `X-User-*`, `app_users`, `require_user`/`require_admin`,
`GET /me`, a checagem de `Origin` (CSRF) e o cookie antigo (`app/identity.py`)."""

import logging
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from sqlalchemy import Engine, event, select
from starlette.datastructures import Headers

from app import identity as identity_module
from app.db import create_session_factory
from app.identity import (
    Identity,
    MalformedIdentityError,
    has_legacy_cookie,
    origin_allowed,
    read_identity,
    route_path,
    sync_app_user,
)
from app.mail.language import Locale
from app.main import create_app
from app.models import AppUser
from tests.factories import count, new_user, save

ORIGIN = "http://localhost:5174"
FORBIDDEN = {"error": "forbidden", "field": None}
NOT_AUTHENTICATED = {"error": "not_authenticated", "field": None}
HEADERS = {
    "X-User-Id": "4242",
    "X-User-Email": "ana@example.com",
    "X-User-Locale": "pt",
    "X-User-Timezone": "America/Sao_Paulo",
}


@pytest.fixture
def bare_client(app, make_client):
    """Cliente que não manda `Origin` sozinho (cada teste escolhe o header)."""
    return make_client(app, origin=False)


@pytest.fixture
def writes() -> Iterator[list[str]]:
    """Os INSERT e UPDATE executados (em qualquer engine) durante o teste."""
    statements: list[str] = []

    def listener(_conn, _cursor, statement, *_args) -> None:
        if statement.lstrip().startswith(("INSERT", "UPDATE")):
            statements.append(statement)

    event.listen(Engine, "before_cursor_execute", listener)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", listener)


def app_users(db_session) -> list[tuple]:
    db_session.rollback()
    query = select(AppUser.id, AppUser.email, AppUser.locale, AppUser.timezone)
    return [tuple(row) for row in db_session.execute(query.order_by(AppUser.id))]


# --- os headers ----------------------------------------------------------------------------


def test_complete_headers_identify_the_user():
    identity = read_identity(Headers(HEADERS | {"X-User-Admin": "1"}))

    assert identity == Identity(
        id=4242,
        email="ana@example.com",
        locale=Locale.PT,
        timezone="America/Sao_Paulo",
        is_admin=True,
    )
    # O email não aparece no repr (traceback, log)
    assert "ana@example.com" not in repr(identity)


def test_without_admin_header_is_not_admin():
    assert read_identity(Headers(HEADERS)).is_admin is False


@pytest.mark.parametrize("headers", [{}, {"X-User-Id": ""}, dict.fromkeys(HEADERS, "")])
def test_without_id_there_is_no_user(headers):
    assert read_identity(Headers(headers)) is None


@pytest.mark.parametrize(
    ("change", "header"),
    [
        ({"X-User-Id": "abc"}, "x-user-id"),
        ({"X-User-Id": "0"}, "x-user-id"),
        ({"X-User-Id": "-1"}, "x-user-id"),
        ({"X-User-Id": "042"}, "x-user-id"),
        ({"X-User-Id": "4.2"}, "x-user-id"),
        ({"X-User-Id": " 42"}, "x-user-id"),
        ({"X-User-Id": str(2**53)}, "x-user-id"),
        ({"X-User-Id": "4²"}, "x-user-id"),
        ({"X-User-Email": "Ana@Example.com"}, "x-user-email"),
        ({"X-User-Email": "ana"}, "x-user-email"),
        ({"X-User-Email": "joão@example.com"}, "x-user-email"),
        ({"X-User-Email": "a" * 250 + "@x.com"}, "x-user-email"),
        ({"X-User-Email": ""}, "x-user-email"),
        ({"X-User-Locale": "es"}, "x-user-locale"),
        ({"X-User-Locale": "PT"}, "x-user-locale"),
        ({"X-User-Locale": ""}, "x-user-locale"),
        ({"X-User-Timezone": "Mars/Base"}, "x-user-timezone"),
        ({"X-User-Timezone": "america/sao_paulo"}, "x-user-timezone"),
        ({"X-User-Timezone": ""}, "x-user-timezone"),
        ({"X-User-Admin": "0"}, "x-user-admin"),
        ({"X-User-Admin": "true"}, "x-user-admin"),
    ],
)
def test_malformed_header_names_the_header(change, header):
    with pytest.raises(MalformedIdentityError) as raised:
        read_identity(Headers(HEADERS | change))
    assert str(raised.value) == header


@pytest.mark.parametrize(
    "name", ["X-User-Email", "X-User-Locale", "X-User-Timezone", "X-User-Admin"]
)
def test_other_headers_without_the_id_are_malformed(name):
    value = HEADERS.get(name, "1")
    with pytest.raises(MalformedIdentityError, match="x-user-id"):
        read_identity(Headers({name: value}))


def test_repeated_header_is_malformed():
    raw = [(name.lower().encode(), value.encode()) for name, value in HEADERS.items()]
    raw.append((b"x-user-id", b"4243"))
    with pytest.raises(MalformedIdentityError, match="x-user-id"):
        read_identity(Headers(raw=raw))


def test_largest_id_is_accepted():
    assert read_identity(Headers(HEADERS | {"X-User-Id": str(2**53 - 1)})).id == 2**53 - 1


# --- require_user na API -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/me"), ("GET", "/habits"), ("POST", "/habits")]
)
def test_without_user_is_401_not_authenticated(client, method, path):
    response = client.request(method, path, json={})

    assert (response.status_code, response.json()) == (401, NOT_AUTHENTICATED)


def test_malformed_header_is_401_with_a_warning_without_the_value(client, caplog):
    with caplog.at_level(logging.WARNING, logger="app.identity"):
        response = client.get("/me", headers=HEADERS | {"X-User-Timezone": "Segredo/Fuso"})

    assert (response.status_code, response.json()) == (401, NOT_AUTHENTICATED)
    [record] = [record for record in caplog.records if record.name == "app.identity"]
    assert record.getMessage() == "header x-user-timezone inválido; request recusado com 401"
    assert "Segredo" not in caplog.text
    assert "ana@example.com" not in caplog.text


def test_get_me_comes_from_the_headers(client):
    response = client.get("/me", headers=HEADERS | {"X-User-Admin": "1"})

    assert (response.status_code, response.json()) == (
        200,
        {
            "id": 4242,
            "email": "ana@example.com",
            "locale": "pt",
            "timezone": "America/Sao_Paulo",
            "is_admin": True,
        },
    )


def test_public_route_works_without_user(client):
    assert client.get("/banners/active").status_code == 200
    assert client.get("/health").status_code == 200


def test_admin_route_needs_the_admin_header(client):
    assert client.get("/admin/banners", headers=HEADERS).json() == FORBIDDEN
    assert client.get("/admin/banners", headers=HEADERS | {"X-User-Admin": "1"}).status_code == 200


# --- app_users -----------------------------------------------------------------------------


def test_first_request_creates_the_app_user(client, db_session):
    assert client.get("/me", headers=HEADERS).status_code == 200

    assert app_users(db_session) == [(4242, "ana@example.com", "pt", "America/Sao_Paulo")]
    [user] = db_session.scalars(select(AppUser))
    assert user.first_seen_at == user.updated_at


def test_same_headers_write_once(client, db_session, writes):
    for _ in range(3):
        assert client.get("/habits", headers=HEADERS).status_code == 200

    assert [statement.split()[0:3] for statement in writes] == [["INSERT", "INTO", "app_users"]]
    assert count(db_session, AppUser) == 1


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            {"X-User-Email": "ana.nova@example.com"},
            ("ana.nova@example.com", "pt", "America/Sao_Paulo"),
        ),
        ({"X-User-Locale": "en"}, ("ana@example.com", "en", "America/Sao_Paulo")),
        ({"X-User-Timezone": "Europe/Lisbon"}, ("ana@example.com", "pt", "Europe/Lisbon")),
    ],
)
def test_changed_header_updates_the_row_once(client, db_session, writes, change, expected):
    assert client.get("/me", headers=HEADERS).status_code == 200
    db_session.rollback()
    first_seen = db_session.scalar(select(AppUser.first_seen_at))
    writes.clear()

    assert client.get("/me", headers=HEADERS | change).status_code == 200
    assert client.get("/me", headers=HEADERS | change).status_code == 200

    assert [statement.split()[0:2] for statement in writes] == [["UPDATE", "app_users"]]
    assert app_users(db_session) == [(4242, *expected)]
    [user] = db_session.scalars(select(AppUser))
    assert user.first_seen_at == first_seen
    assert user.updated_at > first_seen


def test_admin_header_is_not_stored(client, db_session, writes):
    client.get("/me", headers=HEADERS)
    writes.clear()

    assert client.get("/me", headers=HEADERS | {"X-User-Admin": "1"}).status_code == 200

    assert writes == []


def test_parallel_first_requests_create_one_row(app, make_client, db_session):
    client = make_client(app)
    barrier = threading.Barrier(4)

    def call(_index: int) -> int:
        barrier.wait()
        return client.get("/habits", headers=HEADERS).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(call, range(4)))

    assert statuses == [200] * 4
    assert count(db_session, AppUser) == 1


def test_user_known_from_before_imago_is_reused(client, db_session):
    # A linha migrada de users (mesmo id do imago): nada é recriado
    user = new_user("ana@example.com", id=7)
    save(db_session, user)

    assert client.get("/me", headers=HEADERS | {"X-User-Id": "7"}).status_code == 200

    assert app_users(db_session) == [(7, "ana@example.com", "pt", "America/Sao_Paulo")]


# --- Origin (CSRF) -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        # Com caminho: o Origin nunca traz caminho, e o APP_URL inteiro não é uma origem
        "http://localhost:5174/ethos",
        "http://localhost:5174/",
        # Outro esquema, porta ou host
        "https://localhost:5174",
        "http://localhost:5175",
        "http://localhost",
        "http://127.0.0.1:5174",
        "http://LOCALHOST:5174",
        "http://localhost:5174.evil.example",
        "null",
        "",
    ],
)
@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/habits"), ("PATCH", "/habits/1"), ("DELETE", "/habits/1"), ("PUT", "/x")],
)
def test_wrong_origin_is_403(bare_client, method, path, origin):
    response = bare_client.request(method, path, json={}, headers=HEADERS | {"Origin": origin})

    assert (response.status_code, response.json()) == (403, FORBIDDEN)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "PROPFIND"])
def test_missing_origin_is_403_on_any_write_method(bare_client, method):
    # Rota que só aceita GET: a checagem vem antes do 405
    response = bare_client.request(method, "/health")

    assert (response.status_code, response.json()) == (403, FORBIDDEN)


def test_refused_before_reading_the_body(bare_client):
    # JSON quebrado com Origin errado: 403, não 422
    response = bare_client.post(
        "/habits",
        content=b"{not json",
        headers=HEADERS | {"Origin": "https://evil.example", "Content-Type": "application/json"},
    )

    assert response.status_code == 403


def test_two_origin_headers_are_refused(bare_client):
    response = bare_client.post("/habits", headers=[("Origin", ORIGIN), ("Origin", ORIGIN)])

    assert response.status_code == 403


def test_right_origin_passes(bare_client):
    # Passa a checagem e chega na rota: sem usuário, 401
    response = bare_client.post("/habits", json={}, headers={"Origin": ORIGIN})

    assert (response.status_code, response.json()) == (401, NOT_AUTHENTICATED)


# /health só declara GET: HEAD e OPTIONS chegam na rota e levam 405, não 403
@pytest.mark.parametrize(("method", "status"), [("GET", 200), ("HEAD", 405), ("OPTIONS", 405)])
@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {}])
def test_safe_methods_are_not_checked(bare_client, method, status, headers):
    response = bare_client.request(method, "/health", headers=headers)

    assert response.status_code == status


def test_production_origin_has_no_default_port(make_settings, database, make_client, imago):
    settings = make_settings(app_url="https://manasomali.com/ethos")
    client = make_client(create_app(settings, imago_transport=imago.transport), origin=False)

    allowed = client.post("/habits", json={}, headers={"Origin": "https://manasomali.com"})
    with_port = client.post("/habits", json={}, headers={"Origin": "https://manasomali.com:443"})

    assert allowed.status_code == 401
    assert with_port.status_code == 403


@pytest.mark.parametrize(
    ("headers", "allowed"),
    [
        ([(b"origin", b"https://a.example")], True),
        ([(b"host", b"a.example"), (b"origin", b"https://a.example")], True),
        ([], False),
        ([(b"origin", b"https://a.example"), (b"origin", b"https://a.example")], False),
        ([(b"origin", b"https://a.example/")], False),
        ([(b"origin", "https://á.example".encode("latin-1"))], False),
        ([(b"referer", b"https://a.example/ethos")], False),
    ],
)
def test_origin_allowed(headers, allowed):
    assert origin_allowed(headers, "https://a.example") is allowed


@pytest.mark.parametrize(
    ("path", "root", "expected"),
    [
        ("/api/ethos/internal/users/1/delete", "/api/ethos", "/internal/users/1/delete"),
        ("/internal/users/1/delete", "/api/ethos", "/internal/users/1/delete"),
        ("/api/ethos", "/api/ethos", "/"),
        ("/api/ethosx/internal/", "/api/ethos", "/api/ethosx/internal/"),
        ("/habits", "", "/habits"),
    ],
)
def test_route_path_strips_only_the_root_path(path, root, expected):
    assert route_path({"path": path, "root_path": root}) == expected


# --- cookie antigo -------------------------------------------------------------------------


def test_legacy_cookie_is_cleared_when_it_arrives(client):
    response = client.get(
        "/banners/active", headers={"Cookie": "outro=1; __Host-ethos_session=token-antigo"}
    )

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith('__Host-ethos_session=""; ')
    for attribute in ("Max-Age=0", "Path=/", "Secure", "HttpOnly", "SameSite=lax"):
        assert attribute in set_cookie
    assert "Domain" not in set_cookie


def test_legacy_cookie_is_cleared_also_on_errors(bare_client):
    response = bare_client.post("/habits", headers={"Cookie": "__Host-ethos_session=x"})

    assert response.status_code == 403
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_no_cookie_no_set_cookie(client):
    response = client.get("/banners/active", headers={"Cookie": "outro=1"})

    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    ("headers", "found"),
    [
        ([(b"cookie", b"__Host-ethos_session=abc")], True),
        ([(b"cookie", b"a=1"), (b"cookie", b"__Host-ethos_session=")], True),
        ([(b"cookie", b"__Host-imago_session=abc")], False),
        ([(b"cookie", b"x__Host-ethos_session=abc")], False),
        ([], False),
    ],
)
def test_has_legacy_cookie(headers, found):
    assert has_legacy_cookie(headers) is found


def test_row_updated_by_another_request_in_between_is_left_alone(
    db_session, engine, writes, monkeypatch
):
    # A leitura vê a linha velha; antes da trava, outro request já a atualizou: nada a gravar
    save(db_session, new_user("ana@example.com", id=4242))
    identity = read_identity(Headers(HEADERS | {"X-User-Email": "ana.nova@example.com"}))
    real = identity_module.write_transaction

    @contextmanager
    def other_request_first(session):
        with create_session_factory(engine)() as other, real(other):
            other.get(AppUser, 4242).email = "ana.nova@example.com"
        writes.clear()
        with real(session) as inside:
            yield inside

    monkeypatch.setattr(identity_module, "write_transaction", other_request_first)

    sync_app_user(db_session, identity)

    assert writes == []
    assert app_users(db_session) == [(4242, "ana.nova@example.com", "pt", "America/Sao_Paulo")]
