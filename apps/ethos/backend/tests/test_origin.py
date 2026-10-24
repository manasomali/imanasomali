"""Checagem de `Origin` nos métodos de escrita (CSRF), em todas as rotas (ETH-18)."""

import pytest

from app.auth.origin import origin_allowed
from app.main import create_app

ORIGIN = "http://localhost:5174"
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
    [
        ("POST", "/auth/code/request"),
        ("POST", "/auth/code/verify"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/logout-all"),
        ("PATCH", "/auth/me"),
        ("POST", "/auth/me/terms"),
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
    settings = make_settings(app_url="https://manasomali.com/ethos")
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
        ([(b"referer", b"https://a.example/ethos")], False),
    ],
)
def test_origin_allowed(headers, allowed):
    assert origin_allowed(headers, "https://a.example") is allowed
