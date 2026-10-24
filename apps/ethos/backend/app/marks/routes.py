"""Endpoints das marcações (ETH-22). Todos exigem `CurrentUser`; as regras ficam no `service.py`.

- `POST /habits/{id}/toggle` (hábito toggle) com `{day_start, day_end, marked_at}`: 200
  `{"marked": true, "mark": {...}}` se criou, `{"marked": false, "mark": null}` se apagou as do
  dia. Num hábito com várias por dia: 409 `mark_mode_mismatch`.
- `POST /habits/{id}/marks` (várias por dia) com `{marked_at, note?, duration_minutes?,
  cost_cents?}`: 201 com a marcação. Num hábito toggle: 409 `mark_mode_mismatch`. Dia cheio: 409
  `mark_limit_reached`.
- `GET /habits/{id}/marks?from=&to=&cursor=&limit=`: `{"marks": [...], "next_cursor"}`, as
  marcações com `marked_at` em `[from, to)` (no máximo 367 dias), por `marked_at` e id, até `limit`
  (1 a 1000, padrão 1000) por página. Com `next_cursor` não nulo, há mais: repita com
  `?cursor=<next_cursor>` e os mesmos `from` e `to`. Todo papel lê.
- `PATCH /habits/{id}/marks/{mark_id}` com `{note?, duration_minutes?, cost_cents?}`: a marcação.
  `marked_at` (ou qualquer outro campo) no corpo: 422.
- `DELETE /habits/{id}/marks/{mark_id}`: 204.

Escrita: dono e editor (viewer: 403 `forbidden`); arquivado: 409 `habit_archived`. Marcação: o
`author` é `{id, email}` de quem criou, ou `null` quando a conta foi apagada ("usuário removido").
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request

from app.auth.deps import CurrentUser
from app.config import SettingsDep
from app.db import SessionDep
from app.habits.access import MAX_ID, HabitId
from app.marks import service
from app.marks.schemas import (
    Author,
    Instant,
    MarkCreate,
    MarkList,
    MarkOut,
    MarkUpdate,
    ToggleIn,
    ToggleOut,
)
from app.marks.service import MAX_PAGE_SIZE, MarkEntry
from app.request_info import client_ip

router = APIRouter(prefix="/habits", tags=["marks"])

# Id de marcação no caminho (`/habits/{habit_id}/marks/{mark_id}`)
MarkId = Annotated[int, Path(ge=1, le=MAX_ID)]


def mark_out(entry: MarkEntry) -> MarkOut:
    mark = entry.mark
    author = None
    if mark.user_id is not None and entry.author_email is not None:
        author = Author(id=mark.user_id, email=entry.author_email)
    return MarkOut(
        id=mark.id,
        habit_id=mark.habit_id,
        author=author,
        marked_at=mark.marked_at,
        duration_minutes=mark.duration_minutes,
        cost_cents=mark.cost_cents,
        note=mark.note,
        created_at=mark.created_at,
        updated_at=mark.updated_at,
    )


@router.post("/{habit_id}/toggle")
def toggle_mark(
    habit_id: HabitId,
    body: ToggleIn,
    user: CurrentUser,
    request: Request,
    session: SessionDep,
) -> ToggleOut:
    # O write_transaction expira o usuário: os valores dele são lidos antes
    user_id = user.id
    entry = service.toggle_mark(
        session,
        user_id=user_id,
        habit_id=habit_id,
        day_start=body.day_start,
        day_end=body.day_end,
        marked_at=body.marked_at,
        ip=client_ip(request),
    )
    if entry is None:
        return ToggleOut(marked=False, mark=None)
    return ToggleOut(marked=True, mark=mark_out(entry))


@router.post("/{habit_id}/marks", status_code=201)
def create_mark(
    habit_id: HabitId,
    body: MarkCreate,
    user: CurrentUser,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> MarkOut:
    user_id, timezone = user.id, user.timezone
    entry = service.create_mark(
        session,
        settings,
        user_id=user_id,
        timezone=timezone,
        habit_id=habit_id,
        marked_at=body.marked_at,
        note=body.note,
        duration_minutes=body.duration_minutes,
        cost_cents=body.cost_cents,
        ip=client_ip(request),
    )
    return mark_out(entry)


@router.get("/{habit_id}/marks")
def list_marks(
    habit_id: HabitId,
    user: CurrentUser,
    session: SessionDep,
    start: Annotated[Instant, Query(alias="from")],
    end: Annotated[Instant, Query(alias="to")],
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = MAX_PAGE_SIZE,
) -> MarkList:
    page = service.list_marks(
        session,
        user_id=user.id,
        habit_id=habit_id,
        start=start,
        end=end,
        cursor=cursor,
        limit=limit,
    )
    return MarkList(marks=[mark_out(entry) for entry in page.entries], next_cursor=page.next_cursor)


@router.patch("/{habit_id}/marks/{mark_id}")
def update_mark(
    habit_id: HabitId,
    mark_id: MarkId,
    body: MarkUpdate,
    user: CurrentUser,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> MarkOut:
    user_id = user.id
    entry = service.update_mark(
        session,
        settings,
        user_id=user_id,
        habit_id=habit_id,
        mark_id=mark_id,
        values=body.model_dump(exclude_unset=True),
        ip=client_ip(request),
    )
    return mark_out(entry)


@router.delete("/{habit_id}/marks/{mark_id}", status_code=204)
def delete_mark(
    habit_id: HabitId,
    mark_id: MarkId,
    user: CurrentUser,
    request: Request,
    session: SessionDep,
) -> None:
    user_id = user.id
    service.delete_mark(
        session, user_id=user_id, habit_id=habit_id, mark_id=mark_id, ip=client_ip(request)
    )
