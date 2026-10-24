"""`GET /history` (ETH-25): o histórico dos hábitos que o usuário acessa, do mais recente ao mais
antigo. Exige `CurrentUser`; todo papel lê. Regras em `service.py`.

Filtros (todos opcionais, combinados com E; valor inválido dá 422 com o campo):

- `habit_id`: só esse hábito. Sem acesso ou inexistente: lista vazia, sem erro.
- `user_id`: só o que essa pessoa fez.
- `event`: repetido na query (`&event=mark_created&event=mark_deleted`), só esses eventos, da
  lista de `HistoryEvent` (outro valor, como `login`, dá 422).
- `mark_id`: os eventos de uma marcação (criada, editada, apagada): quem fez e quando.
- `from` e `to`: datas locais `YYYY-MM-DD`, inclusivas, no fuso de quem pede (como em
  `GET /habits/progress`); `to` antes de `from`: 422 em `to`.

Paginação: `limit` de 1 a 200 (padrão 50); com `next_cursor` não nulo, repita com
`&cursor=<next_cursor>` e os mesmos filtros.

Resposta: `{"events": [{id, event, created_at, habit: {id, label}, author: {id, email} | null,
details}], "next_cursor"}`. `author: null` é "usuário removido". O IP nunca sai.
"""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.auth.deps import CurrentUser
from app.db import SessionDep
from app.habits.access import MAX_ID
from app.history import service
from app.history.schemas import HistoryEntryOut, HistoryHabit, HistoryList
from app.history.service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    HistoryEntry,
    HistoryEvent,
    HistoryFilters,
)
from app.marks.schemas import Author
from app.progress.schemas import Day

router = APIRouter(prefix="/history", tags=["history"])

# Id num filtro da query
QueryId = Annotated[int | None, Query(ge=1, le=MAX_ID)]


def entry_out(entry: HistoryEntry) -> HistoryEntryOut:
    author = None
    if entry.author_id is not None and entry.author_email is not None:
        author = Author(id=entry.author_id, email=entry.author_email)
    return HistoryEntryOut(
        id=entry.id,
        event=entry.event,
        created_at=entry.created_at,
        habit=HistoryHabit(id=entry.habit_id, label=entry.habit_label),
        author=author,
        details=entry.details,
    )


@router.get("")
def get_history(
    user: CurrentUser,
    session: SessionDep,
    habit_id: QueryId = None,
    user_id: QueryId = None,
    event: Annotated[list[HistoryEvent] | None, Query(max_length=len(HistoryEvent))] = None,
    mark_id: QueryId = None,
    first_day: Annotated[Day | None, Query(alias="from")] = None,
    last_day: Annotated[Day | None, Query(alias="to")] = None,
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> HistoryList:
    page = service.list_history(
        session,
        user_id=user.id,
        tz=ZoneInfo(user.timezone),
        filters=HistoryFilters(
            habit_id=habit_id,
            author_id=user_id,
            events=event,
            mark_id=mark_id,
            first_day=first_day,
            last_day=last_day,
        ),
        cursor=cursor,
        limit=limit,
    )
    return HistoryList(
        events=[entry_out(entry) for entry in page.entries], next_cursor=page.next_cursor
    )
