"""Endpoints do admin de contas (ETH-62). Regras em `app/admin/accounts.py`.

Todos exigem `AdminUser` (sessão válida, termos atuais aceitos e `is_admin` lido do banco). Sem
sessão: 401 `unauthorized`; usuário comum: 403 `forbidden`; termos pendentes: 403
`terms_not_accepted`. A dependência está também no próprio router, então uma rota nova nunca fica
aberta por esquecimento. Conta que não existe: 404 `not_found`.

- `GET /admin/users?email&status&cursor&limit`: `{"users": [AdminUser], "next_cursor"}`, das mais
  novas para as mais antigas. `email`: trecho do email; `status`: `active`, `blocked` ou
  `deleting`; `limit` de 1 a 200 (padrão 50); `next_cursor` vai no `cursor` da próxima página
  (com os mesmos filtros), null na última.
- `PATCH /admin/users/{id}` com `{is_active}`: bloqueia (apaga as sessões da conta) ou desbloqueia.
  A própria conta: 409 `cannot_block_self`. Devolve o AdminUser.
- `PATCH /admin/users/{id}/email` com `{new_email}`: troca o email. Email que já tem conta: 409
  `email_in_use` (field `new_email`). Os avisos ao email antigo e ao novo e as tarefas `refresh`
  das aplicações saem depois da resposta. Devolve o AdminUser com o email novo.
- `DELETE /admin/users/{id}`: 204; a exclusão de `app/deletion.py` (último admin ativo: 409
  `last_admin`), com as aplicações chamadas depois da resposta.
- `GET /admin/mail`: MailStats, os envios de email das últimas 24 h por aplicação e tipo e quanto
  falta para o teto em cada janela.

`AdminUser` = `{id, email, status ("active"|"deleting"), is_active, is_admin, timezone, locale,
created_at, last_login_at|null}`, com as datas em ISO 8601 UTC.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from app.admin import accounts
from app.admin.accounts import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, AccountStatus
from app.auth.deps import AdminUser, require_admin
from app.auth.router import Email
from app.config import SettingsDep
from app.db import SessionDep
from app.deletion import continue_deletion
from app.internal import tasks
from app.internal.tasks import TaskContextDep
from app.mail.language import Locale
from app.mail.sender import MailerDep, schedule
from app.models import EMAIL_MAX_LENGTH, MAX_ACCOUNT_ID, TaskAction, User, UserStatus
from app.request_info import client_ip

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

UserId = Annotated[int, Path(ge=1, le=MAX_ACCOUNT_ID)]


class AdminAccount(BaseModel):
    """Uma conta no painel (o `AdminUser` do contrato)."""

    id: int
    email: str
    # active ou deleting (exclusão em andamento)
    status: UserStatus
    # false: bloqueada pelo admin
    is_active: bool
    is_admin: bool
    timezone: str
    locale: Locale
    created_at: datetime
    # null: nunca entrou pelo código (ex.: importada do ethos e ainda sem login)
    last_login_at: datetime | None


class AccountList(BaseModel):
    users: list[AdminAccount]
    next_cursor: str | None


class ActiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: StrictBool


class EmailChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Normalizado (strip + lower) e validado como no login
    new_email: Email


class AppMailOut(BaseModel):
    app: str
    code: int
    account: int
    notification: int


class MailWindowOut(BaseModel):
    sent: int
    limit: int
    notification_limit: int


class MailStatsOut(BaseModel):
    window_hours: int
    by_app: list[AppMailOut]
    day: MailWindowOut
    hour: MailWindowOut


def account_out(user: User) -> AdminAccount:
    return AdminAccount(
        id=user.id,
        email=user.email,
        status=UserStatus(user.status),
        is_active=user.is_active,
        is_admin=user.is_admin,
        timezone=user.timezone,
        locale=Locale(user.locale),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.get("/users")
def list_users(
    session: SessionDep,
    email: Annotated[str | None, Query(max_length=EMAIL_MAX_LENGTH)] = None,
    status: Annotated[AccountStatus | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> AccountList:
    page = accounts.list_accounts(session, email=email, status=status, cursor=cursor, limit=limit)
    users = [account_out(user) for user in page.users]
    return AccountList(users=users, next_cursor=page.next_cursor)


@router.patch("/users/{user_id}")
def set_user_active(
    user_id: UserId, body: ActiveBody, admin: AdminUser, request: Request, session: SessionDep
) -> AdminAccount:
    admin_id = admin.id
    user = accounts.set_active(
        session,
        admin_id=admin_id,
        account_id=user_id,
        is_active=body.is_active,
        ip=client_ip(request),
    )
    return account_out(user)


@router.patch("/users/{user_id}/email")
def change_user_email(
    user_id: UserId,
    body: EmailChangeBody,
    admin: AdminUser,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    task_context: TaskContextDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> AdminAccount:
    admin_id = admin.id
    change = accounts.change_email(
        session,
        settings,
        admin_id=admin_id,
        account_id=user_id,
        new_email=body.new_email,
        ip=client_ip(request),
    )
    # A transação já fechou: os avisos e o refresh das aplicações saem depois da resposta
    for outgoing in change.emails:
        schedule(background_tasks, mailer, outgoing)
    tasks.schedule(background_tasks, task_context, user_id=user_id, action=TaskAction.REFRESH)
    return account_out(change.user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: UserId,
    admin: AdminUser,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    task_context: TaskContextDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> None:
    admin_id = admin.id
    accounts.delete_account(
        session, settings, admin_id=admin_id, account_id=user_id, ip=client_ip(request)
    )
    # Também quando a exclusão já estava em andamento: tenta de novo as aplicações que faltam
    background_tasks.add_task(continue_deletion, task_context, mailer, user_id)


@router.get("/mail")
def get_mail_stats(session: SessionDep, settings: SettingsDep) -> MailStatsOut:
    stats = accounts.mail_stats(session, settings)
    return MailStatsOut.model_validate(stats, from_attributes=True)
