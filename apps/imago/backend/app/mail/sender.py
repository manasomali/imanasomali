"""Montagem e envio dos emails, e o agendamento em BackgroundTasks depois do commit.

Dois tipos de email saem daqui, sempre do mesmo endereço (`MAIL_FROM_ADDRESS`):

- os do próprio imago (`OutgoingEmail`, do catálogo de `app/mail/catalog.py`), com o nome
  "manasomali.com" no remetente e os textos de `app/mail/templates.py`;
- as notificações das aplicações (`Notification`, do `POST /internal/mail`), já prontas no idioma
  da pessoa, com o nome da aplicação do token no remetente (ex.: "ethos <no-reply@...>").

Uso num endpoint (sempre `def`), depois que a transação que gravou o `mail_log` fechou:

    with write_transaction(session):
        ...
    schedule(background_tasks, mailer, OutgoingEmail(user.email, locale, AccountDeleted()))

O FastAPI roda a tarefa depois de mandar a resposta; se o endpoint levantar exceção, a tarefa não
roda. Quem não está num request (CLI) chama `mailer.send(...)` direto.

Falha de envio nunca propaga: vira uma linha de erro no log com o tipo do email e o tipo do erro
(e o código SMTP, se houver). Nunca o destinatário, o código, o assunto, o corpo nem a mensagem da
exceção, que pode trazer o endereço (ex.: `SMTPRecipientsRefused`).
"""

import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Request

from app.config import ConfigError, EmailBackend, Settings
from app.mail.backends import ConsoleBackend, MailBackend, SmtpBackend
from app.mail.catalog import Email
from app.mail.language import Locale
from app.mail.templates import render

logger = logging.getLogger(__name__)

# Nome no remetente dos emails do próprio imago
IMAGO_SENDER_NAME = "manasomali.com"


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """Email do catálogo do imago, a mandar para `to` no idioma `locale`."""

    to: str = field(repr=False)
    locale: Locale
    email: Email


@dataclass(frozen=True, slots=True)
class Notification:
    """Email pronto de uma aplicação (`POST /internal/mail`), já no idioma da pessoa."""

    to: str = field(repr=False)
    # Nome da aplicação do token: vai no remetente e no log
    app: str
    subject: str = field(repr=False)
    text: str = field(repr=False)
    html: str = field(repr=False)


type Outgoing = OutgoingEmail | Notification


class Mailer:
    """Monta os emails com a config do app e entrega pelo backend escolhido.

    Não guarda estado entre envios, então pode ser usado por várias threads ao mesmo tempo.
    """

    def __init__(self, settings: Settings, backend: MailBackend) -> None:
        self._settings = settings
        self._backend = backend
        # Domínio do Message-ID: o do remetente (sem ele, o make_msgid consulta o DNS da máquina)
        self._domain = settings.mail_from_address.rpartition("@")[2]

    def build(self, outgoing: Outgoing) -> EmailMessage:
        """Monta a mensagem. Levanta ValueError se um cabeçalho tiver quebra de linha."""
        if isinstance(outgoing, Notification):
            sender, subject, text, html = (
                outgoing.app,
                outgoing.subject,
                outgoing.text,
                outgoing.html,
            )
        else:
            rendered = render(
                outgoing.email,
                outgoing.locale,
                app_url=self._settings.app_url,
                support_email=self._settings.support_email,
            )
            sender, subject, text, html = (
                IMAGO_SENDER_NAME,
                rendered.subject,
                rendered.text,
                rendered.html,
            )
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((sender, self._settings.mail_from_address))
        message["To"] = outgoing.to
        # O remetente é no-reply: resposta vai para o suporte
        message["Reply-To"] = self._settings.support_email
        message["Date"] = formatdate(usegmt=True)
        message["Message-ID"] = make_msgid(domain=self._domain)
        # RFC 3834: email automático, sem resposta automática de volta
        message["Auto-Submitted"] = "auto-generated"
        # quoted-printable mantém a mensagem em 7 bits, aceita por qualquer servidor
        message.set_content(text, cte="quoted-printable")
        message.add_alternative(html, subtype="html", cte="quoted-printable")
        return message

    def send(self, outgoing: Outgoing) -> bool:
        """Monta e envia. Devolve False se falhou (já logado); nunca levanta."""
        label = describe(outgoing)
        try:
            self._backend.send(self.build(outgoing))
        except Exception as exc:
            logger.error("email %s não enviado (%s)", label, _describe_error(exc))
            return False
        logger.info("email %s enviado", label)
        return True


def describe(outgoing: Outgoing) -> str:
    """Tipo do email para o log, sem dado da pessoa: "login_code" ou "notification (ethos)"."""
    if isinstance(outgoing, Notification):
        return f"notification ({outgoing.app})"
    return outgoing.email.kind.value


def _describe_error(exc: Exception) -> str:
    # Só o tipo e o código numérico: a mensagem e o smtp_error podem citar o destinatário
    name = type(exc).__name__
    code = getattr(exc, "smtp_code", None)
    return f"{name} {code}" if isinstance(code, int) else name


def build_backend(settings: Settings) -> MailBackend:
    """Backend do `EMAIL_BACKEND`. A config já garante as `SMTP_*` e o console só em dev."""
    if settings.email_backend is EmailBackend.CONSOLE:
        return ConsoleBackend()
    host, port, user, password = (
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_user,
        settings.smtp_password,
    )
    if host is None or port is None or user is None or password is None:
        raise ConfigError(
            "EMAIL_BACKEND=smtp exige SMTP_HOST, SMTP_PORT, SMTP_USER e SMTP_PASSWORD"
        )
    return SmtpBackend(host=host, port=port, user=user, password=password)


def get_mailer(request: Request) -> Mailer:
    """Dependência do FastAPI: o Mailer criado na subida do app."""
    return request.app.state.mailer


MailerDep = Annotated[Mailer, Depends(get_mailer)]


def schedule(background_tasks: BackgroundTasks, mailer: Mailer, outgoing: Outgoing) -> None:
    """Agenda o envio para depois da resposta. Chame depois do `write_transaction` fechar."""
    background_tasks.add_task(mailer.send, outgoing)
