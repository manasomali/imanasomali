"""`GET /internal/session`, chamado pelo `auth_request` do nginx (ETH-18)."""

import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from sqlalchemy import Engine, event, select, update

from app.auth import deps
from app.auth.cookies import SESSION_COOKIE_NAME
from app.auth.security import generate_token, hash_secret
from app.db import write_transaction
from app.internal.router import USER_HEADERS
from app.logs import REQUEST_LOGGER
from app.models import User, UserSession
from app.terms import TERMS_VERSION
from tests.auth_helpers import cookie, open_session
from tests.factories import new_user, save

T0 = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
EMAIL = "ana@example.com"


@pytest.fixture
def nginx(app, make_client):
    # O nginx não manda Origin nem token
    return make_client(app, origin=False)


@pytest.fixture
def make_user(db_session) -> Callable[..., User]:
    def build(**fields) -> User:
        user = new_user(EMAIL, **({"terms_version": TERMS_VERSION, "locale": "en"} | fields))
        save(db_session, user)
        return user

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


def user_headers(response) -> dict[str, str]:
    return {name: response.headers[name] for name in USER_HEADERS if name in response.headers}


def ask(nginx, token: str | None, method: str = "GET"):
    headers = {} if token is None else cookie(token)
    response = nginx.request(method, "/internal/session", headers=headers)
    assert response.status_code == 200
    assert response.content == b""
    return response


def test_valid_session_returns_the_user(nginx, make_user, db_session):
    user = make_user(timezone="Europe/Lisbon")
    token = open_session(db_session, user)

    response = ask(nginx, token)

    assert user_headers(response) == {
        "X-User-Id": str(user.id),
        "X-User-Email": EMAIL,
        "X-User-Locale": "en",
        "X-User-Timezone": "Europe/Lisbon",
    }
    # Nunca devolve um cookie: o nginx não o repassaria
    assert "set-cookie" not in response.headers


def test_admin_header_only_for_admins(nginx, make_user, db_session):
    admin = make_user(is_admin=True)

    response = ask(nginx, open_session(db_session, admin))

    assert response.headers["X-User-Admin"] == "1"
    assert len(user_headers(response)) == 5


def test_large_id_is_decimal(nginx, make_user, db_session):
    user = make_user(id=2**53 - 1)

    response = ask(nginx, open_session(db_session, user))

    assert response.headers["X-User-Id"] == "9007199254740991"


@pytest.mark.parametrize("token", [None, "", "x", generate_token(), "a" * 4000, "token com espaco"])
def test_without_a_valid_cookie_there_are_no_headers(nginx, make_user, db_session, token):
    open_session(db_session, make_user())

    assert user_headers(ask(nginx, token)) == {}


@pytest.mark.parametrize(
    "change",
    [
        {"is_active": False},
        {"status": "deleting"},
        {"terms_version": "2026-01-01"},
        {"terms_version": None, "terms_accepted_at": None},
    ],
)
def test_blocked_deleting_or_pending_terms_get_no_headers(nginx, make_user, db_session, change):
    user = make_user()
    token = open_session(db_session, user)
    assert user_headers(ask(nginx, token))
    with write_transaction(db_session):
        db_session.execute(update(User).where(User.id == user.id).values(**change))

    assert user_headers(ask(nginx, token)) == {}


def test_terms_accepted_brings_the_user_back(nginx, client, make_user, db_session):
    user = make_user(terms_version="2026-01-01")
    token = open_session(db_session, user)
    assert user_headers(ask(nginx, token)) == {}

    client.post("/me/terms", json={"terms_version": TERMS_VERSION}, headers=cookie(token))

    assert user_headers(ask(nginx, token))["X-User-Id"] == str(user.id)


@pytest.mark.parametrize("method", ["HEAD", "POST", "PATCH", "DELETE"])
def test_any_method_answers_like_get(nginx, make_user, db_session, method):
    token = open_session(db_session, make_user())

    response = nginx.request(method, "/internal/session", headers=cookie(token))

    assert response.status_code == 200
    assert response.headers["X-User-Email"] == EMAIL


def test_renews_at_most_once_a_day(nginx, make_user, db_session, session_writes):
    user = make_user()
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(db_session, user)
        traveller.shift(DAY - timedelta(minutes=1))
        ask(nginx, token)
        assert session_writes() == 0
        traveller.shift(timedelta(minutes=1))
        ask(nginx, token)
        traveller.shift(timedelta(hours=5))
        ask(nginx, token)

    assert session_writes() == 1
    db_session.rollback()
    stored = db_session.scalar(select(UserSession).execution_options(populate_existing=True))
    assert stored.last_seen_at == T0 + DAY
    assert stored.expires_at == T0 + DAY + timedelta(days=60)


def test_using_only_apps_keeps_the_session_alive(nginx, make_user, db_session):
    user = make_user()
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(db_session, user)
        results = []
        # Quem só usa uma aplicação: um request por dia, 61 dias seguidos
        for _ in range(61):
            traveller.shift(DAY)
            results.append(bool(user_headers(ask(nginx, token))))
        # Depois, 61 dias parado: vence
        traveller.shift(61 * DAY)
        expired = user_headers(ask(nginx, token))

    assert all(results)
    assert expired == {}


def test_session_ended_while_renewing_gets_no_headers(nginx, make_user, db_session, monkeypatch):
    user = make_user()
    with time_machine.travel(T0, tick=False) as traveller:
        token = open_session(db_session, user)
        traveller.shift(2 * DAY)
        original = deps.write_transaction

        def racing(session):
            with write_transaction(db_session):
                db_session.execute(
                    update(UserSession)
                    .where(UserSession.token_hash == hash_secret(token))
                    .values(expires_at=T0)
                )
            return original(session)

        monkeypatch.setattr(deps, "write_transaction", racing)
        response = ask(nginx, token)

    assert user_headers(response) == {}


def test_client_x_user_headers_are_not_echoed(nginx):
    response = nginx.get(
        "/internal/session", headers={"X-User-Id": "1", "X-User-Admin": "1", "Cookie": "a=b"}
    )

    assert user_headers(response) == {}


def test_headers_never_reach_the_log(nginx, make_user, db_session, caplog):
    user = make_user(is_admin=True)
    token = open_session(db_session, user)

    with caplog.at_level(logging.DEBUG):
        ask(nginx, token)

    # Só os logs do app (o cliente de teste loga a URL do request no dele)
    app_records = [record for record in caplog.records if record.name.startswith("app")]
    lines = [record.getMessage() for record in app_records]
    assert [record.name for record in app_records] == [REQUEST_LOGGER]
    assert lines[0].startswith("GET /internal/session 200 ")
    for secret in (token, EMAIL, str(user.id), SESSION_COOKIE_NAME):
        assert secret not in lines[0]
