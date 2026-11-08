"""Cliente da API interna do imago (ETH-14): `app/imago_client.py` e o `Mailer`
(`app/mail/sender.py`), contra o imago falso (`tests/fake_imago.py`)."""

import json
import logging

import httpx2
import pytest
from pydantic import SecretStr

from app.imago_client import (
    TIMEOUT,
    ImagoClient,
    ImagoUnavailableError,
    ImagoUser,
    MailOutcome,
)
from app.mail import sender
from app.mail.catalog import HabitDeleted, Invite
from app.mail.language import Locale
from app.mail.sender import Mailer
from tests.fake_imago import INTERNAL_TOKEN, FakeImago

BASE_URL = "http://127.0.0.1:3003"


@pytest.fixture
def client(imago: FakeImago):
    imago_client = ImagoClient(BASE_URL, SecretStr(INTERNAL_TOKEN), transport=imago.transport)
    try:
        yield imago_client
    finally:
        imago_client.close()


def app_messages(caplog) -> list[str]:
    # Sem as linhas do próprio httpx2 (logger "httpx2", fora do "app", sem handler em produção)
    return [record.getMessage() for record in caplog.records if record.name.startswith("app.")]


def send(client: ImagoClient, user_id: int = 7) -> MailOutcome:
    return client.send_mail(user_id, "invite", subject="Assunto", text="Texto", html="<p>x</p>")


# --- envio ---------------------------------------------------------------------------------


def test_send_mail_posts_the_notification_with_the_token(client, imago, caplog):
    with caplog.at_level(logging.DEBUG):
        assert send(client) is MailOutcome.ACCEPTED

    [request] = imago.requests
    assert (request.method, str(request.url)) == ("POST", f"{BASE_URL}/internal/mail")
    assert request.headers["authorization"] == f"Bearer {INTERNAL_TOKEN}"
    assert json.loads(request.content) == {
        "kind": "notification",
        "user_id": 7,
        "subject": "Assunto",
        "text": "Texto",
        "html": "<p>x</p>",
    }
    assert app_messages(caplog) == ["email invite aceito pelo imago"]


@pytest.mark.parametrize(
    ("status", "outcome", "level", "message"),
    [
        (
            204,
            MailOutcome.SKIPPED,
            logging.INFO,
            "email invite não enviado: destinatário inativo no imago",
        ),
        (
            429,
            MailOutcome.REFUSED,
            logging.WARNING,
            "email invite recusado pelo teto de envio do imago",
        ),
        (500, MailOutcome.FAILED, logging.ERROR, "email invite não enviado (imago respondeu 500)"),
        (404, MailOutcome.FAILED, logging.ERROR, "email invite não enviado (imago respondeu 404)"),
        (422, MailOutcome.FAILED, logging.ERROR, "email invite não enviado (imago respondeu 422)"),
    ],
)
def test_send_mail_outcomes(client, imago, caplog, status, outcome, level, message):
    imago.mail_status = status

    with caplog.at_level(logging.DEBUG):
        assert send(client, user_id=424242) is outcome

    [record] = [record for record in caplog.records if record.name.startswith("app.")]
    assert (record.levelno, record.getMessage()) == (level, message)
    # Nem id nem token no log
    assert "424242" not in caplog.text
    assert INTERNAL_TOKEN not in caplog.text


@pytest.mark.parametrize("error", [httpx2.ConnectError, httpx2.ReadTimeout])
def test_network_error_is_failed_and_logged_by_type(client, imago, caplog, error):
    imago.error = error

    with caplog.at_level(logging.DEBUG):
        assert send(client) is MailOutcome.FAILED

    assert app_messages(caplog) == [f"email invite não enviado ({error.__name__})"]


def test_wrong_token_is_a_failure(imago, caplog):
    other = ImagoClient(BASE_URL, SecretStr("x" * 43), transport=imago.transport)
    try:
        with caplog.at_level(logging.ERROR):
            assert send(other) is MailOutcome.FAILED
    finally:
        other.close()
    assert caplog.messages == ["email invite não enviado (imago respondeu 401)"]
    assert "x" * 43 not in caplog.text


def test_client_settings():
    imago_client = ImagoClient(BASE_URL, SecretStr(INTERNAL_TOKEN))
    try:
        # Timeout curto e nada de proxy do ambiente: o token não sai do loopback
        assert imago_client._client.timeout == httpx2.Timeout(TIMEOUT)
        assert TIMEOUT == 5.0
        assert imago_client._client.trust_env is False
        assert imago_client._client.follow_redirects is False
    finally:
        imago_client.close()


# --- busca por email -----------------------------------------------------------------------


def test_lookup_sends_the_email_in_the_body(client, imago):
    imago.add_account(55, "bia@example.com", "en")

    assert client.lookup_user("bia@example.com") == ImagoUser(id=55, locale=Locale.EN)

    [request] = imago.requests
    assert str(request.url) == f"{BASE_URL}/internal/users/lookup"
    assert "bia" not in str(request.url)
    assert json.loads(request.content) == {"email": "bia@example.com"}
    assert request.headers["authorization"] == f"Bearer {INTERNAL_TOKEN}"


def test_lookup_without_account_is_none(client):
    assert client.lookup_user("ninguem@example.com") is None


@pytest.mark.parametrize("status", [500, 401, 422, 429])
def test_lookup_error_status_raises(client, imago, status, caplog):
    imago.lookup_status = status

    with caplog.at_level(logging.ERROR), pytest.raises(ImagoUnavailableError):
        client.lookup_user("bia@example.com")

    assert caplog.messages == [f"busca de usuário no imago falhou (imago respondeu {status})"]
    assert "bia@example.com" not in caplog.text


def test_lookup_network_error_raises(client, imago, caplog):
    imago.error = httpx2.ConnectTimeout

    with caplog.at_level(logging.ERROR), pytest.raises(ImagoUnavailableError):
        client.lookup_user("bia@example.com")

    assert caplog.messages == ["busca de usuário no imago falhou (ConnectTimeout)"]


@pytest.mark.parametrize(
    "content",
    [
        b"nao e json",
        b"[]",
        b'{"id": "55", "locale": "pt"}',
        b'{"id": true, "locale": "pt"}',
        b'{"id": 0, "locale": "pt"}',
        str.encode(f'{{"id": {2**53}, "locale": "pt"}}'),
        b'{"id": 55, "locale": "es"}',
        b'{"id": 55}',
    ],
)
def test_lookup_with_an_invalid_body_raises(content, caplog):
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=content)

    imago_client = ImagoClient(
        BASE_URL, SecretStr(INTERNAL_TOKEN), transport=httpx2.MockTransport(handler)
    )
    try:
        with caplog.at_level(logging.ERROR), pytest.raises(ImagoUnavailableError):
            imago_client.lookup_user("bia@example.com")
    finally:
        imago_client.close()
    assert caplog.messages == ["busca de usuário no imago falhou (resposta inválida)"]


# --- Mailer --------------------------------------------------------------------------------


def test_mailer_renders_in_the_locale_and_sends_by_id(settings, client, imago):
    mailer = Mailer(settings, client)

    outcome = mailer.send(
        9,
        Locale.EN,
        Invite(habit_name="<b>Run</b>", inviter_email="ana@example.com", role="editor"),
    )

    assert outcome is MailOutcome.ACCEPTED
    [mail] = imago.mails
    assert (mail.user_id, mail.subject) == (9, "You've been invited on ethos")
    assert "ana@example.com invited you" in mail.text
    assert "&lt;b&gt;Run&lt;/b&gt;" in mail.html
    assert "<b>Run</b>" not in mail.html
    assert "http://localhost:5174/imago/" in mail.text


def test_mailer_never_raises(settings, client, imago, monkeypatch, caplog):
    def boom(*_args, **_kwargs):
        raise RuntimeError("ana@example.com")

    monkeypatch.setattr(sender, "render", boom)

    with caplog.at_level(logging.ERROR):
        outcome = Mailer(settings, client).send(9, Locale.PT, HabitDeleted(habit_name="x"))

    assert outcome is MailOutcome.FAILED
    assert caplog.messages == ["email habit_deleted não enviado (RuntimeError)"]
    assert imago.requests == []
