"""`/openapi.json`, `/docs` e `/redoc`: só com `APP_ENV=dev`, nunca em produção."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import ROOT_PATH

DOCS_PATHS = ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect")


@pytest.fixture
def prod_app(make_settings, database, imago) -> FastAPI:
    settings = make_settings(app_env="prod", app_url="https://manasomali.com/ethos")
    return create_app(settings, imago_transport=imago.transport)


@pytest.mark.parametrize("path", DOCS_PATHS)
def test_docs_do_not_exist_outside_dev(prod_app, make_client, path):
    client = make_client(prod_app, origin=False)

    response = client.get(path)

    assert response.status_code == 404
    # O mesmo 404 de uma rota que nunca existiu
    assert response.json() == client.get("/nao-existe").json()


def test_the_schema_is_still_built_in_code_outside_dev(prod_app, make_client):
    make_client(prod_app, origin=False)

    assert "/habits" in prod_app.openapi()["paths"]


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/openapi.json", "application/json"),
        ("/docs", "text/html; charset=utf-8"),
        ("/redoc", "text/html; charset=utf-8"),
        ("/docs/oauth2-redirect", "text/html; charset=utf-8"),
    ],
)
def test_docs_exist_in_dev(client, path, content_type):
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"] == content_type


def test_dev_docs_use_the_public_prefix(client):
    # Como pelo proxy do Vite (README): a página busca o schema no caminho com o prefixo
    assert f"url: '{ROOT_PATH}/openapi.json'" in client.get("/docs").text
    assert {"url": ROOT_PATH} in client.get("/openapi.json").json()["servers"]


def test_a_second_startup_does_not_repeat_the_docs_routes(app):
    for _ in range(2):
        with TestClient(app, root_path=ROOT_PATH) as client:
            assert client.get("/openapi.json").status_code == 200

    paths = [getattr(route, "path", None) for route in app.routes]
    assert [paths.count(path) for path in DOCS_PATHS] == [1, 1, 1, 1]
