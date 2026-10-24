import logging
import re
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
import time_machine
from sqlalchemy import select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.audit import AuditEvent
from app.auth import service
from app.auth.cookies import SESSION_COOKIE_NAME
from app.auth.security import hash_secret
from app.main import create_app
from app.models import AuditLog, LoginCode, User, UserSession
from app.terms import TERMS_VERSION
from tests.auth_helpers import code_in, login, session_token
from tests.factories import count, new_user, save

IP = "203.0.113.7"
ANA = "ana@example.com"
BIA = "bia@example.com"
T0 = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
SUPPORT = "suporte@example.com"


@pytest.fixture
def client(settings, database, make_client, outbox):
    # Endereço do cliente como o uvicorn entrega depois do --proxy-headers
    return make_client(create_app(settings, mail_backend=outbox), client=(IP, 50000))


@pytest.fixture
def ana(db_session):
    user = new_user(ANA, timezone="America/Sao_Paulo", locale="pt")
    save(db_session, user)
    return user


def request_code(client, email=ANA, **kwargs):
    return client.post("/auth/code/request", json={"email": email}, **kwargs)


def verify(client, code, email=ANA, timezone="America/Sao_Paulo", locale="pt"):
    return client.post(
        "/auth/code/verify",
        json={"email": email, "code": code, "timezone": timezone, "locale": locale},
    )


def other_code(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def fixed_codes(monkeypatch, *codes: str) -> None:
    monkeypatch.setattr(service, "generate_code", iter(codes).__next__)


def snapshot(response) -> tuple:
    return response.status_code, response.content, tuple(sorted(response.headers.items()))


def events(db_session, event: AuditEvent) -> list[AuditLog]:
    db_session.rollback()
    return list(db_session.scalars(select(AuditLog).where(AuditLog.event == event.value)))


def login_codes(db_session, email=ANA) -> list[LoginCode]:
    db_session.rollback()
    query = select(LoginCode).where(LoginCode.email == email).order_by(LoginCode.id)
    return list(db_session.scalars(query.execution_options(populate_existing=True)))


def find_user(db_session, email=ANA) -> User | None:
    db_session.rollback()
    query = select(User).where(User.email == email).execution_options(populate_existing=True)
    return db_session.scalar(query)


# --- fluxo completo ---


def test_full_flow_with_fake_smtp(settings, database, make_client, smtp_server, db_session):
    client = make_client(
        create_app(settings, mail_backend=smtp_server.backend()), client=(IP, 50000)
    )

    response = request_code(client, "  Ana@Example.COM ", headers={"Accept-Language": "pt-BR"})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    [received] = smtp_server.received
    assert received.rcpt_tos == [ANA]
    assert received.message["Subject"] == "Seu código de acesso ao ethos"
    code = re.search(r"^([0-9]{6})$", received.body("plain"), re.MULTILINE).group(1)

    response = verify(client, code, email="ANA@example.com ", timezone="Europe/Lisbon")

    assert response.status_code == 200
    assert response.json() == {"new_account": True}
    token = session_token(response)
    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE_NAME}={token};")
    attributes = {part.strip().partition("=")[0].lower() for part in header.split(";")[1:]}
    assert attributes == {"httponly", "max-age", "path", "samesite", "secure"}
    cookie = SimpleCookie()
    cookie.load(header)
    morsel = cookie[SESSION_COOKIE_NAME]
    assert morsel["path"] == "/"
    assert morsel["samesite"].lower() == "lax"
    assert morsel["max-age"] == str(60 * 24 * 3600)
    assert morsel["domain"] == ""

    user = find_user(db_session)
    assert (user.timezone, user.locale) == ("Europe/Lisbon", "pt")
    assert (user.is_active, user.is_admin) == (True, False)
    assert user.terms_version == TERMS_VERSION
    assert user.terms_accepted_at == user.created_at == user.last_login_at
    [stored] = db_session.scalars(select(UserSession))
    # No banco, só o hash do token
    assert stored.token_hash == hash_secret(token)
    assert stored.user_id == user.id
    assert stored.expires_at - stored.created_at == timedelta(days=60)
    assert (stored.ip, stored.user_agent) == (IP, "testclient")
    [used] = login_codes(db_session)
    assert used.attempts == 1
    assert used.used_at is not None
    assert used.code_hash == hash_secret(code)
    [entry] = events(db_session, AuditEvent.LOGIN)
    assert (entry.user_id, entry.ip, entry.details) == (user.id, IP, {"new_account": True})
    # Sem conta no pedido: nada no audit_log
    assert events(db_session, AuditEvent.CODE_REQUESTED) == []


def test_second_login_reuses_the_account(client, outbox, db_session):
    with time_machine.travel(T0, tick=False) as traveller:
        first = login(client, outbox, ANA)
        traveller.shift(timedelta(minutes=2))
        assert request_code(client).status_code == 202
        response = verify(client, code_in(outbox.messages[-1]), timezone="Asia/Tokyo", locale="en")

    assert response.status_code == 200
    assert response.json() == {"new_account": False}
    assert session_token(response) != first
    assert count(db_session, User) == 1
    assert count(db_session, UserSession) == 2
    [requested] = events(db_session, AuditEvent.CODE_REQUESTED)
    assert (requested.user_id, requested.ip) == (find_user(db_session).id, IP)
    logins = events(db_session, AuditEvent.LOGIN)
    assert [entry.details for entry in logins] == [{"new_account": True}, {"new_account": False}]


def test_nothing_sensitive_in_the_logs(client, outbox, caplog):
    with caplog.at_level(logging.DEBUG):
        token = login(client, outbox, ANA)
        verify(client, "000000")

    code = code_in(outbox.messages[0])
    assert caplog.records
    for sensitive in (ANA, code, token, hash_secret(token), IP):
        assert sensitive not in caplog.text


# --- pedir código ---


def test_request_is_identical_with_and_without_account(client, outbox, db_session, ana):
    save(db_session, new_user(BIA, is_active=False))
    new_email = "caio@example.com"

    responses = [request_code(client, email) for email in (ANA, BIA, new_email)]

    assert responses[0].status_code == 202
    assert len({snapshot(response) for response in responses}) == 1
    # Conta inativa não recebe email, mas o código conta nos limites como os outros
    assert [message["To"] for message in outbox.messages] == [ANA, new_email]
    assert [len(login_codes(db_session, email)) for email in (ANA, BIA, new_email)] == [1, 1, 1]

    limited = [request_code(client, email) for email in (ANA, BIA, new_email)]

    assert limited[0].status_code == 429
    assert limited[0].json() == {"error": "rate_limited", "field": None}
    assert len({snapshot(response) for response in limited}) == 1
    assert len(outbox.messages) == 2


def test_inactive_account_gets_202_and_no_email_and_cannot_log_in(
    client, outbox, db_session, monkeypatch
):
    save(db_session, new_user(BIA, is_active=False))
    fixed_codes(monkeypatch, "424242")

    assert request_code(client, BIA).status_code == 202
    response = verify(client, "424242", email=BIA)

    assert outbox.messages == []
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_code", "field": "code"}
    assert count(db_session, UserSession) == 0
    assert [entry.ip for entry in events(db_session, AuditEvent.LOGIN_FAILED)] == [IP]
    [requested] = events(db_session, AuditEvent.CODE_REQUESTED)
    assert requested.user_id == find_user(db_session, BIA).id


@pytest.mark.parametrize(
    "email",
    [
        "",
        "   ",
        "ana",
        "ana@example",
        "ana @example.com",
        "ana@exa\u0000mple.com",
        "a" * 250 + "@x.com",
    ],
)
def test_invalid_email_is_refused(client, outbox, db_session, email):
    response = request_code(client, email)

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": "email"}
    assert count(db_session, LoginCode) == 0
    assert outbox.messages == []


def test_email_language_follows_the_account_then_the_browser(client, outbox, db_session):
    save(db_session, new_user(ANA, locale="en"))

    request_code(client, ANA, headers={"Accept-Language": "pt-BR"})
    request_code(client, BIA, headers={"Accept-Language": "pt-BR,en;q=0.5"})
    request_code(client, "caio@example.com", headers={"Accept-Language": "fr"})

    subjects = [message["Subject"] for message in outbox.messages]
    assert subjects == [
        "Your ethos sign-in code",
        "Seu código de acesso ao ethos",
        "Your ethos sign-in code",
    ]


def test_rate_limit_per_email_with_frozen_time(client, outbox):
    with time_machine.travel(T0, tick=False) as traveller:
        assert request_code(client).status_code == 202
        traveller.shift(timedelta(seconds=59))
        assert request_code(client).status_code == 429
        # Outro email não é afetado
        assert request_code(client, BIA).status_code == 202
        for minute in range(1, 5):
            traveller.move_to(T0 + timedelta(minutes=minute, seconds=1))
            assert request_code(client).status_code == 202
        # 5 na última hora
        traveller.move_to(T0 + timedelta(minutes=30))
        assert request_code(client).status_code == 429
        # O primeiro saiu da janela de 1 hora
        traveller.move_to(T0 + timedelta(hours=1, seconds=1))
        assert request_code(client).status_code == 202

    assert len(outbox.to(ANA)) == 6


def test_global_cap_and_support_alert_once_per_hour(
    make_settings, database, make_client, outbox, db_session
):
    settings = make_settings(max_code_emails_per_hour=3, max_code_emails_per_day=5)
    client = make_client(create_app(settings, mail_backend=outbox), client=(IP, 50000))

    def emails_to_support():
        return outbox.to(SUPPORT)

    with time_machine.travel(T0, tick=False) as traveller:
        for index in range(3):
            assert request_code(client, f"u{index}@example.com").status_code == 202
        capped = request_code(client, "u3@example.com")
        limited_by_email = request_code(client, "u0@example.com")
        assert capped.status_code == 429
        assert snapshot(capped) == snapshot(limited_by_email)
        assert len(emails_to_support()) == 1
        traveller.shift(timedelta(minutes=59))
        assert request_code(client, "u4@example.com").status_code == 429
        assert len(emails_to_support()) == 1

        # Janela de 1 hora livre, mas o teto do dia (5) bate no 6º
        traveller.move_to(T0 + timedelta(hours=1, seconds=1))
        assert request_code(client, "u5@example.com").status_code == 202
        assert request_code(client, "u6@example.com").status_code == 202
        assert request_code(client, "u7@example.com").status_code == 429
        assert len(emails_to_support()) == 2
        traveller.shift(timedelta(minutes=30))
        assert request_code(client, "u8@example.com").status_code == 429
        assert len(emails_to_support()) == 2

        traveller.move_to(T0 + timedelta(days=1, seconds=1))
        assert request_code(client, "u9@example.com").status_code == 202

    alerts = events(db_session, AuditEvent.SEND_CAP_REACHED)
    assert [(entry.user_id, entry.ip) for entry in alerts] == [(None, None), (None, None)]
    assert [entry.details for entry in alerts] == [
        {"window": "hour", "limit": 3},
        {"window": "day", "limit": 5},
    ]
    first, second = emails_to_support()
    assert first["Subject"] == "ethos: teto de envio de códigos atingido"
    assert "(3 por hora)" in plain_text(first)
    assert "(5 por dia)" in plain_text(second)
    # Só o código para quem pediu e os 2 avisos: nada para u3, u4, u7, u8
    assert len(outbox.messages) == 3 + 2 + 2 + 1


def plain_text(message) -> str:
    return message.get_body(preferencelist=("plain",)).get_content()


def test_new_code_invalidates_the_previous_one(client, monkeypatch):
    fixed_codes(monkeypatch, "111111", "222222")
    with time_machine.travel(T0, tick=False) as traveller:
        request_code(client)
        traveller.shift(timedelta(minutes=1, seconds=1))
        request_code(client)

        assert verify(client, "111111").status_code == 400
        assert verify(client, "222222").status_code == 200


def test_request_cleans_expired_codes_and_sessions(client, db_session, ana):
    with time_machine.travel(T0 - timedelta(days=2), tick=False):
        save(
            db_session,
            LoginCode(
                email=BIA,
                purpose="login",
                code_hash=hash_secret("123456"),
                expires_at=T0 - timedelta(days=2) + timedelta(minutes=10),
            ),
            UserSession(
                token_hash=hash_secret("velho"), user_id=ana.id, expires_at=T0 - timedelta(days=1)
            ),
        )
    save(
        db_session,
        UserSession(
            token_hash=hash_secret("valendo"), user_id=ana.id, expires_at=T0 + timedelta(days=1)
        ),
    )

    with time_machine.travel(T0, tick=False):
        assert request_code(client).status_code == 202

    db_session.rollback()
    assert count(db_session, LoginCode, LoginCode.email == BIA) == 0
    assert list(db_session.scalars(select(UserSession.token_hash))) == [hash_secret("valendo")]


# --- verificar código ---


def test_wrong_code_is_refused(client, outbox, db_session, ana):
    request_code(client)
    code = code_in(outbox.messages[0])

    response = verify(client, other_code(code))

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_code", "field": "code"}
    assert "set-cookie" not in response.headers
    # A tentativa errada ficou gravada (não sofreu rollback)
    assert login_codes(db_session)[0].attempts == 1
    [failed] = events(db_session, AuditEvent.LOGIN_FAILED)
    assert (failed.user_id, failed.ip) == (ana.id, IP)
    assert verify(client, code).status_code == 200


def test_expired_code_is_refused(client, outbox):
    with time_machine.travel(T0, tick=False) as traveller:
        request_code(client)
        code = code_in(outbox.messages[0])
        traveller.shift(timedelta(minutes=10))

        response = verify(client, code)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_code", "field": "code"}


def test_code_still_valid_just_before_ten_minutes(client, outbox):
    with time_machine.travel(T0, tick=False) as traveller:
        request_code(client)
        traveller.shift(timedelta(minutes=9, seconds=59))

        assert verify(client, code_in(outbox.messages[0])).status_code == 200


def test_used_code_is_refused(client, outbox, db_session):
    request_code(client)
    code = code_in(outbox.messages[0])
    assert verify(client, code).status_code == 200

    response = verify(client, code)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_code", "field": "code"}
    assert count(db_session, UserSession) == 1


def test_code_of_another_email_is_refused(client, outbox, db_session, monkeypatch):
    fixed_codes(monkeypatch, "111111", "222222")
    request_code(client, ANA)
    request_code(client, BIA)

    assert verify(client, "222222", email=ANA).status_code == 400
    assert verify(client, "111111", email=BIA).status_code == 400
    # Email sem código nenhum
    assert verify(client, "111111", email="caio@example.com").status_code == 400
    assert count(db_session, User) == 0
    assert verify(client, "111111", email=ANA).status_code == 200


def test_sixth_attempt_is_refused_even_with_the_right_code(client, outbox, db_session, ana):
    request_code(client)
    code = code_in(outbox.messages[0])

    for _ in range(5):
        assert verify(client, other_code(code)).status_code == 400
    response = verify(client, code)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_code", "field": "code"}
    assert login_codes(db_session)[0].attempts == 5
    assert len(events(db_session, AuditEvent.LOGIN_FAILED)) == 6
    assert count(db_session, UserSession) == 0


def test_existing_account_keeps_its_timezone_and_locale(client, outbox, db_session, ana):
    request_code(client)

    response = verify(client, code_in(outbox.messages[0]), timezone="Mars/Base", locale="en")

    assert response.status_code == 200
    assert response.json() == {"new_account": False}
    user = find_user(db_session)
    assert (user.timezone, user.locale) == ("America/Sao_Paulo", "pt")
    assert user.last_login_at is not None


def test_invalid_timezone_on_first_access(client, outbox, db_session):
    request_code(client)
    code = code_in(outbox.messages[0])

    response = verify(client, code, timezone="Mars/Base")

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_timezone", "field": "timezone"}
    assert find_user(db_session) is None
    # O código não foi gasto: o mesmo código entra com um fuso válido
    assert verify(client, code, timezone="America/Sao_Paulo").status_code == 200
    assert login_codes(db_session)[0].attempts == 2


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"code": "12345"}, "code"),
        ({"code": "1234567"}, "code"),
        ({"code": "12a456"}, "code"),
        # Dígitos de outro alfabeto
        ({"code": "١٢٣٤٥٦"}, "code"),
        ({"locale": "fr"}, "locale"),
        ({"timezone": ""}, "timezone"),
        ({"timezone": "A" * 65}, "timezone"),
        ({"email": "ana"}, "email"),
    ],
)
def test_malformed_verify_body_is_refused_without_counting(
    client, outbox, db_session, changes, field
):
    request_code(client)
    body = {"email": ANA, "code": "123456", "timezone": "UTC", "locale": "pt"} | changes

    response = client.post("/auth/code/verify", json=body)

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": field}
    assert login_codes(db_session)[0].attempts == 0


def test_audit_ip_comes_from_the_nginx_hop(settings, database, make_client, outbox, db_session):
    # Como em produção: uvicorn --proxy-headers --forwarded-allow-ips=127.0.0.1 atrás do nginx,
    # que acrescenta o $remote_addr ao X-Forwarded-For que o cliente mandou (forjado aqui)
    app = ProxyHeadersMiddleware(create_app(settings, mail_backend=outbox), "127.0.0.1")
    client = make_client(app, client=("127.0.0.1", 50000))
    save(db_session, new_user(ANA))

    response = request_code(client, headers={"X-Forwarded-For": f"198.51.100.9, {IP}"})

    assert response.status_code == 202
    [entry] = events(db_session, AuditEvent.CODE_REQUESTED)
    assert entry.ip == IP
