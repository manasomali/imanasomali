"""Montagem e entrega dos emails pelo imago, e o agendamento em BackgroundTasks depois do commit.

Uso num endpoint (sempre `def`), depois que a transação fechou:

    with write_transaction(session):
        ...
    schedule_email(background_tasks, mailer, member_id, locale, HabitDeleted(habit_name=name))

O destinatário é o id do usuário no imago, nunca um endereço: o imago põe o email atual da pessoa
(e não manda nada a quem está inativo ou em exclusão). O FastAPI roda a tarefa depois de mandar a
resposta; se o endpoint levantar exceção, a tarefa não roda. Quem não está num request (o CLI dos
alertas) chama `mailer.send(...)` direto e decide pelo `MailOutcome`.

Falha de envio nunca propaga: vira uma linha no log com o tipo do email e do erro (ver
`app/imago_client.py`), nunca o destinatário, o corpo nem a mensagem da exceção.
"""

import logging
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Request

from app.config import Settings
from app.imago_client import ImagoClient, MailOutcome
from app.mail.catalog import Email
from app.mail.language import Locale
from app.mail.templates import render

logger = logging.getLogger(__name__)


class Mailer:
    """Monta os emails do catálogo com a config do app e os entrega pelo imago.

    Não guarda estado entre envios, então pode ser usado por várias threads ao mesmo tempo.
    """

    def __init__(self, settings: Settings, imago: ImagoClient) -> None:
        self._settings = settings
        self._imago = imago

    def send(self, user_id: int, locale: Locale, email: Email) -> MailOutcome:
        """Monta e entrega ao imago. Nunca levanta: falha vira `MailOutcome.FAILED` (já logada)."""
        try:
            rendered = render(
                email,
                locale,
                app_url=self._settings.app_url,
                account_url=self._settings.account_url,
            )
            return self._imago.send_mail(
                user_id,
                email.kind,
                subject=rendered.subject,
                text=rendered.text,
                html=rendered.html,
            )
        except Exception as exc:
            # Só o tipo: a mensagem pode trazer dados do email
            logger.error("email %s não enviado (%s)", email.kind, type(exc).__name__)
            return MailOutcome.FAILED


def get_mailer(request: Request) -> Mailer:
    """Dependência do FastAPI: o Mailer criado na subida do app."""
    return request.app.state.mailer


MailerDep = Annotated[Mailer, Depends(get_mailer)]


def schedule_email(
    background_tasks: BackgroundTasks, mailer: Mailer, user_id: int, locale: Locale, email: Email
) -> None:
    """Agenda o envio para depois da resposta. Chame depois do `write_transaction` fechar."""
    background_tasks.add_task(mailer.send, user_id, locale, email)
