"""`POST /internal/mail` e o token de cada aplicação em `/internal/*` (ETH-58)."""

import logging
import re
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from pydantic import SecretStr
from sqlalchemy import select

from app.body_limit import MAX_BODY_BYTES
from app.mail.backends import SmtpBackend
from app.main import create_app
from app.models import MAX_ACCOUNT_ID, MailLog, User
from tests.factories import count, new_user, save
from tests.fake_smtp import SMTP_HOST, SMTP_PASSWORD, SMTP_USER, free_port
from tests.internal_helpers import ENGRAFI_TOKEN, ETHOS_TOKEN, bearer

NOW = datetime(2026, 3, 10, 20, 0, tzinfo=UTC)
UNAUTHORIZED = {"error": "unauthorized", "field": None}
EMAIL = "bia@example.com"


@pytest.fixture
def bia(db_session) -> User:
    user = new_user(EMAIL, locale="en")
    save(db_session, user)
    return user


@pytest.fixture
def internal(app, make_client):
    # As aplicações chamam direto, sem Origin (não são um navegador)
    return make_client(app, origin=False)


def payload(user_id: int, **values) -> dict:
    return {
        "kind": "notification",
        "user_id": user_id,
        "subject": "You were invited",
        "text": "Habit “Read” ✓",
        "html": "<p>Habit &ldquo;Read&rdquo; ✓</p>",
    } | values


def test_notification_is_accepted_and_sent_after_the_log_row(internal, outbox, db_session, bia):
    with time_machine.travel(NOW, tick=False):
        response = internal.post(
            "/internal/mail", json=payload(bia.id), headers=bearer(ETHOS_TOKEN)
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    [message] = outbox.messages
    # O imago põe o endereço atual da pessoa e o nome da aplicação do token
    assert message["To"] == EMAIL
    assert message["From"] == "ethos <no-reply@example.com>"
    assert message["Subject"] == "You were invited"
    assert message.get_body(("plain",)).get_content() == "Habit “Read” ✓\n"
    assert message.get_body(("html",)).get_content() == "<p>Habit &ldquo;Read&rdquo; ✓</p>\n"
    db_session.rollback()
    [row] = db_session.scalars(select(MailLog))
    assert (row.app, row.kind, row.created_at) == ("ethos", "notification", NOW)


def test_app_comes_from_the_token(internal, outbox, db_session, bia):
    response = internal.post("/internal/mail", json=payload(bia.id), headers=bearer(ENGRAFI_TOKEN))

    assert response.status_code == 202
    assert outbox.messages[0]["From"] == "engrafi <no-reply@example.com>"
    db_session.rollback()
    assert db_session.scalar(select(MailLog.app)) == "engrafi"


def test_body_cannot_choose_the_app(internal, outbox, bia):
    response = internal.post(
        "/internal/mail", json=payload(bia.id, app="imago"), headers=bearer(ETHOS_TOKEN)
    )

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": "app"}
    assert outbox.messages == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        bearer("x" * 43),
        bearer(ETHOS_TOKEN[:-1]),
        {"Authorization": f"Basic {ETHOS_TOKEN}"},
        {"Authorization": ETHOS_TOKEN},
        {"Authorization": "Bearer "},
        {"Authorization": f"Bearer  {ETHOS_TOKEN}"},
    ],
)
def test_without_the_right_token_is_401(internal, outbox, db_session, bia, headers):
    response = internal.post("/internal/mail", json=payload(bia.id), headers=headers)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert outbox.messages == []
    db_session.rollback()
    assert count(db_session, MailLog) == 0


def test_bearer_scheme_is_case_insensitive(internal, bia):
    headers = {"Authorization": f"bearer {ETHOS_TOKEN}"}

    assert internal.post("/internal/mail", json=payload(bia.id), headers=headers).status_code == 202


def test_two_authorization_headers_are_refused(internal, bia):
    headers = [("Authorization", f"Bearer {ETHOS_TOKEN}"), ("Authorization", "Bearer outro")]

    response = internal.post("/internal/mail", json=payload(bia.id), headers=headers)

    assert response.status_code == 401


def test_token_of_an_app_outside_imago_apps_is_refused(make_settings, database, make_client, bia):
    # O engrafi ainda tem token, mas saiu do IMAGO_APPS
    settings = make_settings(imago_apps="ethos=http://127.0.0.1:3001")
    client = make_client(create_app(settings), origin=False)

    response = client.post("/internal/mail", json=payload(bia.id), headers=bearer(ENGRAFI_TOKEN))

    assert response.status_code == 401


def test_every_internal_route_but_session_requires_the_token(app, internal):
    # Pelo schema do OpenAPI: lista todas as rotas, inclusive as que entrarem depois
    paths = {
        path: ops for path, ops in app.openapi()["paths"].items() if path.startswith("/internal/")
    }
    # O /internal/session fica fora do schema (e não exige token: tests/test_internal_session.py)
    assert "/internal/mail" in paths
    assert "/internal/session" not in paths
    for path, operations in paths.items():
        url = re.sub(r"\{[^}]+\}", "1", path)
        for method in operations:
            response = internal.request(method.upper(), url, json={})
            assert response.status_code == 401, (method, path)


def test_unknown_user_is_404(internal, outbox, db_session):
    response = internal.post("/internal/mail", json=payload(424242), headers=bearer(ETHOS_TOKEN))

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "field": None}
    assert outbox.messages == []
    db_session.rollback()
    assert count(db_session, MailLog) == 0


@pytest.mark.parametrize("values", [{"is_active": False}, {"status": "deleting"}])
def test_blocked_or_deleting_user_gets_nothing_and_counts_nothing(
    internal, outbox, db_session, values
):
    user = new_user(EMAIL, **values)
    save(db_session, user)

    response = internal.post("/internal/mail", json=payload(user.id), headers=bearer(ETHOS_TOKEN))

    assert response.status_code == 204
    assert response.content == b""
    assert outbox.messages == []
    db_session.rollback()
    assert count(db_session, MailLog) == 0


def test_quota_reached_is_429_and_nothing_goes_out(internal, outbox, db_session, bia):
    rows = [
        MailLog(app="ethos", kind="notification", created_at=NOW - timedelta(minutes=minute))
        for minute in range(45)
    ]
    save(db_session, *rows)

    with time_machine.travel(NOW, tick=False):
        response = internal.post(
            "/internal/mail", json=payload(bia.id), headers=bearer(ETHOS_TOKEN)
        )

    assert response.status_code == 429
    assert response.json() == {"error": "mail_quota", "field": None}
    assert outbox.messages == []
    db_session.rollback()
    assert count(db_session, MailLog) == 45


@pytest.mark.parametrize(
    ("values", "field"),
    [
        ({"kind": "code"}, "kind"),
        ({"kind": None}, "kind"),
        ({"user_id": "12"}, "user_id"),
        ({"user_id": 12.0}, "user_id"),
        ({"user_id": True}, "user_id"),
        ({"user_id": 0}, "user_id"),
        ({"user_id": MAX_ACCOUNT_ID + 1}, "user_id"),
        ({"subject": ""}, "subject"),
        ({"subject": "x" * 201}, "subject"),
        ({"subject": "Oi\nBcc: x@y.com"}, "subject"),
        ({"subject": "Oi\r"}, "subject"),
        ({"subject": "Oi\u2028tchau"}, "subject"),
        ({"subject": "Oi\tvocê"}, "subject"),
        ({"text": ""}, "text"),
        ({"html": ""}, "html"),
        ({"to": "outro@example.com"}, "to"),
    ],
)
def test_validation(internal, outbox, bia, values, field):
    response = internal.post(
        "/internal/mail", json=payload(bia.id) | values, headers=bearer(ETHOS_TOKEN)
    )

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": field}
    assert outbox.messages == []


def test_missing_field(internal, bia):
    body = payload(bia.id)
    del body["html"]

    response = internal.post("/internal/mail", json=body, headers=bearer(ETHOS_TOKEN))

    assert response.json() == {"error": "validation_error", "field": "html"}


def test_subject_at_the_limit_and_body_close_to_100_kb(internal, outbox, bia):
    body = payload(bia.id, subject="ç" * 200, text="t" * (MAX_BODY_BYTES - 1000))

    response = internal.post("/internal/mail", json=body, headers=bearer(ETHOS_TOKEN))

    assert response.status_code == 202
    assert outbox.messages[0]["Subject"] == "ç" * 200


@pytest.mark.parametrize(
    "subject",
    [
        # Espaço não separável, emoji com ZWJ e marca de direção (RLM): só não pode quebrar a linha
        "Convite\u00a0para “Ler”",
        "Família \U0001f468\u200d\U0001f469\u200d\U0001f467",
        "\u200fOi",
    ],
)
def test_subject_accepts_unicode_on_one_line(internal, outbox, bia, subject):
    response = internal.post(
        "/internal/mail", json=payload(bia.id, subject=subject), headers=bearer(ETHOS_TOKEN)
    )

    assert response.status_code == 202
    assert outbox.messages[0]["Subject"] == subject


def test_smtp_down_keeps_the_log_row(settings, database, make_client, db_session, bia, caplog):
    dead = SmtpBackend(
        host=SMTP_HOST, port=free_port(), user=SMTP_USER, password=SecretStr(SMTP_PASSWORD)
    )
    client = make_client(create_app(settings, mail_backend=dead), origin=False)

    with caplog.at_level(logging.ERROR, logger="app.mail.sender"):
        response = client.post("/internal/mail", json=payload(bia.id), headers=bearer(ETHOS_TOKEN))

    # A aplicação não fica sabendo: o SMTP roda depois da resposta
    assert response.status_code == 202
    assert [r.getMessage() for r in caplog.records] == [
        "email notification (ethos) não enviado (ConnectionRefusedError)"
    ]
    assert EMAIL not in caplog.text
    db_session.rollback()
    assert count(db_session, MailLog) == 1


def test_smtp_server_receives_the_notification(settings, database, make_client, smtp_server, bia):
    client = make_client(create_app(settings, mail_backend=smtp_server.backend()), origin=False)

    response = client.post("/internal/mail", json=payload(bia.id), headers=bearer(ETHOS_TOKEN))

    assert response.status_code == 202
    [received] = smtp_server.received
    assert received.tls
    assert received.authenticated
    assert received.rcpt_tos == [EMAIL]
    assert received.message["From"] == "ethos <no-reply@example.com>"
    assert received.body("plain") == "Habit “Read” ✓\n"
