"""Servidor SMTP falso (aiosmtpd), com STARTTLS e login obrigatórios, do backend do E2E.

Funciona como o provedor: só aceita AUTH depois do STARTTLS, e o certificado vem de uma CA de
teste (`trustme`). O app não fala com SMTP (os emails saem pelo imago): o servidor fica para o
`tests/e2e_stack.py`. `FakeSmtpServer.send(mensagem)` manda por ele com o caminho completo
(STARTTLS com o certificado verificado, login, envio). A fixture fica em `conftest.py`
(`smtp_server`).
"""

import smtplib
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

import trustme
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, Envelope, LoginPassword, Session

SMTP_HOST = "127.0.0.1"
SMTP_USER = "ethos-test@smtp.example.com"
# Credencial só do servidor falso
SMTP_PASSWORD = "senha-de-teste-do-smtp"  # noqa: S105


@dataclass(frozen=True)
class ReceivedEmail:
    mail_from: str
    rcpt_tos: list[str]
    message: EmailMessage
    # A sessão estava em TLS e autenticada quando o DATA chegou
    tls: bool
    authenticated: bool

    def body(self, subtype: str) -> str:
        """Conteúdo decodificado da parte text/<subtype>, com fim de linha "\\n"."""
        part = self.message.get_body(preferencelist=(subtype,))
        assert part is not None
        return part.get_content().replace("\r\n", "\n")


@dataclass
class FakeSmtpServer:
    port: int
    client_context: ssl.SSLContext
    received: list[ReceivedEmail] = field(default_factory=list)

    def send(self, message: EmailMessage, *, context: ssl.SSLContext | None = None) -> None:
        """Manda `message` por este servidor: STARTTLS (com `context`, por padrão um que confia na
        CA de teste), login e envio."""
        with smtplib.SMTP(SMTP_HOST, self.port, timeout=5.0) as smtp:
            smtp.starttls(context=context or self.client_context)
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(message)


class _Handler:
    def __init__(self, server: FakeSmtpServer) -> None:
        self.server = server

    async def handle_DATA(self, server: Any, session: Session, envelope: Envelope) -> str:
        message = message_from_bytes(envelope.original_content or b"", policy=policy.default)
        assert isinstance(message, EmailMessage)
        self.server.received.append(
            ReceivedEmail(
                mail_from=str(envelope.mail_from),
                rcpt_tos=list(envelope.rcpt_tos),
                message=message,
                tls=session.ssl is not None,
                authenticated=bool(session.authenticated),
            )
        )
        return "250 OK"


def _authenticate(
    server: Any, session: Session, envelope: Envelope, mechanism: str, auth_data: Any
) -> AuthResult:
    ok = (
        isinstance(auth_data, LoginPassword)
        and auth_data.login == SMTP_USER.encode()
        and auth_data.password == SMTP_PASSWORD.encode()
    )
    return AuthResult(success=ok)


def free_port() -> int:
    """Porta livre em 127.0.0.1 (o Controller do aiosmtpd não aceita a porta 0)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((SMTP_HOST, 0))
        return sock.getsockname()[1]


def start_fake_smtp(ca: trustme.CA) -> tuple[FakeSmtpServer, Callable[[], None]]:
    """Sobe o servidor numa thread. Devolve o servidor e a função que o para."""
    client_context = ssl.create_default_context()
    ca.configure_trust(client_context)
    server = FakeSmtpServer(port=free_port(), client_context=client_context)
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert(SMTP_HOST).configure_cert(server_context)
    controller = Controller(
        _Handler(server),
        hostname=SMTP_HOST,
        port=server.port,
        authenticator=_authenticate,
        auth_required=True,
        auth_require_tls=True,
        tls_context=server_context,
        require_starttls=True,
    )
    controller.start()
    return server, controller.stop
