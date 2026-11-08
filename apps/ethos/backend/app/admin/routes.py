"""Endpoints do admin (ETH-28) e o banner público.

`/admin/...`: todos exigem `AdminUser` (o usuário do imago com `X-User-Admin: 1`). Sem login: 401
`not_authenticated`; usuário comum: 403 `forbidden`. A dependência está também no próprio router,
então uma rota nova nunca fica aberta por esquecimento. Regras em `accounts.py` e `banners.py`.
As contas (bloquear, trocar email, excluir) ficam no painel do imago (`/imago/admin`).

Quem usa o ethos (`app_users`):

- `GET /admin/users?email&first_seen_from&first_seen_to&cursor&limit`: `{"users": [{id, email,
  locale, timezone, first_seen_at, habit_count, mark_count}], "next_cursor"}`, do primeiro acesso
  mais novo ao mais antigo. `email`: trecho do email; datas locais `YYYY-MM-DD`, inclusivas, no
  fuso do admin (fim antes do início: 422 em `first_seen_to`); `limit` de 1 a 200 (padrão 50).
- `GET /admin/users/{id}/habits?habit_id&cursor&limit`: `{"user", "habits", "marks",
  "next_cursor"}`: a pessoa, os hábitos de que ela é dona (como no `GET /habits/{id}`, com
  `role` owner e sem `score`) e uma página das marcações deles (com observações), das mais
  recentes para as mais antigas. Cada chamada grava `admin_viewed_habits`. Pessoa que não usa o
  ethos: 404 `not_found`.

Banners:

- `GET /admin/banners?cursor&limit`: `{"banners": [{id, text_pt, text_en, starts_at, ends_at,
  created_by, created_at, updated_at}], "next_cursor"}`, todos, dos criados por último aos
  primeiros.
- `POST /admin/banners` com `{text_pt, text_en, starts_at, ends_at}`: 201 com o banner.
- `PATCH /admin/banners/{id}` com qualquer parte dos mesmos campos: o banner.
- `POST /admin/banners/{id}/end`: o banner, com a janela fechada agora.
- `GET /banners/active`, sem login (nem Origin, por ser GET): `{"banner": {id, text_pt, text_en,
  starts_at, ends_at} | null}`, o banner no ar agora.

Banner que não existe: 404 `not_found`.
"""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query

from app.admin import accounts, banners
from app.admin.accounts import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, UserFilters, UserSummary
from app.admin.schemas import (
    ActiveBanner,
    AppUserHabits,
    AppUserList,
    AppUserOut,
    BannerCreate,
    BannerList,
    BannerOut,
    BannerUpdate,
    PublicBanner,
)
from app.db import SessionDep
from app.habits.access import MAX_ID, HabitAccess, HabitRole
from app.habits.routes import habit_out
from app.identity import AdminUser, require_admin
from app.mail.language import Locale
from app.marks.routes import mark_out
from app.models import EMAIL_MAX_LENGTH, MAX_USER_ID, Banner
from app.progress.schemas import Day

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
public_router = APIRouter(prefix="/banners", tags=["banners"])

UserId = Annotated[int, Path(ge=1, le=MAX_USER_ID)]
BannerId = Annotated[int, Path(ge=1, le=MAX_ID)]
Cursor = Annotated[str | None, Query(max_length=64)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
QueryDay = Annotated[Day | None, Query()]


def app_user_out(summary: UserSummary) -> AppUserOut:
    user = summary.user
    return AppUserOut(
        id=user.id,
        email=user.email,
        locale=Locale(user.locale),
        timezone=user.timezone,
        first_seen_at=user.first_seen_at,
        habit_count=summary.habit_count,
        mark_count=summary.mark_count,
    )


def banner_out(banner: Banner) -> BannerOut:
    return BannerOut.model_validate(banner, from_attributes=True)


# --- quem usa o ethos ---


@router.get("/users")
def list_users(
    admin: AdminUser,
    session: SessionDep,
    email: Annotated[str | None, Query(max_length=EMAIL_MAX_LENGTH)] = None,
    first_seen_from: QueryDay = None,
    first_seen_to: QueryDay = None,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
) -> AppUserList:
    page = accounts.list_users(
        session,
        tz=ZoneInfo(admin.timezone),
        filters=UserFilters(
            email=email, first_seen_from=first_seen_from, first_seen_to=first_seen_to
        ),
        cursor=cursor,
        limit=limit,
    )
    return AppUserList(
        users=[app_user_out(entry) for entry in page.entries], next_cursor=page.next_cursor
    )


@router.get("/users/{user_id}/habits")
def view_user_habits(
    user_id: UserId,
    admin: AdminUser,
    session: SessionDep,
    habit_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
) -> AppUserHabits:
    content = accounts.view_user_habits(
        session,
        admin_id=admin.id,
        user_id=user_id,
        habit_id=habit_id,
        cursor=cursor,
        limit=limit,
    )
    return AppUserHabits(
        user=app_user_out(content.summary),
        habits=[habit_out(HabitAccess(habit, HabitRole.OWNER), None) for habit in content.habits],
        marks=[mark_out(entry) for entry in content.marks],
        next_cursor=content.next_cursor,
    )


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
def create_banner(body: BannerCreate, admin: AdminUser, session: SessionDep) -> BannerOut:
    banner = banners.create_banner(
        session,
        admin_id=admin.id,
        text_pt=body.text_pt,
        text_en=body.text_en,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    return banner_out(banner)


@router.patch("/banners/{banner_id}")
def update_banner(
    banner_id: BannerId, body: BannerUpdate, admin: AdminUser, session: SessionDep
) -> BannerOut:
    banner = banners.update_banner(
        session,
        admin_id=admin.id,
        banner_id=banner_id,
        values=body.model_dump(exclude_unset=True),
    )
    return banner_out(banner)


@router.post("/banners/{banner_id}/end")
def end_banner(banner_id: BannerId, admin: AdminUser, session: SessionDep) -> BannerOut:
    banner = banners.end_banner(session, admin_id=admin.id, banner_id=banner_id)
    return banner_out(banner)


@public_router.get("/active")
def get_active_banner(session: SessionDep) -> ActiveBanner:
    banner = banners.active_banner(session)
    if banner is None:
        return ActiveBanner(banner=None)
    return ActiveBanner(banner=PublicBanner.model_validate(banner, from_attributes=True))
