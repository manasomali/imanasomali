import logging

import pytest
from pydantic import BaseModel

from app.config import AppEnv
from app.logs import APP_LOGGER, REQUEST_LOGGER, configure_logging

EMAIL = "pessoa@exemplo.com"
COOKIE = "token-da-sessao-secreto"
CODE = "123456"


class Login(BaseModel):
    email: str
    code: str


@pytest.fixture
def api(app, make_client):
    @app.post("/test/login/{code}")
    def login(code: str, body: Login) -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/test/crash")
    def crash() -> None:
        raise RuntimeError

    return make_client(app, raise_server_exceptions=False)


def request_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == REQUEST_LOGGER]


def test_one_line_per_request(api, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        api.get("/health")

    [line] = request_lines(caplog)
    method, route, status, duration = line.split(" ")
    assert (method, route, status) == ("GET", "/health", "200")
    assert duration.endswith("ms")
    float(duration.removesuffix("ms"))


def test_log_has_no_email_code_token_cookie_or_query(api, caplog):
    api.cookies.set("__Host-ethos_session", COOKIE)

    with caplog.at_level(logging.DEBUG):
        ok = api.post(
            f"/test/login/{CODE}?email={EMAIL}&token={COOKIE}",
            json={"email": EMAIL, "code": CODE},
            headers={"X-Forwarded-For": "203.0.113.9", "Authorization": f"Bearer {COOKIE}"},
        )
        invalid = api.post(f"/test/login/{CODE}", json={"email": EMAIL, "code": [CODE]})

    assert ok.status_code == 200
    assert invalid.status_code == 422
    # O molde da rota, não o caminho com o código
    lines = request_lines(caplog)
    assert len(lines) == 2
    assert lines[0].startswith("POST /test/login/{code} 200 ")
    assert lines[1].startswith("POST /test/login/{code} 422 ")
    # Tudo que o servidor logou (o httpx2 é o lado do cliente de teste)
    server_log = [r.getMessage() for r in caplog.records if r.name.split(".")[0] != "httpx2"]
    for sensitive in (EMAIL, CODE, COOKIE, "203.0.113.9", "testclient"):
        assert all(sensitive not in line for line in server_log)


def test_unmatched_route_is_not_logged_verbatim(api, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        api.get(f"/{EMAIL}")

    [line] = request_lines(caplog)
    assert line.startswith("GET - 404 ")


def test_unknown_method_is_not_logged_verbatim(api, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        api.request("BREW", "/health")

    assert request_lines(caplog)[0].startswith("OTHER /health 405 ")


def test_crash_is_logged_as_500(api, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        api.get("/test/crash")

    assert request_lines(caplog)[0].startswith("GET /test/crash 500 ")


@pytest.mark.parametrize(
    ("env", "level"), [(AppEnv.PROD, logging.INFO), (AppEnv.DEV, logging.DEBUG)]
)
def test_configure_logging_level(env, level):
    configure_logging(env)
    configure_logging(env)

    logger = logging.getLogger(APP_LOGGER)
    assert logger.level == level
    # Chamar de novo não duplica o handler
    assert len(logger.handlers) == 1
    assert logging.getLogger("uvicorn.access").disabled
