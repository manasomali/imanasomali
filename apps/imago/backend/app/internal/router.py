"""API interna do imago: só entre os serviços, direto em 127.0.0.1:3003, nunca pelo nginx.

O nginx responde 404 para `/api/imago/internal/` de fora.

- `router`, com o token de cada aplicação (`app/internal/deps.py`) em todas as rotas:
  `POST /internal/mail` (notificação de uma aplicação para um usuário). A ETH-59 acrescenta aqui
  `POST /internal/users/lookup` e `GET /internal/users/{id}`.

`POST /internal/mail` `{kind: "notification", user_id, subject, text, html}` (corpo até 100 KB,
`app/body_limit.py`): o destinatário é sempre um usuário do imago, por id, nunca um endereço
qualquer, e o imago põe o endereço atual dele. Respostas: 202 `{"status": "accepted"}` com a linha
do `mail_log` gravada (o SMTP roda depois, em BackgroundTasks; falha de SMTP vira uma linha de log
e a aplicação não fica sabendo); 204 para conta bloqueada ou em exclusão (sem envio e sem contar
no teto); 404 `not_found` para id inexistente; 429 `mail_quota` com o teto de notificações
atingido (`app/mail/quota.py`); 401 sem token ou com token errado; 422 na validação. O remetente
é "<aplicação do token> <MAIL_FROM_ADDRESS>".
"""

import unicodedata
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import select

from app.config import SettingsDep
from app.db import SessionDep, write_transaction
from app.errors import ApiError, ErrorCode
from app.internal.deps import CallerApp, caller_app
from app.mail import quota
from app.mail.kinds import MailKind
from app.mail.sender import MailerDep, Notification, schedule
from app.models import MAX_ACCOUNT_ID, User, UserStatus, utcnow

# Rotas que exigem o token da aplicação: todas as de /internal/
router = APIRouter(prefix="/internal", tags=["interna"], dependencies=[Depends(caller_app)])

# Assunto de uma notificação: até 200 caracteres, numa linha só. Categorias Unicode recusadas:
# controle (Cc), separador de linha (Zl) e de parágrafo (Zp)
SUBJECT_MAX_LENGTH = 200
_NOT_IN_SUBJECT = frozenset({"Cc", "Zl", "Zp"})
MAIL_ACCEPTED = {"status": "accepted"}


Subject = Annotated[str, StringConstraints(min_length=1, max_length=SUBJECT_MAX_LENGTH)]
Body = Annotated[str, StringConstraints(min_length=1)]


class MailBody(BaseModel):
    """Notificação pronta, no idioma do destinatário, com todo dado do usuário já escapado no
    HTML. Campos desconhecidos são recusados (a aplicação vem do token, nunca do corpo)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["notification"]
    # strict: só inteiro JSON (nem "12", nem 12.0, nem true)
    user_id: Annotated[int, Field(strict=True, ge=1, le=MAX_ACCOUNT_ID)]
    subject: Subject
    text: Body
    html: Body

    @field_validator("subject")
    @classmethod
    def _single_line(cls, value: str) -> str:
        # Quebra de linha num header de email viraria outro header. Ficam de fora também os
        # outros caracteres de controle (tab, NUL...) e os separadores de linha e de parágrafo
        # do Unicode. Espaços (inclusive o não separável) e emojis passam
        if any(unicodedata.category(char) in _NOT_IN_SUBJECT for char in value):
            raise ValueError("o assunto não pode ter quebra de linha nem caractere de controle")
        return value


@router.post("/mail", status_code=202)
def send_mail(
    body: MailBody,
    app: CallerApp,
    session: SessionDep,
    settings: SettingsDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> Response:
    with write_transaction(session):
        now = utcnow()
        user = session.scalar(
            select(User).where(User.id == body.user_id).execution_options(populate_existing=True)
        )
        if user is None:
            raise ApiError(404, ErrorCode.NOT_FOUND)
        if not user.is_active or user.status != UserStatus.ACTIVE.value:
            return Response(status_code=204)
        refusal = quota.reserve(session, settings, app=app, kind=MailKind.NOTIFICATION, now=now)
        if refusal is not None:
            raise ApiError(429, ErrorCode.MAIL_QUOTA)
        to = user.email
    # Depois do commit: a linha do mail_log já está gravada
    schedule(
        background_tasks,
        mailer,
        Notification(to=to, app=app, subject=body.subject, text=body.text, html=body.html),
    )
    return JSONResponse(status_code=202, content=MAIL_ACCEPTED)
