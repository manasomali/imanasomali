"""`POST /auth/code/request` e `POST /auth/code/verify` (ETH-17), pela API."""

import logging
import re
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
import time_machine
from sqlalchemy import select

from app.auth import service
from app.auth.cookies import SESSION_COOKIE_NAME
from app.auth.security import hash_secret
from app.main import create_app
from app.models import AuditLog, LoginCode, MailLog, User, UserSession
from app.terms import TERMS_VERSION
from tests.auth_helpers import code_in, session_token
from tests.factories import count, new_user, save

IP = "203.0.113.7"
ANA = "ana@example.com"
BIA = "bia@example.com"
SUPPORT = "suporte@example.com"
T0 = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
COOKIE_MAX_AGE = 400 * 24 * 3600


@pytest.fixture
def client(app, make_client):
    # Endereço do cliente como o uvicorn entrega depois do --proxy-headers
    return make_client(app, client=(IP, 50000))


def request_code(client, email=ANA, **kwargs):
    return client.post("/auth/code/request", json={"email": email}, **kwargs)


def verify(client, code, email=ANA, timezone="America/Sao_Paulo", locale="pt"):
    return client.post(
        "/auth/code/verify",
        json={"email": email, "code": code, "timezone": timezone, "locale": locale},
    )


def snapshot(response) -> tuple:
    return response.status_code, response.content, tuple(sorted(response.headers.items()))


def find_user(db_session, email=ANA) -> User | None:
    db_session.rollback()
    query = select(User).where(User.email == email).execution_options(populate_existing=True)
    return db_session.scalar(query)


def test_full_flow_with_fake_smtp(settings, database, make_client, smtp_server, db_session):
    client = make_client(
        create_app(settings, mail_backend=smtp_server.backend()), client=(IP, 50000)
    )

    response = request_code(client, "  Ana@Example.COM ", headers={"Accept-Language": "pt-BR"})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    [received] = smtp_server.received
    assert received.rcpt_tos == [ANA]
    assert received.message["From"] == '"manasomali.com" <no-reply@example.com>'
    assert received.message["Subject"] == "Seu código de acesso ao manasomali.com"
    code = re.search(r"^([0-9]{6})$", received.body("plain"), re.MULTILINE).group(1)

    response = verify(client, code, email="ANA@example.com ", timezone="Europe/Lisbon")

    assert response.status_code == 200
    assert response.json() == {"new_account": True}
    token = session_token(response)
    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE_NAME}={token};")
    attributes = {part.strip().partition("=")[0].lower() for part in header.split(";")[1:]}
    assert attributes == {"httponly", "max-age", "path", "samesite", "secure"}
    jar = SimpleCookie()
    jar.load(header)
    morsel = jar[SESSION_COOKIE_NAME]
    assert morsel["path"] == "/"
    assert morsel["samesite"].lower() == "lax"
    # 400 dias: quem decide a validade é o expires_at da sessão (60 dias sem uso)
    assert morsel["max-age"] == str(COOKIE_MAX_AGE)
    assert morsel["domain"] == ""

    user = find_user(db_session)
    assert (user.timezone, user.locale, user.status) == ("Europe/Lisbon", "pt", "active")
    assert user.terms_version == TERMS_VERSION
    [stored] = db_session.scalars(select(UserSession))
    assert stored.token_hash == hash_secret(token)
    assert stored.user_id == user.id
    assert stored.expires_at - stored.created_at == timedelta(days=60)
    assert (stored.ip, stored.user_agent) == (IP, "testclient")
    [entry] = db_session.scalars(select(AuditLog).where(AuditLog.event == "login"))
    assert (entry.user_id, entry.ip, entry.details) == (user.id, IP, {"new_account": True})
    # O token e o código nunca vão para o banco em claro
    assert token not in str(entry.details)


def test_new_account_gets_the_email_in_the_browser_language(client, outbox):
    request_code(client, headers={"Accept-Language": "en-US,en;q=0.9"})

    [message] = outbox.messages
    assert message["Subject"] == "Your manasomali.com sign-in code"


def test_existing_account_with_another_timezone_keeps_its_own(client, outbox, db_session):
    save(db_session, new_user(ANA, timezone="America/Sao_Paulo", locale="en"))
    request_code(client)

    response = verify(client, code_in(outbox.messages[0]), timezone="Asia/Tokyo", locale="pt")

    assert response.json() == {"new_account": False}
    user = find_user(db_session)
    assert (user.timezone, user.locale) == ("America/Sao_Paulo", "en")


@pytest.mark.parametrize("values", [{}, {"is_active": False}, {"status": "deleting"}])
def test_same_response_with_and_without_account(client, outbox, db_session, values):
    save(db_session, new_user(BIA, **values))

    with_account = request_code(client, BIA)
    without_account = request_code(client, "ninguem@example.com")

    assert snapshot(with_account) == snapshot(without_account)
    assert with_account.status_code == 202
    # Conta bloqueada ou em exclusão não recebe email
    assert len(outbox.to(BIA)) == (1 if not values else 0)


def test_rate_limit_is_the_same_429_for_any_email(client, db_session):
    save(db_session, new_user(BIA))
    request_code(client, BIA)
    request_code(client, ANA)

    with_account = request_code(client, BIA)
    without_account = request_code(client, ANA)

    assert with_account.status_code == 429
    assert with_account.json() == {"error": "rate_limited", "field": None}
    assert snapshot(with_account) == snapshot(without_account)


def test_cap_reached_is_429_and_support_gets_one_notice(client, outbox, db_session):
    save(db_session, *(MailLog(app="ethos", kind="notification") for _ in range(60)))

    first = request_code(client, ANA)
    second = request_code(client, BIA)

    assert first.status_code == second.status_code == 429
    assert first.json() == {"error": "rate_limited", "field": None}
    [notice] = outbox.messages
    assert notice["To"] == SUPPORT
    assert notice["Subject"] == "manasomali.com: teto de envio de email atingido"
    db_session.rollback()
    assert count(db_session, LoginCode) == 0


def test_code_still_passes_when_notifications_are_capped(client, outbox, db_session):
    # 215 notificações nas 24 h param as aplicações, mas não o login
    save(
        db_session,
        *(
            MailLog(app="ethos", kind="notification", created_at=T0 - timedelta(minutes=6 * i))
            for i in range(215)
        ),
    )

    with time_machine.travel(T0, tick=False):
        response = request_code(client)

    assert response.status_code == 202
    assert len(outbox.to(ANA)) == 1


@pytest.mark.parametrize(
    "email",
    ["", "ana", "ana@example", "joão@exemplo.com", "a" * 250 + "@example.com", None, 12],
)
def test_invalid_email_is_422(client, outbox, email):
    response = request_code(client, email)

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": "email"}
    assert outbox.messages == []


def test_wrong_code_is_400_and_counts(client, outbox, db_session):
    request_code(client)
    code = code_in(outbox.messages[0])

    response = verify(client, f"{(int(code) + 1) % 10**6:06d}")

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_code", "field": "code"}
    assert "set-cookie" not in response.headers
    db_session.rollback()
    assert db_session.scalar(select(LoginCode.attempts)) == 1


def test_unknown_timezone_on_first_access_is_422(client, outbox):
    request_code(client)

    response = verify(client, code_in(outbox.messages[0]), timezone="Mars/Base")

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_timezone", "field": "timezone"}


@pytest.mark.parametrize(
    ("field", "value"),
    [("code", "12345"), ("code", "١٢٣٤٥٦"), ("code", 123456), ("locale", "es"), ("timezone", "")],
)
def test_malformed_verify_body_is_422(client, field, value):
    body = {"email": ANA, "code": "123456", "timezone": "UTC", "locale": "pt"} | {field: value}

    response = client.post("/auth/code/verify", json=body)

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": field}


def test_codes_and_tokens_never_reach_the_logs(client, outbox, caplog):
    with caplog.at_level(logging.DEBUG):
        request_code(client)
        code = code_in(outbox.messages[0])
        token = session_token(verify(client, code))

    for record in caplog.records:
        message = record.getMessage()
        for secret in (code, token, ANA, IP):
            assert secret not in message


def test_fixed_code_round_trip(client, outbox, monkeypatch):
    monkeypatch.setattr(service, "generate_code", lambda: "000042")

    request_code(client)

    assert code_in(outbox.messages[0]) == "000042"
    assert verify(client, "000042").status_code == 200
