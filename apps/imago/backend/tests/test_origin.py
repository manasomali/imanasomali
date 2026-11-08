"""Checagem de `Origin` nos métodos de escrita (CSRF), em todas as rotas menos `/internal/*`."""

import asyncio

import pytest

from app.auth.origin import OriginCheckMiddleware, origin_allowed, route_path
from app.main import create_app
from tests.factories import new_user, save
from tests.internal_helpers import ETHOS_TOKEN, bearer

ORIGIN = "http://localhost:8080"
FORBIDDEN = {"error": "forbidden", "field": None}


@pytest.fixture
def bare_client(app, make_client):
    """Cliente que não manda `Origin` sozinho (cada teste escolhe o header)."""
    return make_client(app, origin=False)


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        # Com caminho: o Origin nunca traz caminho, e o APP_URL inteiro não é uma origem
        "http://localhost:8080/imago",
        "http://localhost:8080/",
        # Outro esquema, porta ou host
        "https://localhost:8080",
        "http://localhost:5175",
        "http://localhost",
        "http://127.0.0.1:8080",
        "http://LOCALHOST:8080",
        "http://localhost:8080.evil.example",
        "null",
        "",
    ],
)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/auth/code/request"),
        ("POST", "/auth/code/verify"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/logout-all"),
        ("PATCH", "/me"),
        ("POST", "/me/terms"),
    ],
)
def test_wrong_origin_is_403(bare_client, method, path, origin):
    response = bare_client.request(method, path, json={}, headers={"Origin": origin})

    assert response.status_code == 403
    assert response.json() == FORBIDDEN


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "PROPFIND"])
def test_missing_origin_is_403_on_any_write_method(bare_client, method):
    # Rota que só aceita GET: a checagem vem antes do 405
    response = bare_client.request(method, "/health")

    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_missing_origin_on_login_routes_is_403(bare_client, outbox):
    response = bare_client.post("/auth/code/request", json={"email": "ana@example.com"})

    assert response.status_code == 403


def test_refused_before_reading_the_body(bare_client):
    # JSON quebrado com Origin errado: 403, não 422
    response = bare_client.post(
        "/auth/code/verify",
        content=b"{not json",
        headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
    )

    assert response.status_code == 403


def test_two_origin_headers_are_refused(bare_client):
    response = bare_client.post("/auth/logout", headers=[("Origin", ORIGIN), ("Origin", ORIGIN)])

    assert response.status_code == 403


def test_right_origin_passes(bare_client):
    # Passa a checagem e chega na rota: sem sessão, 401
    response = bare_client.post("/auth/logout", headers={"Origin": ORIGIN})

    assert response.status_code == 401


# /health só declara GET: HEAD e OPTIONS chegam na rota e levam 405, não 403
@pytest.mark.parametrize(("method", "status"), [("GET", 200), ("HEAD", 405), ("OPTIONS", 405)])
@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {}])
def test_safe_methods_are_not_checked(bare_client, method, status, headers):
    response = bare_client.request(method, "/health", headers=headers)

    assert response.status_code == status


def test_production_origin_has_no_default_port(make_settings, database, make_client):
    settings = make_settings(app_url="https://manasomali.com/imago")
    client = make_client(create_app(settings), origin=False)

    allowed = client.post("/auth/logout", headers={"Origin": "https://manasomali.com"})
    with_port = client.post("/auth/logout", headers={"Origin": "https://manasomali.com:443"})

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
        ([(b"referer", b"https://a.example/imago")], False),
    ],
)
def test_origin_allowed(headers, allowed):
    assert origin_allowed(headers, "https://a.example") is allowed


def test_internal_routes_need_no_origin(bare_client, db_session):
    user = new_user()
    save(db_session, user)
    body = {"kind": "notification", "user_id": user.id, "subject": "Oi", "text": "t", "html": "h"}

    # Sem Origin (ou com qualquer um): quem confere é o token
    without = bare_client.post("/internal/mail", json=body, headers=bearer(ETHOS_TOKEN))
    evil = bare_client.post(
        "/internal/mail",
        json=body,
        headers=bearer(ETHOS_TOKEN) | {"Origin": "https://evil.example"},
    )
    no_token = bare_client.post("/internal/mail", json=body)

    assert (without.status_code, evil.status_code, no_token.status_code) == (202, 202, 401)


@pytest.mark.parametrize(
    ("path", "root_path", "expected"),
    [
        # uvicorn --root-path: o prefixo vem no path
        ("/api/imago/internal/mail", "/api/imago", "/internal/mail"),
        ("/api/imago/me", "/api/imago", "/me"),
        ("/api/imago", "/api/imago", ""),
        # TestClient: o path vem sem o prefixo
        ("/internal/mail", "/api/imago", "/internal/mail"),
        ("/internal/mail", "", "/internal/mail"),
        # Prefixo que só começa igual não é tirado
        ("/api/imagox/internal/mail", "/api/imago", "/api/imagox/internal/mail"),
    ],
)
def test_route_path(path, root_path, expected):
    assert route_path({"path": path, "root_path": root_path}) == expected


def asgi_call(app, path: str, root_path: str) -> int:
    """Status de um POST sem Origin com o scope como o uvicorn monta (prefixo no path)."""
    sent: list[dict] = []

    async def downstream(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "root_path": root_path,
        "headers": [],
        "app": app,
    }
    asyncio.run(OriginCheckMiddleware(downstream)(scope, receive, send))
    return sent[0]["status"]


def test_internal_exemption_with_the_uvicorn_scope(app, client):
    # O client roda o lifespan, que põe a config no app.state
    assert asgi_call(app, "/api/imago/internal/mail", "/api/imago") == 200
    assert asgi_call(app, "/api/imago/me", "/api/imago") == 403
    assert asgi_call(app, "/api/imago/internalx", "/api/imago") == 403
