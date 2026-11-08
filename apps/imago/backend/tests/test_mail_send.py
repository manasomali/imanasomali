import io
import logging
import re
import smtplib
from email.message import EmailMessage

import pytest
from fastapi import BackgroundTasks
from pydantic import SecretStr

from app.config import ConfigError, EmailBackend
from app.mail.backends import ConsoleBackend, SmtpBackend
from app.mail.catalog import AccountDeleted, EmailChangedOld, LoginCode
from app.mail.language import Locale
from app.mail.sender import (
    Mailer,
    MailerDep,
    Notification,
    OutgoingEmail,
    build_backend,
    describe,
    schedule,
)
from app.main import create_app
from tests.fake_smtp import SMTP_HOST, SMTP_PASSWORD, SMTP_USER, free_port

TO = "pessoa@exemplo.com"
CODE = "381904"
MAIL_LOGGER = "app.mail.sender"


def login_code(locale: Locale = Locale.PT, to: str = TO) -> OutgoingEmail:
    return OutgoingEmail(to, locale, LoginCode(code=CODE))


def notification(**values) -> Notification:
    fields = {
        "to": TO,
        "app": "ethos",
        "subject": "Você recebeu um convite",
        "text": "Convite para o hábito “Ler” ✓",
        "html": "<p>Convite para o hábito &ldquo;Ler&rdquo; ✓</p>",
    }
    return Notification(**(fields | values))


def mail_logs(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == MAIL_LOGGER]


def assert_nothing_sensitive(caplog, *extra: str) -> None:
    for record in caplog.records:
        text = record.getMessage()
        for sensitive in (TO, CODE, SMTP_PASSWORD, *extra):
            assert sensitive not in text
        assert record.exc_info is None


def test_smtp_server_receives_imago_email(settings, smtp_server, caplog):
    mailer = Mailer(settings, smtp_server.backend())

    with caplog.at_level(logging.INFO, logger=MAIL_LOGGER):
        assert mailer.send(login_code()) is True

    [received] = smtp_server.received
    # STARTTLS e login antes do envio
    assert received.tls
    assert received.authenticated
    assert received.mail_from == "no-reply@example.com"
    assert received.rcpt_tos == [TO]
    message = received.message
    assert message["Subject"] == "Seu código de acesso ao manasomali.com"
    assert message["From"] == '"manasomali.com" <no-reply@example.com>'
    assert message["To"] == TO
    assert message["Reply-To"] == "suporte@example.com"
    assert message["Auto-Submitted"] == "auto-generated"
    assert message["Message-ID"].endswith("@example.com>")
    assert message["Date"]
    assert CODE not in message["Subject"]
    text = received.body("plain")
    assert "Use este código para entrar na sua conta do manasomali.com:" in text
    assert f"\n{CODE}\n" in text
    assert "Nunca compartilhe este código" in text
    assert "Se não foi você que pediu, ignore este email." in text
    assert f">{CODE}</p>" in received.body("html")
    assert mail_logs(caplog) == ["email login_code enviado"]
    assert_nothing_sensitive(caplog)


def test_notification_goes_out_as_given_with_the_app_name(settings, smtp_server, caplog):
    mailer = Mailer(settings, smtp_server.backend())

    with caplog.at_level(logging.INFO, logger=MAIL_LOGGER):
        assert mailer.send(notification()) is True

    [received] = smtp_server.received
    message = received.message
    assert message["From"] == "ethos <no-reply@example.com>"
    assert message["Subject"] == "Você recebeu um convite"
    assert message["Reply-To"] == "suporte@example.com"
    assert received.body("plain") == "Convite para o hábito “Ler” ✓\n"
    assert received.body("html") == "<p>Convite para o hábito &ldquo;Ler&rdquo; ✓</p>\n"
    # 7 bits no fio, com acento e símbolo no texto
    assert message.as_bytes().isascii()
    assert mail_logs(caplog) == ["email notification (ethos) enviado"]
    assert_nothing_sensitive(caplog, "convite")


def test_describe_never_has_personal_data():
    assert describe(login_code()) == "login_code"
    assert describe(OutgoingEmail(TO, Locale.EN, EmailChangedOld(new_email="x@y.com"))) == (
        "email_changed_old"
    )
    assert describe(notification(app="engrafi")) == "notification (engrafi)"


def test_server_without_starttls_gets_nothing(settings, make_smtp_server, caplog):
    server = make_smtp_server(starttls=False)
    mailer = Mailer(settings, server.backend())

    with caplog.at_level(logging.DEBUG):
        assert mailer.send(login_code(Locale.EN)) is False

    assert server.received == []
    assert mail_logs(caplog) == ["email login_code não enviado (SMTPNotSupportedError)"]
    assert_nothing_sensitive(caplog)


def test_untrusted_certificate_is_refused(settings, smtp_server, caplog):
    # Contexto padrão: não confia na CA de teste
    mailer = Mailer(settings, smtp_server.backend(ssl_context=None))

    with caplog.at_level(logging.ERROR, logger=MAIL_LOGGER):
        assert mailer.send(login_code(Locale.EN)) is False

    assert smtp_server.received == []
    assert mail_logs(caplog) == ["email login_code não enviado (SSLCertVerificationError)"]


def test_wrong_password_is_logged_without_sensitive_data(settings, smtp_server, caplog):
    mailer = Mailer(settings, smtp_server.backend(password=SecretStr("senha-errada")))

    with caplog.at_level(logging.DEBUG):
        assert mailer.send(login_code()) is False

    assert smtp_server.received == []
    [line] = mail_logs(caplog)
    assert re.fullmatch(r"email login_code não enviado \(SMTP\w+( \d{3})?\)", line)
    assert_nothing_sensitive(caplog, "senha-errada", SMTP_USER)


def test_refused_recipient_is_logged_without_the_address(settings, caplog):
    class Refusing:
        def send(self, message: EmailMessage) -> None:
            # Mesma exceção do smtplib quando o servidor recusa o destinatário: traz o endereço
            raise smtplib.SMTPRecipientsRefused({TO: (550, f"<{TO}> {CODE}".encode())})

    with caplog.at_level(logging.DEBUG):
        assert Mailer(settings, Refusing()).send(login_code(Locale.EN)) is False

    assert mail_logs(caplog) == ["email login_code não enviado (SMTPRecipientsRefused)"]
    assert_nothing_sensitive(caplog)


def test_connection_refused_is_logged_and_not_raised(settings, caplog):
    backend = SmtpBackend(
        host=SMTP_HOST, port=free_port(), user=SMTP_USER, password=SecretStr(SMTP_PASSWORD)
    )

    with caplog.at_level(logging.ERROR, logger=MAIL_LOGGER):
        assert Mailer(settings, backend).send(notification()) is False

    assert mail_logs(caplog) == ["email notification (ethos) não enviado (ConnectionRefusedError)"]
    assert_nothing_sensitive(caplog)


def test_smtp_error_code_is_logged(settings, caplog):
    class Busy:
        def send(self, message: EmailMessage) -> None:
            raise smtplib.SMTPDataError(451, f"tente depois, {TO}".encode())

    with caplog.at_level(logging.ERROR, logger=MAIL_LOGGER):
        assert Mailer(settings, Busy()).send(login_code()) is False

    assert mail_logs(caplog) == ["email login_code não enviado (SMTPDataError 451)"]
    assert_nothing_sensitive(caplog)


@pytest.mark.parametrize("to", [f"{TO}\r\nBcc: outro@exemplo.com", f"{TO}\nBcc: x@y.z"])
def test_header_injection_in_recipient_is_refused(settings, smtp_server, caplog, to):
    mailer = Mailer(settings, smtp_server.backend())

    with caplog.at_level(logging.ERROR, logger=MAIL_LOGGER):
        assert mailer.send(login_code(Locale.EN, to=to)) is False

    assert smtp_server.received == []
    assert mail_logs(caplog) == ["email login_code não enviado (ValueError)"]
    assert_nothing_sensitive(caplog, "outro@exemplo.com")


def test_header_injection_in_subject_is_refused(settings, smtp_server, caplog):
    mailer = Mailer(settings, smtp_server.backend())

    with caplog.at_level(logging.ERROR, logger=MAIL_LOGGER):
        assert mailer.send(notification(subject="Oi\r\nBcc: outro@exemplo.com")) is False

    assert smtp_server.received == []
    assert mail_logs(caplog) == ["email notification (ethos) não enviado (ValueError)"]


def test_console_backend_shows_the_email(settings):
    stream = io.StringIO()
    mailer = Mailer(settings, ConsoleBackend(stream))

    assert mailer.send(login_code(Locale.EN)) is True

    output = stream.getvalue()
    assert f"Para: {TO}\n" in output
    assert "Assunto: Your manasomali.com sign-in code\n" in output
    # Em dev o código aparece: é o único jeito de entrar sem SMTP
    assert f"\n{CODE}\n" in output
    assert "<p>" not in output


def test_console_backend_defaults_to_stderr(capsys):
    # Só HTML: sem parte de texto, o console mostra o cabeçalho e o corpo vazio
    message = EmailMessage()
    message["To"] = TO
    message["Subject"] = "Assunto"
    message.set_content("<p>oi</p>", subtype="html")

    ConsoleBackend().send(message)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"Para: {TO}\nAssunto: Assunto\n\n\n----- fim do email -----\n" in captured.err


def test_build_backend_follows_the_config(make_settings):
    console = make_settings()
    smtp = make_settings(
        email_backend="smtp",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user=SMTP_USER,
        smtp_password=SMTP_PASSWORD,
    )

    assert isinstance(build_backend(console), ConsoleBackend)
    assert isinstance(build_backend(smtp), SmtpBackend)


def test_build_backend_refuses_smtp_without_credentials(settings):
    # model_copy não valida: a config de verdade já recusaria esta combinação
    broken = settings.model_copy(update={"email_backend": EmailBackend.SMTP})

    with pytest.raises(ConfigError, match="SMTP_HOST"):
        build_backend(broken)


def test_schedule_sends_after_the_response(settings, database, smtp_server, make_client):
    app = create_app(settings, mail_backend=smtp_server.backend())
    received_before_response: list[int] = []

    @app.post("/test/delete")
    def delete_account(background_tasks: BackgroundTasks, mailer: MailerDep) -> dict[str, str]:
        schedule(background_tasks, mailer, OutgoingEmail(TO, Locale.EN, AccountDeleted()))
        received_before_response.append(len(smtp_server.received))
        return {"status": "ok"}

    response = make_client(app).post("/test/delete")

    assert response.status_code == 200
    assert received_before_response == [0]
    [received] = smtp_server.received
    assert received.rcpt_tos == [TO]
    assert received.message["Subject"] == "Your manasomali.com account was deleted"


def test_smtp_failure_does_not_break_the_request(settings, database, make_client, caplog):
    dead = SmtpBackend(
        host=SMTP_HOST, port=free_port(), user=SMTP_USER, password=SecretStr(SMTP_PASSWORD)
    )
    app = create_app(settings, mail_backend=dead)

    @app.post("/test/login")
    def login(background_tasks: BackgroundTasks, mailer: MailerDep) -> dict[str, str]:
        schedule(background_tasks, mailer, login_code())
        return {"status": "ok"}

    with caplog.at_level(logging.DEBUG):
        response = make_client(app).post("/test/login")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert mail_logs(caplog) == ["email login_code não enviado (ConnectionRefusedError)"]
    assert_nothing_sensitive(caplog)


def test_failed_request_sends_nothing(settings, database, smtp_server, make_client):
    app = create_app(settings, mail_backend=smtp_server.backend())

    @app.post("/test/rollback")
    def rollback(background_tasks: BackgroundTasks, mailer: MailerDep) -> None:
        schedule(background_tasks, mailer, login_code())
        raise RuntimeError

    response = make_client(app, raise_server_exceptions=False).post("/test/rollback")

    assert response.status_code == 500
    assert smtp_server.received == []


def test_app_builds_the_backend_from_the_config(settings, database, make_client, capsys):
    # A config de teste usa EMAIL_BACKEND=console
    app = create_app(settings)

    @app.post("/test/send")
    def send(background_tasks: BackgroundTasks, mailer: MailerDep) -> None:
        schedule(background_tasks, mailer, OutgoingEmail(TO, Locale.EN, AccountDeleted()))

    assert make_client(app).post("/test/send").status_code == 200
    assert "Assunto: Your manasomali.com account was deleted\n" in capsys.readouterr().err
