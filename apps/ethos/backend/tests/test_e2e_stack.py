"""O backend do E2E (`tests/e2e_stack.py`): pasta de dados, config, SMTP e caixa de entrada."""

import http.client
import json
import threading
from email.message import EmailMessage

import pytest
from pydantic import SecretStr

from app.config import EmailBackend, load_settings
from app.mail.backends import SmtpBackend
from tests.e2e_stack import (
    MARKER,
    StackError,
    mailbox_server,
    prepare_data_dir,
    stack_environment,
)
from tests.fake_smtp import SMTP_HOST, SMTP_PASSWORD, SMTP_USER


def _message(to: str, subject: str = "Seu código") -> EmailMessage:
    message = EmailMessage()
    message["From"] = "ethos <no-reply@example.com>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content("Código: 123456\n")
    return message


def _get(port: int, path: str) -> tuple[int, object]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_prepare_data_dir_creates_and_recreates(tmp_path):
    path = prepare_data_dir(tmp_path / "stack")
    assert sorted(item.name for item in path.iterdir()) == [MARKER]
    (path / "app.db").write_text("velho")

    again = prepare_data_dir(tmp_path / "stack")

    assert again == path
    assert sorted(item.name for item in again.iterdir()) == [MARKER]


def test_prepare_data_dir_accepts_empty_dir(tmp_path):
    assert (prepare_data_dir(tmp_path) / MARKER).is_file()


def test_prepare_data_dir_never_deletes_a_foreign_dir(tmp_path):
    keep = tmp_path / "importante.txt"
    keep.write_text("não apagar")

    with pytest.raises(StackError, match="não foi criada pelo E2E"):
        prepare_data_dir(tmp_path)
    with pytest.raises(StackError, match="não é uma pasta"):
        prepare_data_dir(keep)

    assert keep.read_text() == "não apagar"


def test_stack_environment_is_a_valid_smtp_config(tmp_path):
    environment = stack_environment(
        app_url="http://127.0.0.1:47830/ethos",
        data_dir=tmp_path,
        smtp_port=2525,
        ca_file=tmp_path / "ca.pem",
    )

    settings = load_settings(environment)

    assert settings.email_backend is EmailBackend.SMTP
    assert settings.app_origin == "http://127.0.0.1:47830"
    assert settings.database_path == tmp_path / "app.db"
    assert environment["SSL_CERT_FILE"] == str(tmp_path / "ca.pem")


def test_default_context_trusts_the_ca_from_ssl_cert_file(
    smtp_server, smtp_ca, tmp_path, monkeypatch
):
    # O caminho de produção (SmtpBackend sem ssl_context) confia na CA de teste pelo SSL_CERT_FILE
    ca_file = tmp_path / "ca.pem"
    smtp_ca.cert_pem.write_to_path(str(ca_file))
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))
    backend = SmtpBackend(
        host=SMTP_HOST, port=smtp_server.port, user=SMTP_USER, password=SecretStr(SMTP_PASSWORD)
    )

    backend.send(_message("ana@example.com"))

    [received] = smtp_server.received
    assert received.tls
    assert received.authenticated


def test_mailbox_lists_the_emails_of_an_address(smtp_server):
    backend = smtp_server.backend()
    backend.send(_message("Ana@Example.com", "primeiro"))
    backend.send(_message("bia@example.com", "outro"))
    backend.send(_message("ana@example.com", "segundo"))
    mailbox = mailbox_server(smtp_server, 0)
    port = mailbox.server_address[1]
    thread = threading.Thread(target=mailbox.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _get(port, "/emails?to=ANA%40example.com")
        missing_to = _get(port, "/emails")
        other_path = _get(port, "/outra?to=ana%40example.com")
        nobody = _get(port, "/emails?to=caio%40example.com")
    finally:
        mailbox.shutdown()
        mailbox.server_close()
        thread.join(timeout=5)

    assert status == 200
    assert body == [
        {"to": ["Ana@Example.com"], "subject": "primeiro", "text": "Código: 123456\n"},
        {"to": ["ana@example.com"], "subject": "segundo", "text": "Código: 123456\n"},
    ]
    assert missing_to[0] == 404
    assert other_path[0] == 404
    assert nobody == (200, [])
