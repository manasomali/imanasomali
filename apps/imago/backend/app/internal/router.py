"""API interna do imago: só entre os serviços, direto em 127.0.0.1:3003, nunca pelo nginx.

O nginx responde 404 para `/api/imago/internal/` de fora. Estas rotas não passam pela checagem
de `Origin` (`app/auth/origin.py`): não vêm do navegador.

- `session_router`, sem token: `GET /internal/session`, chamado pelo `auth_request` do nginx em
  cada request de `/api/<app>/`. Sempre 200, corpo vazio. Com cookie de sessão válido, conta ativa
  (`is_active` e `status=active`) e a versão atual dos termos aceita, devolve o usuário nos headers
  `X-User-Id` (decimal), `X-User-Email` (ASCII, minúsculo), `X-User-Locale` (`pt`|`en`),
  `X-User-Timezone` (IANA) e `X-User-Admin: 1` (só para admin). Em qualquer outro caso, nenhum
  deles: as aplicações decidem quais rotas exigem login. Renova a sessão com a regra de uma
  escrita por dia (`app/auth/deps.py`), então usar qualquer aplicação mantém a sessão viva. Só lê
  o cookie que veio no request e devolve o que o próprio dono do cookie já vê em `GET /me`;
- `router`, com o token de cada aplicação (`app/internal/deps.py`) em todas as rotas:
  `POST /internal/mail` (notificação de uma aplicação para um usuário),
  `POST /internal/users/lookup` e `GET /internal/users/{id}` (ETH-59).

`POST /internal/mail` `{kind: "notification", user_id, subject, text, html}` (corpo até 100 KB,
`app/body_limit.py`): o destinatário é sempre um usuário do imago, por id, nunca um endereço
qualquer, e o imago põe o endereço atual dele. Respostas: 202 `{"status": "accepted"}` com a linha
do `mail_log` gravada (o SMTP roda depois, em BackgroundTasks; falha de SMTP vira uma linha de log
e a aplicação não fica sabendo); 204 para conta bloqueada ou em exclusão (sem envio e sem contar
no teto); 404 `not_found` para id inexistente; 429 `mail_quota` com o teto de notificações
atingido (`app/mail/quota.py`); 401 sem token ou com token errado; 422 na validação. O remetente
é "<aplicação do token> <MAIL_FROM_ADDRESS>".

`POST /internal/users/lookup` `{email}` (convites: o email vai no corpo, nunca na URL, para não
parar em log): 200 `{id, locale}` da conta ativa com esse email (normalizado como no login); 404
`not_found` se não existe, está bloqueada ou em exclusão (a mesma resposta nos três casos); 422 com
email inválido ou campo desconhecido.

`GET /internal/users/{id}`: 200 `{id, email, locale, timezone, active}`, com `active` = conta não
bloqueada e fora de exclusão; 404 `not_found` se não existe; 422 com id fora de 1 a 2^53 - 1.
"""

import unicodedata
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import authenticate, session_token, terms_pending
from app.auth.router import Email
from app.auth.security import hash_secret
from app.auth.service import can_sign_in
from app.config import SettingsDep
from app.db import SessionDep, write_transaction
from app.errors import ApiError, ErrorCode
from app.internal.deps import CallerApp, caller_app
from app.mail import quota
from app.mail.kinds import MailKind
from app.mail.language import Locale
from app.mail.sender import MailerDep, Notification, schedule
from app.models import MAX_ACCOUNT_ID, User, utcnow

# Rotas que exigem o token da aplicação: todas as de /internal/ menos /internal/session
router = APIRouter(prefix="/internal", tags=["interna"], dependencies=[Depends(caller_app)])
session_router = APIRouter(prefix="/internal", tags=["interna"])

# Headers que o /internal/session devolve e que o nginx repassa às aplicações
USER_ID_HEADER = "X-User-Id"
USER_EMAIL_HEADER = "X-User-Email"
USER_LOCALE_HEADER = "X-User-Locale"
USER_TIMEZONE_HEADER = "X-User-Timezone"
USER_ADMIN_HEADER = "X-User-Admin"
USER_HEADERS = (
    USER_ID_HEADER,
    USER_EMAIL_HEADER,
    USER_LOCALE_HEADER,
    USER_TIMEZONE_HEADER,
    USER_ADMIN_HEADER,
)

# Assunto de uma notificação: até 200 caracteres, numa linha só. Categorias Unicode recusadas:
# controle (Cc), separador de linha (Zl) e de parágrafo (Zp)
SUBJECT_MAX_LENGTH = 200
_NOT_IN_SUBJECT = frozenset({"Cc", "Zl", "Zp"})
MAIL_ACCEPTED = {"status": "accepted"}


# O nginx manda o subrequest do auth_request como GET; os outros métodos só garantem que um
# nginx que repasse o método do request original (POST, PATCH...) não derrube as aplicações. Fora
# do OpenAPI: uma rota com vários métodos repetiria o operationId
@session_router.api_route(
    "/session",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
def internal_session(request: Request, session: SessionDep) -> Response:
    return Response(status_code=200, headers=session_headers(request, session))


def session_headers(request: Request, session: Session) -> dict[str, str]:
    """Os headers `X-User-*` do dono do cookie, ou nenhum (ver o docstring do módulo)."""
    token = session_token(request)
    if token is None:
        return {}
    try:
        authenticated, _ = authenticate(session, hash_secret(token), renew=True)
    except ApiError:
        return {}
    user = authenticated.user
    if terms_pending(user):
        return {}
    headers = {
        USER_ID_HEADER: str(user.id),
        USER_EMAIL_HEADER: user.email,
        USER_LOCALE_HEADER: user.locale,
        USER_TIMEZONE_HEADER: user.timezone,
    }
    if user.is_admin:
        headers[USER_ADMIN_HEADER] = "1"
    return headers


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
        if not can_sign_in(user):
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


# --- contas, para as aplicações (ETH-59) ---


class LookupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Normalizado (strip + lower) e validado como no login
    email: Email


class LookupResponse(BaseModel):
    id: int
    locale: Locale


@router.post("/users/lookup")
def lookup_user(body: LookupBody, session: SessionDep) -> LookupResponse:
    user = session.scalar(select(User).where(User.email == body.email))
    if user is None or not can_sign_in(user):
        raise ApiError(404, ErrorCode.NOT_FOUND)
    return LookupResponse(id=user.id, locale=Locale(user.locale))


class InternalUser(BaseModel):
    id: int
    email: str
    locale: Locale
    timezone: str
    # Conta não bloqueada e fora de exclusão
    active: bool


@router.get("/users/{user_id}")
def get_user(
    user_id: Annotated[int, Path(ge=1, le=MAX_ACCOUNT_ID)], session: SessionDep
) -> InternalUser:
    user = session.get(User, user_id)
    if user is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    return InternalUser(
        id=user.id,
        email=user.email,
        locale=Locale(user.locale),
        timezone=user.timezone,
        active=can_sign_in(user),
    )
