import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from app.errors import ApiError, ErrorCode, code_for_status, validation_field


class Habit(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class Payload(BaseModel):
    email: str
    habits: list[Habit] = []


@pytest.fixture
def routes(app):
    """Rotas só dos testes, para provocar cada tipo de erro."""

    @app.post("/test/payload")
    def payload(body: Payload, limit: int = 10) -> dict[str, int]:
        return {"habits": len(body.habits), "limit": limit}

    @app.get("/test/rule")
    def rule() -> None:
        raise ApiError(409, ErrorCode.CONFLICT, field="email")

    @app.get("/test/limited")
    def limited() -> None:
        raise ApiError(429, ErrorCode.RATE_LIMITED, headers={"Retry-After": "60"})

    @app.get("/test/http/{status}")
    def http(status: int) -> None:
        raise HTTPException(status, detail="mensagem pronta que não pode sair")

    @app.get("/test/crash")
    def crash() -> None:
        raise RuntimeError("detalhe interno")

    return app


@pytest.fixture
def api(routes, make_client):
    return make_client(routes, raise_server_exceptions=False)


def test_validation_error_names_the_field(api):
    response = api.post("/test/payload", json={"email": "a@exemplo.com", "habits": [{"name": ""}]})

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": "habits.0.name"}


def test_missing_body_field(api):
    response = api.post("/test/payload", json={})

    assert response.json() == {"error": "validation_error", "field": "email"}


def test_invalid_query_parameter(api):
    response = api.post("/test/payload?limit=x", json={"email": "a@exemplo.com"})

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": "limit"}


def test_validation_error_does_not_echo_input(api):
    response = api.post("/test/payload", json={"email": ["segredo@exemplo.com"]})

    assert response.json() == {"error": "validation_error", "field": "email"}
    assert "segredo" not in response.text


def test_malformed_json_has_no_field(api):
    response = api.post(
        "/test/payload", content=b'{"email": ', headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": None}


def test_missing_body_has_no_field(api):
    response = api.post("/test/payload")

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": None}


def test_rule_error(api):
    response = api.get("/test/rule")

    assert response.status_code == 409
    assert response.json() == {"error": "conflict", "field": "email"}


def test_rule_error_keeps_headers(api):
    response = api.get("/test/limited")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert response.json() == {"error": "rate_limited", "field": None}


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "unauthorized"), (403, "forbidden"), (418, "bad_request"), (502, "internal_error")],
)
def test_http_exception_uses_catalog(api, status, code):
    response = api.get(f"/test/http/{status}")

    assert response.status_code == status
    assert response.json() == {"error": code, "field": None}
    assert "mensagem pronta" not in response.text


def test_unknown_route(api):
    response = api.get("/nao-existe")

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "field": None}


def test_wrong_method_keeps_allow_header(api):
    response = api.delete("/health")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET"
    assert response.json() == {"error": "method_not_allowed", "field": None}


def test_unhandled_exception(api):
    response = api.get("/test/crash")

    assert response.status_code == 500
    assert response.json() == {"error": "internal_error", "field": None}


def test_every_status_maps_to_a_catalog_code():
    for status in range(400, 600):
        assert code_for_status(status) in ErrorCode


@pytest.mark.parametrize("status", [200, 302, 399, 600])
def test_api_error_requires_error_status(status):
    with pytest.raises(ValueError, match="status de erro"):
        ApiError(status, ErrorCode.CONFLICT)


def test_codes_are_unique_snake_case():
    values = [code.value for code in ErrorCode]

    assert len(values) == len(set(values))
    assert all(value.replace("_", "").isalpha() and value.islower() for value in values)


@pytest.mark.parametrize(
    ("errors", "field"),
    [
        ([], None),
        ([{"type": "missing", "loc": ()}], None),
        ([{"type": "missing", "loc": ("body",)}], None),
        ([{"type": "missing", "loc": ("x", 0)}], "x.0"),
        ([{"type": "missing", "loc": ("cookie", "c")}, {"type": "missing", "loc": ("d",)}], "c"),
    ],
)
def test_validation_field(errors, field):
    assert validation_field(RequestValidationError(errors)) == field
