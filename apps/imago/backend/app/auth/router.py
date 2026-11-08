"""Endpoints públicos do login por código (`/auth/code/*`). A sessão e a conta (`/me`) entram na
ETH-18.

As regras do login ficam em `app/auth/service.py`; aqui só a entrada (validação do corpo), a
resposta HTTP e o agendamento dos emails depois do commit.

- `POST /auth/code/request`: 202 com o mesmo corpo e os mesmos headers para email com conta, sem
  conta e de conta bloqueada ou em exclusão (que não recebem email). Limite por email e teto de
  envio: 429 `rate_limited`, igual para qualquer email. O aviso ao suporte sai mesmo com 429: a
  resposta de erro é devolvida (não levantada), e o FastAPI roda os emails agendados depois dela.
- `POST /auth/code/verify`: 200 `{"new_account": bool}` com o cookie da sessão
  (`app/auth/cookies.py`). Código errado, vencido, usado, esgotado ou de conta bloqueada ou em
  exclusão: 400 `invalid_code` (field `code`), sempre igual. Fuso desconhecido no primeiro acesso:
  422 `invalid_timezone` (field `timezone`).
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, StringConstraints

from app.auth import service
from app.auth.cookies import set_session_cookie
from app.config import SettingsDep
from app.db import SessionDep
from app.errors import ApiError, ErrorCode, error_response
from app.mail.language import Locale
from app.mail.sender import Mailer, MailerDep, schedule
from app.models import TIMEZONE_MAX_LENGTH
from app.request_info import client_ip, client_user_agent

router = APIRouter(tags=["conta"])

# Corpo do 202 dos pedidos de código, igual em todos os casos
CODE_REQUEST_ACCEPTED = {"status": "accepted"}


def _normalized_email(value: str) -> str:
    email = service.normalize_email(value)
    if email is None:
        # Vira 422 validation_error com field "email", sem o valor recebido
        raise ValueError("email inválido")
    return email


Email = Annotated[str, AfterValidator(_normalized_email)]
# [0-9] e não \d: o \d do validador aceitaria dígitos de outros alfabetos
Code = Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")]
Timezone = Annotated[str, StringConstraints(min_length=1, max_length=TIMEZONE_MAX_LENGTH)]


class CodeRequestBody(BaseModel):
    email: Email


class CodeVerifyBody(BaseModel):
    email: Email
    code: Code
    # Fuso IANA e idioma do navegador: só valem no primeiro acesso
    timezone: Timezone
    locale: Locale


class CodeVerifyResponse(BaseModel):
    new_account: bool


def code_request_response(
    result: service.CodeRequestResult, background_tasks: BackgroundTasks, mailer: Mailer
) -> JSONResponse:
    """202 ou 429 de um pedido de código, com os emails agendados para depois da resposta.

    Serve ao `POST /auth/code/request` e ao pedido do código de exclusão (ETH-61). A transação
    já fechou: o código (ou o aviso do teto ao suporte) sai depois da resposta, inclusive a 429.
    """
    for outgoing in result.emails:
        schedule(background_tasks, mailer, outgoing)
    if not result.accepted:
        return error_response(429, ErrorCode.RATE_LIMITED)
    return JSONResponse(status_code=202, content=CODE_REQUEST_ACCEPTED)


@router.post("/auth/code/request", status_code=202)
def request_code(
    body: CodeRequestBody,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    result = service.request_login_code(
        session,
        settings,
        email=body.email,
        ip=client_ip(request),
        accept_language=request.headers.get("accept-language"),
    )
    return code_request_response(result, background_tasks, mailer)


@router.post("/auth/code/verify")
def verify_code(
    body: CodeVerifyBody,
    request: Request,
    response: Response,
    session: SessionDep,
) -> CodeVerifyResponse:
    result = service.verify_login_code(
        session,
        email=body.email,
        code=body.code,
        timezone=body.timezone,
        locale=body.locale,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    # A tentativa já foi gravada (commit no serviço); o erro só monta a resposta
    if result is service.VerifyFailure.INVALID_TIMEZONE:
        raise ApiError(422, ErrorCode.INVALID_TIMEZONE, field="timezone")
    if isinstance(result, service.VerifyFailure):
        raise ApiError(400, ErrorCode.INVALID_CODE, field="code")
    set_session_cookie(response, result.token)
    return CodeVerifyResponse(new_account=result.new_account)
