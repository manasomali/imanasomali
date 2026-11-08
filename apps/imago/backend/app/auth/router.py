"""Endpoints públicos da conta: login por código (`/auth/*`) e a própria conta (`/me`).

As regras do login ficam em `app/auth/service.py` e as da sessão em `app/auth/deps.py`; aqui só
a entrada (validação do corpo), a resposta HTTP e o agendamento dos emails depois do commit. Toda
request de escrita passa antes pela checagem de `Origin` (`app/auth/origin.py`).

- `POST /auth/code/request`: 202 com o mesmo corpo e os mesmos headers para email com conta, sem
  conta e de conta bloqueada ou em exclusão (que não recebem email). Limite por email e teto de
  envio: 429 `rate_limited`, igual para qualquer email. O aviso ao suporte sai mesmo com 429: a
  resposta de erro é devolvida (não levantada), e o FastAPI roda os emails agendados depois dela.
- `POST /auth/code/verify`: 200 `{"new_account": bool}` com o cookie da sessão
  (`app/auth/cookies.py`). Código errado, vencido, usado, esgotado ou de conta bloqueada ou em
  exclusão: 400 `invalid_code` (field `code`), sempre igual. Fuso desconhecido no primeiro acesso:
  422 `invalid_timezone` (field `timezone`).
- `POST /auth/logout`: apaga a sessão do cookie e o cookie; `POST /auth/logout-all`: apaga todas as
  sessões do usuário (expulsa um aparelho perdido) e o cookie. 204; sem sessão válida, 401.
- `GET /me`: os dados da conta, `terms_pending`, as aplicações do `IMAGO_APPS` e o
  `SUPPORT_EMAIL` (para pedir a troca de email).
- `PATCH /me`: muda `timezone` (fuso IANA; desconhecido: 422 `invalid_timezone`) e `locale`. É o
  único jeito de mudar o fuso: o login de conta existente o ignora. Exige os termos atuais. Quando
  algo muda, cria na mesma transação uma tarefa `refresh` por aplicação do `IMAGO_APPS`
  (`app/internal/tasks.py`), tentada depois da resposta.
- `POST /me/terms`: aceita a versão atual dos termos. O corpo traz a versão que a pessoa leu; se
  ela não for a atual (os termos mudaram com a tela aberta), 409 `conflict` (field
  `terms_version`), e o front mostra os termos novos.

- `POST /me/delete/request`: manda o código de exclusão da conta para o email atual (202 com o mesmo
  corpo do pedido de código de login; 429 `rate_limited` com os mesmos limites). O último admin
  ativo recebe 409 `last_admin`.
- `DELETE /me` com `{code}`: confere o código e começa a exclusão da conta em todas as aplicações
  (`app/deletion.py`). 204 e o cookie apagado; as aplicações são chamadas depois da resposta.
  Código recusado: 400 `invalid_code` (field `code`), como no login; último admin: 409.

`GET /me`, `POST /me/terms`, a exclusão da conta e o logout funcionam sem os termos atuais aceitos:
quem não aceita a versão nova dos termos pode sair ou apagar a conta.
"""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import audit, deletion
from app.audit import AuditEvent
from app.auth import service
from app.auth.cookies import clear_session_cookie, set_session_cookie
from app.auth.deps import CurrentSession, CurrentUser, CurrentUserAnyTerms, terms_pending
from app.config import Settings, SettingsDep
from app.db import SessionDep, write_transaction
from app.errors import ApiError, ErrorCode, error_response
from app.internal import tasks
from app.internal.tasks import TaskContextDep
from app.mail.language import Locale
from app.mail.sender import Mailer, MailerDep, schedule
from app.models import (
    TERMS_VERSION_MAX_LENGTH,
    TIMEZONE_MAX_LENGTH,
    TaskAction,
    User,
    UserSession,
    utcnow,
)
from app.request_info import client_ip, client_user_agent
from app.terms import TERMS_VERSION

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


# --- sessão ---


def _delete_sessions(session: Session, *where: Any) -> int:
    """Apaga as sessões que batem com `where` e devolve quantas eram."""
    result = session.execute(
        delete(UserSession).where(*where), execution_options={"synchronize_session": False}
    )
    return result.rowcount


@router.post("/auth/logout", status_code=204)
def logout(
    current: CurrentSession, request: Request, response: Response, session: SessionDep
) -> None:
    user_id = current.user.id
    with write_transaction(session):
        # 0 só se outro request apagou a sessão no meio (outro logout, logout-all, exclusão)
        if _delete_sessions(session, UserSession.token_hash == current.token_hash):
            audit.record(session, AuditEvent.LOGOUT, user_id=user_id, ip=client_ip(request))
    clear_session_cookie(response)


@router.post("/auth/logout-all", status_code=204)
def logout_all(
    current: CurrentSession, request: Request, response: Response, session: SessionDep
) -> None:
    user_id = current.user.id
    with write_transaction(session):
        deleted = _delete_sessions(session, UserSession.user_id == user_id)
        if deleted:
            audit.record(
                session,
                AuditEvent.LOGOUT_ALL,
                user_id=user_id,
                ip=client_ip(request),
                details={"sessions": deleted},
            )
    clear_session_cookie(response)


# --- conta ---


class MeResponse(BaseModel):
    id: int
    email: str
    timezone: str
    locale: Locale
    is_admin: bool
    # Versão dos termos aceita pela pessoa (None: nenhuma ainda) e a atual; terms_pending:
    # precisa aceitar a atual
    terms_version: str | None
    current_terms_version: str
    terms_pending: bool
    # Nomes do IMAGO_APPS, na ordem dele; o link de cada uma é /<nome>/
    apps: list[str]
    # Para pedir a troca de email (só pelo suporte)
    support_email: str


def me_response(user: User, settings: Settings) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        timezone=user.timezone,
        locale=Locale(user.locale),
        is_admin=user.is_admin,
        terms_version=user.terms_version,
        current_terms_version=TERMS_VERSION,
        terms_pending=terms_pending(user),
        apps=list(settings.app_names),
        support_email=settings.support_email,
    )


def reload_user(session: Session, user_id: int) -> User:
    """Relê o usuário dentro da transação de escrita; 401 se foi apagado, bloqueado ou entrou em
    exclusão no meio."""
    user = session.scalar(
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )
    if user is None or not service.can_sign_in(user):
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    return user


@router.get("/me")
def get_me(user: CurrentUserAnyTerms, settings: SettingsDep) -> MeResponse:
    return me_response(user, settings)


class ProfileUpdateBody(BaseModel):
    """Campos ausentes não mudam; `null` e campos desconhecidos são recusados (422)."""

    model_config = ConfigDict(extra="forbid")

    timezone: Timezone | None = None
    locale: Locale | None = None

    @field_validator("timezone", "locale")
    @classmethod
    def _not_null(cls, value: str | None) -> str:
        # Só roda quando o campo veio no corpo: o padrão (ausente) não é validado
        if value is None:
            raise ValueError("não pode ser null")
        return value


@router.patch("/me")
def update_me(
    body: ProfileUpdateBody,
    user: CurrentUser,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    task_context: TaskContextDep,
    background_tasks: BackgroundTasks,
) -> MeResponse:
    if body.timezone is not None and not service.is_valid_timezone(body.timezone):
        raise ApiError(422, ErrorCode.INVALID_TIMEZONE, field="timezone")
    requested = {"timezone": body.timezone, "locale": body.locale}
    if all(value is None for value in requested.values()):
        return me_response(user, settings)
    user_id = user.id
    with write_transaction(session):
        user = reload_user(session, user_id)
        changes = []
        for name, new in requested.items():
            old = getattr(user, name)
            if new is not None and new != old:
                changes.append({"field": name, "old": old, "new": str(new)})
                setattr(user, name, str(new))
        if changes:
            audit.record(
                session,
                AuditEvent.PROFILE_UPDATED,
                user_id=user_id,
                ip=client_ip(request),
                details={"changes": changes},
            )
            # As aplicações guardam o idioma e o fuso em app_users: uma tarefa refresh para cada
            # uma (no máximo uma pendente por conta e aplicação)
            tasks.request_tasks(session, settings, user_id=user_id, action=TaskAction.REFRESH)
    if changes:
        # Depois do commit; o refresh manda os valores da conta na hora da chamada
        tasks.schedule(background_tasks, task_context, user_id=user_id, action=TaskAction.REFRESH)
    return me_response(user, settings)


class TermsAcceptBody(BaseModel):
    # A versão que a pessoa leu e aceitou (a que o front mostrou)
    terms_version: Annotated[
        str, StringConstraints(min_length=1, max_length=TERMS_VERSION_MAX_LENGTH)
    ]


@router.post("/me/terms")
def accept_terms(
    body: TermsAcceptBody,
    user: CurrentUserAnyTerms,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> MeResponse:
    if body.terms_version != TERMS_VERSION:
        raise ApiError(409, ErrorCode.CONFLICT, field="terms_version")
    user_id = user.id
    with write_transaction(session):
        user = reload_user(session, user_id)
        # Aceitar de novo a versão já aceita não muda nada
        if terms_pending(user):
            user.terms_version = TERMS_VERSION
            user.terms_accepted_at = utcnow()
            audit.record(
                session,
                AuditEvent.TERMS_ACCEPTED,
                user_id=user_id,
                ip=client_ip(request),
                details={"terms_version": TERMS_VERSION},
            )
    return me_response(user, settings)


# --- exclusão da conta (ETH-61) ---


@router.post("/me/delete/request", status_code=202)
def request_account_deletion(
    user: CurrentUserAnyTerms,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    result = deletion.request_account_deletion(
        session, settings, user_id=user.id, ip=client_ip(request)
    )
    return code_request_response(result, background_tasks, mailer)


class AccountDeleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Code


@router.delete("/me", status_code=204)
def delete_me(
    body: AccountDeleteBody,
    current: CurrentSession,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    task_context: TaskContextDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> None:
    user_id = current.user.id
    failure = deletion.delete_own_account(session, settings, user_id=user_id, code=body.code)
    # A tentativa já foi gravada (commit no serviço); o erro só monta a resposta
    if failure is not None:
        raise ApiError(400, ErrorCode.INVALID_CODE, field="code")
    clear_session_cookie(response)
    # Depois do commit: as aplicações apagam os dados, e o passo 3 manda o "conta excluída"
    background_tasks.add_task(deletion.continue_deletion, task_context, mailer, user_id)
