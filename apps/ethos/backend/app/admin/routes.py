"""Endpoints do admin (ETH-28) e o banner público.

`/admin/...`: todos exigem `AdminUser` (sessão válida, termos atuais aceitos e `is_admin` lido do
banco). Sem sessão: 401 `unauthorized`; usuário comum: 403 `forbidden`. A dependência está também
no próprio router, então uma rota nova nunca fica aberta por esquecimento. Regras em
`accounts.py` e `banners.py`.

Contas:

- `GET /admin/users?email&status&created_from&created_to&last_login_from&last_login_to&cursor
  &limit`: `{"users": [{id, email, is_active, is_admin, timezone, locale, created_at,
  last_login_at, habit_count, mark_count}], "next_cursor"}`, das mais novas para as mais antigas.
  `email`: trecho do email; `status`: `active` ou `blocked`; datas locais `YYYY-MM-DD`,
  inclusivas, no fuso do admin (fim antes do início: 422 no campo do fim); `limit` de 1 a 200
  (padrão 50).
- `GET /admin/users/{id}/habits?habit_id&cursor&limit`: `{"user", "habits", "marks",
  "next_cursor"}`: a conta, os hábitos de que ela é dona (como no `GET /habits/{id}`, com
  `role` owner e sem `score`) e uma página das marcações deles (com observações), das mais
  recentes para as mais antigas. Cada chamada grava `admin_viewed_habits`.
- `POST /admin/users/{id}/block` e `/unblock`: a conta (como na listagem). Bloquear apaga as
  sessões; a própria conta: 409 `cannot_block_self`.
- `PATCH /admin/users/{id}/email` com `{new_email}`: a conta com o email novo. Email que já tem
  conta: 409 `email_in_use` (field `new_email`). Apaga as sessões; os avisos ao email antigo e ao
  novo saem depois da resposta.
- `DELETE /admin/users/{id}`: 204; a exclusão de `app/auth/deletion.py` (último admin ativo: 409
  `last_admin`), com os avisos depois da resposta.

Conta ou banner que não existe: 404 `not_found`.

Banners:

- `GET /admin/banners?cursor&limit`: `{"banners": [{id, text_pt, text_en, starts_at, ends_at,
  created_by, created_at, updated_at}], "next_cursor"}`, todos, dos criados por último aos
  primeiros.
- `POST /admin/banners` com `{text_pt, text_en, starts_at, ends_at}`: 201 com o banner.
- `PATCH /admin/banners/{id}` com qualquer parte dos mesmos campos: o banner.
- `POST /admin/banners/{id}/end`: o banner, com a janela fechada agora.
- `GET /banners/active`, sem login (nem sessão, nem termos, nem Origin, por ser GET):
  `{"banner": {id, text_pt, text_en, starts_at, ends_at} | null}`, o banner no ar agora.
"""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request

from app.admin import accounts, banners
from app.admin.accounts import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AccountFilters,
    AccountStatus,
    AccountSummary,
)
from app.admin.schemas import (
    AccountHabits,
    AccountList,
    AccountOut,
    ActiveBanner,
    BannerCreate,
    BannerList,
    BannerOut,
    BannerUpdate,
    EmailChangeIn,
    PublicBanner,
)
from app.auth import deletion
from app.auth.deps import AdminUser, require_admin
from app.db import SessionDep
from app.habits.access import MAX_ID, HabitAccess, HabitRole
from app.habits.routes import habit_out
from app.mail.language import Locale
from app.mail.sender import MailerDep, schedule_email
from app.marks.routes import mark_out
from app.models import EMAIL_MAX_LENGTH, Banner
from app.progress.schemas import Day
from app.request_info import client_ip

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
public_router = APIRouter(prefix="/banners", tags=["banners"])

UserId = Annotated[int, Path(ge=1, le=MAX_ID)]
BannerId = Annotated[int, Path(ge=1, le=MAX_ID)]
Cursor = Annotated[str | None, Query(max_length=64)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
QueryDay = Annotated[Day | None, Query()]


def account_out(summary: AccountSummary) -> AccountOut:
    user = summary.user
    return AccountOut(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_admin=user.is_admin,
        timezone=user.timezone,
        locale=Locale(user.locale),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        habit_count=summary.habit_count,
        mark_count=summary.mark_count,
    )


def banner_out(banner: Banner) -> BannerOut:
    return BannerOut.model_validate(banner, from_attributes=True)


# --- contas ---


@router.get("/users")
def list_users(
    admin: AdminUser,
    session: SessionDep,
    email: Annotated[str | None, Query(max_length=EMAIL_MAX_LENGTH)] = None,
    status: Annotated[AccountStatus | None, Query()] = None,
    created_from: QueryDay = None,
    created_to: QueryDay = None,
    last_login_from: QueryDay = None,
    last_login_to: QueryDay = None,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
) -> AccountList:
    page = accounts.list_accounts(
        session,
        tz=ZoneInfo(admin.timezone),
        filters=AccountFilters(
            email=email,
            status=status,
            created_from=created_from,
            created_to=created_to,
            last_login_from=last_login_from,
            last_login_to=last_login_to,
        ),
        cursor=cursor,
        limit=limit,
    )
    return AccountList(
        users=[account_out(entry) for entry in page.entries], next_cursor=page.next_cursor
    )


@router.get("/users/{user_id}/habits")
def view_user_habits(
    user_id: UserId,
    admin: AdminUser,
    request: Request,
    session: SessionDep,
    habit_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
) -> AccountHabits:
    content = accounts.view_account_habits(
        session,
        admin_id=admin.id,
        account_id=user_id,
        habit_id=habit_id,
        cursor=cursor,
        limit=limit,
        ip=client_ip(request),
    )
    return AccountHabits(
        user=account_out(content.account),
        habits=[habit_out(HabitAccess(habit, HabitRole.OWNER), None) for habit in content.habits],
        marks=[mark_out(entry) for entry in content.marks],
        next_cursor=content.next_cursor,
    )


@router.post("/users/{user_id}/block")
def block_user(
    user_id: UserId, admin: AdminUser, request: Request, session: SessionDep
) -> AccountOut:
    summary = accounts.block_account(
        session, admin_id=admin.id, account_id=user_id, ip=client_ip(request)
    )
    return account_out(summary)


@router.post("/users/{user_id}/unblock")
def unblock_user(
    user_id: UserId, admin: AdminUser, request: Request, session: SessionDep
) -> AccountOut:
    summary = accounts.unblock_account(
        session, admin_id=admin.id, account_id=user_id, ip=client_ip(request)
    )
    return account_out(summary)


@router.patch("/users/{user_id}/email")
def change_user_email(
    user_id: UserId,
    body: EmailChangeIn,
    admin: AdminUser,
    request: Request,
    session: SessionDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> AccountOut:
    change = accounts.change_email(
        session,
        admin_id=admin.id,
        account_id=user_id,
        new_email=body.new_email,
        ip=client_ip(request),
    )
    # A transação já fechou: os avisos saem depois da resposta
    for outgoing in change.emails:
        schedule_email(background_tasks, mailer, outgoing.to, outgoing.locale, outgoing.email)
    return account_out(change.account)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: UserId,
    admin: AdminUser,
    request: Request,
    session: SessionDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> None:
    result = deletion.delete_account(
        session, account_id=user_id, actor_id=admin.id, ip=client_ip(request)
    )
    # Depois do commit: uma exclusão que falhou não avisa ninguém
    for outgoing in result.emails:
        schedule_email(background_tasks, mailer, outgoing.to, outgoing.locale, outgoing.email)


# --- banners ---


@router.get("/banners")
def list_banners(
    session: SessionDep, cursor: Cursor = None, limit: Limit = DEFAULT_PAGE_SIZE
) -> BannerList:
    page = banners.list_banners(session, cursor=cursor, limit=limit)
    return BannerList(
        banners=[banner_out(banner) for banner in page.entries], next_cursor=page.next_cursor
    )


@router.post("/banners", status_code=201)
def create_banner(
    body: BannerCreate, admin: AdminUser, request: Request, session: SessionDep
) -> BannerOut:
    banner = banners.create_banner(
        session,
        admin_id=admin.id,
        ip=client_ip(request),
        text_pt=body.text_pt,
        text_en=body.text_en,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    return banner_out(banner)


@router.patch("/banners/{banner_id}")
def update_banner(
    banner_id: BannerId,
    body: BannerUpdate,
    admin: AdminUser,
    request: Request,
    session: SessionDep,
) -> BannerOut:
    banner = banners.update_banner(
        session,
        admin_id=admin.id,
        banner_id=banner_id,
        values=body.model_dump(exclude_unset=True),
        ip=client_ip(request),
    )
    return banner_out(banner)


@router.post("/banners/{banner_id}/end")
def end_banner(
    banner_id: BannerId, admin: AdminUser, request: Request, session: SessionDep
) -> BannerOut:
    banner = banners.end_banner(
        session, admin_id=admin.id, banner_id=banner_id, ip=client_ip(request)
    )
    return banner_out(banner)


@public_router.get("/active")
def get_active_banner(session: SessionDep) -> ActiveBanner:
    banner = banners.active_banner(session)
    if banner is None:
        return ActiveBanner(banner=None)
    return ActiveBanner(banner=PublicBanner.model_validate(banner, from_attributes=True))
