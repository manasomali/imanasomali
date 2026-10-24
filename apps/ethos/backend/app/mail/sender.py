"""Montagem e envio dos emails, e o agendamento em BackgroundTasks depois do commit.

Uso num endpoint (sempre `def`), depois que a transação fechou:

    with write_transaction(session):
        ...
    locale = pick_locale(user.locale)
    schedule_email(background_tasks, mailer, user.email, locale, HabitDeleted(habit_name=name))

O FastAPI roda a tarefa depois de mandar a resposta; se o endpoint levantar exceção, a tarefa não
roda. Quem não está num request (o CLI dos alertas) chama `mailer.send(...)` direto.

Falha de envio nunca propaga: vira uma linha de erro no log com o tipo do email e o tipo do erro
(e o código SMTP, se houver). Nunca o destinatário, o código, o corpo nem a mensagem da exceção,
que pode trazer o endereço (ex.: `SMTPRecipientsRefused`).
"""

import logging
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Request

from app.config import ConfigError, EmailBackend, Settings
from app.mail.backends import ConsoleBackend, MailBackend, SmtpBackend
from app.mail.catalog import Email
from app.mail.language import Locale
from app.mail.templates import render

logger = logging.getLogger(__name__)


class Mailer:
    """Monta os emails do catálogo com a config do app e entrega pelo backend escolhido.

    Não guarda estado entre envios, então pode ser usado por várias threads ao mesmo tempo.
    """

    def __init__(self, settings: Settings, backend: MailBackend) -> None:
        self._settings = settings
        self._backend = backend
        # Domínio do Message-ID: o do remetente (sem ele, o make_msgid consulta o DNS da máquina)
        self._domain = parseaddr(settings.mail_from)[1].rpartition("@")[2]

    def build(self, to: str, locale: Locale, email: Email) -> EmailMessage:
        """Monta a mensagem. Levanta ValueError se `to` tiver quebra de linha."""
        rendered = render(
            email,
            locale,
            app_url=self._settings.app_url,
            support_email=self._settings.support_email,
        )
        message = EmailMessage()
        message["Subject"] = rendered.subject
        message["From"] = self._settings.mail_from
        message["To"] = to
        # O remetente é no-reply: resposta vai para o suporte
        message["Reply-To"] = self._settings.support_email
        message["Date"] = formatdate(usegmt=True)
        message["Message-ID"] = make_msgid(domain=self._domain)
        # RFC 3834: email automático, sem resposta automática de volta
        message["Auto-Submitted"] = "auto-generated"
        # quoted-printable mantém a mensagem em 7 bits, aceita por qualquer servidor
        message.set_content(rendered.text, cte="quoted-printable")
        message.add_alternative(rendered.html, subtype="html", cte="quoted-printable")
        return message

    def send(self, to: str, locale: Locale, email: Email) -> bool:
        """Monta e envia. Devolve False se falhou (já logado); nunca levanta."""
        try:
            self._backend.send(self.build(to, locale, email))
        except Exception as exc:
            logger.error("email %s não enviado (%s)", email.kind, _describe(exc))
            return False
        logger.info("email %s enviado", email.kind)
        return True


def _describe(exc: Exception) -> str:
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


def schedule_email(
    background_tasks: BackgroundTasks, mailer: Mailer, to: str, locale: Locale, email: Email
) -> None:
    """Agenda o envio para depois da resposta. Chame depois do `write_transaction` fechar."""
    background_tasks.add_task(mailer.send, to, locale, email)
