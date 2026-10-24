"""Histórico dos hábitos (ETH-25): os eventos do `audit_log` que quem pede pode ver.

Quais eventos (`HistoryEvent`, lista fechada): os de hábito (`habit_created`, `habit_updated`,
`habit_paused`, `habit_resumed`, `habit_archived`, `habit_unarchived`), de marcação
(`mark_created`, `mark_updated`, `mark_deleted`) e de compartilhamento (`invite_*`, `member_*`).
Nunca os de auth, de conta, de admin nem `alert_updated` (a configuração de alerta é de cada
membro, não do hábito). `habit_deleted` vai com `habit_id` nulo e não entra: o hábito já não
existe, e com ele foi a auditoria (decisão do plano).

Quem vê (ethos-plan.md, "compartilhamento"):

- Os eventos dos hábitos que o usuário acessa AGORA: dono, editor ou viewer, de qualquer status
  (arquivado inclusive: ele guarda histórico e continua visível). Quem saiu ou foi removido deixa
  de ver o histórico na hora; quem entrou vê o histórico inteiro do hábito, também o de antes.
- Os convites são do dono (`GET /habits/{id}/invites` só para ele): `invite_created`,
  `invite_canceled` e `invite_declined` só aparecem para o dono. Para os outros membros, eles
  revelariam quem foi convidado e não entrou. `invite_accepted` aparece para todos: quem aceitou
  virou membro e já está em `GET /habits/{id}/members`.
- Filtrar por um hábito sem acesso (ou que não existe) dá a lista vazia, igual a um hábito sem
  eventos: a API não revela que ele existe.

O que sai de cada evento: id, evento, quando (`created_at`, UTC), hábito (id e `label`: a sigla
ou o nome), autor (`user_id` e o email; os dois nulos quando a conta foi apagada, "usuário
removido") e `details` filtrado por `PUBLIC_DETAILS`, a lista de chaves de cada evento. O JSON
gravado nunca é repassado inteiro, e o IP nunca sai (nem é lido).

Filtros, cada um opcional e combináveis (todos juntos com E):

- `habit_id`; `author_id` (o `user_id` de quem fez); `events` (um ou mais `HistoryEvent`);
- `mark_id`: os eventos de uma marcação ("detalhes da marcação: quem e quando"), pelo
  `details.mark_id`, que a coluna calculada `audit_log.mark_id` expõe com índice (migração 0002);
- `first_day` / `last_day`: datas locais inclusivas no fuso de quem pede, como na API de
  progresso (ETH-23): de `first_day` 00:00 até o fim de `last_day`, no `users.timezone`.

Paginação por cursor (`app/pagination.py`): ordem `created_at` desc e `id` desc, `limit` por
página (`DEFAULT_PAGE_SIZE`, no máximo `MAX_PAGE_SIZE`). A página seguinte continua depois do
`(created_at, id)` da última linha: eventos novos (mais recentes) não entram nas páginas
seguintes, e nada se repete nem é pulado.

Uma consulta por página (com os hábitos e os emails em JOIN), sem N+1.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.audit import AuditEvent
from app.errors import ApiError, ErrorCode
from app.models import AuditLog, Habit, HabitMember, User
from app.pagination import decode_cursor, encode_cursor

# Eventos por página (ethos-plan.md, "paginação de listas")
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class HistoryEvent(StrEnum):
    """Eventos do histórico: os de hábito, de marcação e de compartilhamento do `AuditEvent`."""

    HABIT_CREATED = AuditEvent.HABIT_CREATED.value
    HABIT_UPDATED = AuditEvent.HABIT_UPDATED.value
    HABIT_PAUSED = AuditEvent.HABIT_PAUSED.value
    HABIT_RESUMED = AuditEvent.HABIT_RESUMED.value
    HABIT_ARCHIVED = AuditEvent.HABIT_ARCHIVED.value
    HABIT_UNARCHIVED = AuditEvent.HABIT_UNARCHIVED.value
    MARK_CREATED = AuditEvent.MARK_CREATED.value
    MARK_UPDATED = AuditEvent.MARK_UPDATED.value
    MARK_DELETED = AuditEvent.MARK_DELETED.value
    INVITE_CREATED = AuditEvent.INVITE_CREATED.value
    INVITE_CANCELED = AuditEvent.INVITE_CANCELED.value
    INVITE_ACCEPTED = AuditEvent.INVITE_ACCEPTED.value
    INVITE_DECLINED = AuditEvent.INVITE_DECLINED.value
    MEMBER_LEFT = AuditEvent.MEMBER_LEFT.value
    MEMBER_REMOVED = AuditEvent.MEMBER_REMOVED.value
    MEMBER_ROLE_CHANGED = AuditEvent.MEMBER_ROLE_CHANGED.value


# Eventos que só o dono do hábito vê (os convites que não viraram membro)
OWNER_ONLY_EVENTS: frozenset[HistoryEvent] = frozenset(
    {HistoryEvent.INVITE_CREATED, HistoryEvent.INVITE_CANCELED, HistoryEvent.INVITE_DECLINED}
)

_MARK_SNAPSHOT = ("mark_id", "author_id", "marked_at", "duration_minutes", "cost_cents", "has_note")
_INVITE = ("invite_id", "role")

# Chaves do `details` que saem no histórico, por evento (o que cada service grava; ver os
# docstrings de app/habits/service.py, app/marks/service.py e app/sharing/service.py)
PUBLIC_DETAILS: Mapping[HistoryEvent, tuple[str, ...]] = {
    HistoryEvent.HABIT_CREATED: (),
    HistoryEvent.HABIT_UPDATED: ("changes",),
    HistoryEvent.HABIT_PAUSED: (),
    HistoryEvent.HABIT_RESUMED: (),
    HistoryEvent.HABIT_ARCHIVED: (),
    HistoryEvent.HABIT_UNARCHIVED: (),
    HistoryEvent.MARK_CREATED: _MARK_SNAPSHOT,
    HistoryEvent.MARK_UPDATED: ("mark_id", "changes"),
    HistoryEvent.MARK_DELETED: _MARK_SNAPSHOT,
    HistoryEvent.INVITE_CREATED: _INVITE,
    HistoryEvent.INVITE_CANCELED: _INVITE,
    HistoryEvent.INVITE_ACCEPTED: _INVITE,
    HistoryEvent.INVITE_DECLINED: _INVITE,
    HistoryEvent.MEMBER_LEFT: ("role",),
    HistoryEvent.MEMBER_REMOVED: ("member_id", "role"),
    HistoryEvent.MEMBER_ROLE_CHANGED: ("member_id", "changes"),
}
# Chaves de cada item de `changes` (`{"field", "old", "new"}`; o texto da observação e da
# descrição vai só com `field`)
_CHANGE_KEYS = ("field", "old", "new")


@dataclass(frozen=True, slots=True)
class HistoryFilters:
    """Filtros do histórico; None (ou `events` vazio) é "sem filtro"."""

    habit_id: int | None = None
    # `user_id` de quem fez
    author_id: int | None = None
    events: Collection[HistoryEvent] | None = None
    mark_id: int | None = None
    # Datas locais inclusivas, no fuso de quem pede
    first_day: date | None = None
    last_day: date | None = None


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    id: int
    event: HistoryEvent
    created_at: datetime
    habit_id: int
    habit_label: str
    # Os dois None: conta apagada ("usuário removido")
    author_id: int | None
    author_email: str | None
    # Já filtrado por `PUBLIC_DETAILS`
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class HistoryPage:
    entries: list[HistoryEntry]
    # Cursor da próxima página; None na última
    next_cursor: str | None


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _public_changes(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    changes = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("field"), str):
            changes.append(
                {key: item[key] for key in _CHANGE_KEYS if key in item and _is_scalar(item[key])}
            )
    return changes


def public_details(event: HistoryEvent, details: Any) -> dict[str, Any]:
    """As chaves de `details` que o evento mostra (`PUBLIC_DETAILS`), só com valores simples.

    Chave fora da lista, valor que não é texto, número, booleano ou nulo, e `changes` fora do
    formato `[{"field", "old", "new"}]` ficam de fora: o histórico nunca repassa o JSON gravado.
    """
    if not isinstance(details, dict):
        return {}
    public: dict[str, Any] = {}
    for key in PUBLIC_DETAILS[event]:
        if key not in details:
            continue
        if key == "changes":
            changes = _public_changes(details[key])
            if changes is not None:
                public[key] = changes
        elif _is_scalar(details[key]):
            public[key] = details[key]
    return public


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    # Meia-noite que não existe (horário de verão às 00:00) vira, com fold=0, o instante da
    # mudança, como em app/marks/service.day_bounds
    return datetime.combine(day, time(), tzinfo=tz).astimezone(UTC)


def _conditions(user_id: int, filters: HistoryFilters, tz: ZoneInfo) -> list[Any]:
    if (
        filters.first_day is not None
        and filters.last_day is not None
        and filters.last_day < filters.first_day
    ):
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, field="to")
    is_owner = Habit.owner_id == user_id
    shared = select(HabitMember.habit_id).where(HabitMember.user_id == user_id)
    events = sorted(filters.events or HistoryEvent)
    conditions: list[Any] = [
        or_(is_owner, Habit.id.in_(shared)),
        AuditLog.event.in_(events),
        or_(is_owner, AuditLog.event.not_in(sorted(OWNER_ONLY_EVENTS))),
    ]
    if filters.habit_id is not None:
        conditions.append(AuditLog.habit_id == filters.habit_id)
    if filters.author_id is not None:
        conditions.append(AuditLog.user_id == filters.author_id)
    if filters.mark_id is not None:
        conditions.append(AuditLog.mark_id == filters.mark_id)
    if filters.first_day is not None:
        conditions.append(AuditLog.created_at >= _local_midnight(filters.first_day, tz))
    if filters.last_day is not None:
        end = _local_midnight(filters.last_day + timedelta(days=1), tz)
        conditions.append(AuditLog.created_at < end)
    return conditions


def list_history(
    session: Session,
    *,
    user_id: int,
    tz: ZoneInfo,
    filters: HistoryFilters,
    cursor: str | None,
    limit: int,
) -> HistoryPage:
    """Uma página do histórico de `user_id`, do mais recente ao mais antigo.

    `tz`: o fuso de quem pede (`users.timezone`), para as datas do filtro. `limit`: 1 a
    `MAX_PAGE_SIZE` (a rota confere). Cursor inválido: 422 `cursor`; `last_day` antes de
    `first_day`: 422 `to`.
    """
    conditions = _conditions(user_id, filters, tz)
    if cursor is not None:
        after_at, after_id = decode_cursor(cursor)
        conditions.append(
            or_(
                AuditLog.created_at < after_at,
                and_(AuditLog.created_at == after_at, AuditLog.id < after_id),
            )
        )
    rows = session.execute(
        select(
            AuditLog.id,
            AuditLog.event,
            AuditLog.created_at,
            AuditLog.habit_id,
            AuditLog.user_id,
            AuditLog.details,
            Habit.name,
            Habit.code,
            User.email,
        )
        .join(Habit, Habit.id == AuditLog.habit_id)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit + 1)
    ).all()
    entries = []
    for row in rows[:limit]:
        event = HistoryEvent(row.event)
        entries.append(
            HistoryEntry(
                id=row.id,
                event=event,
                created_at=row.created_at,
                habit_id=row.habit_id,
                habit_label=row.code or row.name,
                author_id=row.user_id if row.email is not None else None,
                author_email=row.email,
                details=public_details(event, row.details),
            )
        )
    next_cursor = None
    if len(rows) > limit:
        next_cursor = encode_cursor(entries[-1].created_at, entries[-1].id)
    return HistoryPage(entries, next_cursor)
