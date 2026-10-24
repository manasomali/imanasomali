"""Regras das marcações: marcar, desmarcar, listar, editar e apagar (ETH-22).

Cada escrita abre o próprio `write_transaction` (BEGIN IMMEDIATE) e faz dentro dele as leituras
que decidem a escrita: acesso, status e modo do hábito, marcações do dia. Duas requests ao mesmo
tempo nunca leem o mesmo estado: a segunda espera o commit da primeira e lê de novo. Ordem das
recusas: 404 `not_found` (sem acesso ou id que não existe), 403 `forbidden` (viewer), 409
`habit_archived`, 409 `mark_mode_mismatch`, 422 `validation_error` (com o campo) e 409
`mark_limit_reached`.

Regras (ethos-plan.md, "marcações e fuso horário", "custo", "compartilhamento"):

- Quem escreve: dono e editor, em qualquer marcação do hábito (inclusive as de outras pessoas).
  Viewer só lê. Arquivado é só leitura; pausado continua marcável.
- Toggle (`multi_mark` desligado): o cliente manda o início e o fim do dia clicado, no fuso dele,
  em UTC (de 23 h a 25 h, por causa do horário de verão), e o `marked_at` dentro desse dia. Se o
  intervalo já tem marcação (de qualquer membro), todas são apagadas; senão, uma é criada. Clique
  duplo ou dois membros clicando juntos: a segunda request vê o resultado da primeira, então o dia
  fica com uma marcação ou nenhuma, nunca duas.
- Várias por dia (`multi_mark` ligado): `MAX_MARKS_PER_DAY` conta as marcações do hábito (de
  todos os membros) no dia de `marked_at` no fuso salvo de quem marca (`users.timezone`), na mesma
  transação da inserção.
- `marked_at`: no máximo `FUTURE_TOLERANCE` (1 min) no futuro, pela diferença de relógio. Dias
  antes da criação do hábito são aceitos (histórico; a pontuação os ignora).
- Valores gravados na criação: a duração (só com o recurso ligado; o toggle e a marcação sem
  duração usam a padrão do hábito) e o custo (só com o recurso ligado; nível hábito: sempre o valor
  fixo do hábito, e mandar outro é recusado; nível marcação: o valor mandado ou, sem ele, o padrão
  do hábito). O custo fica na marcação: mudar o do hábito depois não muda as antigas. Com o
  recurso desligado, a coluna fica nula e mandar o campo é recusado.
- Observação: só com `notes_enabled`, até `MAX_NOTE_LENGTH` caracteres.
- Editar: só observação, duração e custo, com as mesmas regras de recurso ligado (custo só no
  nível marcação). A data não muda.
- Auditoria: `mark_created`, `mark_updated` e `mark_deleted`, com `habit_id`, quem fez (`user_id`)
  e o que mudou (`details`). O texto da observação nunca vai para a auditoria, só se existe.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.config import Settings
from app.db import write_transaction
from app.errors import ApiError, ErrorCode
from app.habits.access import MAX_ID, get_habit_access, require_writable
from app.models import CostLevel, Habit, Mark, User, utcnow

# Tolerância para o relógio de quem marca estar adiantado
FUTURE_TOLERANCE = timedelta(minutes=1)
# Tamanho do dia do toggle: 23 h e 25 h nos dias de mudança do horário de verão
MIN_DAY_LENGTH = timedelta(hours=23)
MAX_DAY_LENGTH = timedelta(hours=25)
# Maior intervalo da listagem: um ano do calendário com folga para o fuso
MAX_LIST_RANGE = timedelta(days=367)
# Marcações por página na listagem
MAX_PAGE_SIZE = 1000

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)
# Cursor da listagem: "<microssegundos de marked_at desde 1970>.<id>" da última marcação vista
_CURSOR_RE = re.compile(r"(-?[0-9]{1,18})\.([0-9]{1,19})")


@dataclass(frozen=True, slots=True)
class MarkEntry:
    """Uma marcação e o email do autor (None: conta apagada, "usuário removido")."""

    mark: Mark
    author_email: str | None


@dataclass(frozen=True, slots=True)
class MarkPage:
    entries: list[MarkEntry]
    # Cursor da próxima página; None na última
    next_cursor: str | None


def _invalid(field: str) -> ApiError:
    return ApiError(422, ErrorCode.VALIDATION_ERROR, field=field)


def day_bounds(instant: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Início e fim (exclusivo), em UTC, do dia local de `instant` no fuso `tz`."""
    day = instant.astimezone(tz).date()
    # Meia-noite que não existe (horário de verão que começa às 00:00) vira, com fold=0, o
    # instante da mudança, como em score.period_containing
    start = datetime.combine(day, time(), tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), tzinfo=tz).astimezone(UTC)
    return start, end


def encode_cursor(mark: Mark) -> str:
    return f"{(mark.marked_at - _EPOCH) // _MICROSECOND}.{mark.id}"


def decode_cursor(value: str) -> tuple[datetime, int]:
    """`marked_at` e id da última marcação vista; cursor inválido dá 422 `cursor`."""
    match = _CURSOR_RE.fullmatch(value)
    if match is None or int(match[2]) > MAX_ID:
        raise _invalid("cursor")
    try:
        marked_at = _EPOCH + int(match[1]) * _MICROSECOND
    except OverflowError:
        raise _invalid("cursor") from None
    return marked_at, int(match[2])


def _writable_habit(session: Session, habit_id: int, user_id: int) -> Habit:
    """O hábito em que `user_id` pode escrever marcações (404, 403 ou 409 `habit_archived`)."""
    access = get_habit_access(session, habit_id, user_id)
    if not access.can_mark:
        raise ApiError(403, ErrorCode.FORBIDDEN)
    return require_writable(access)


def _require_mode(habit: Habit, *, multi_mark: bool) -> None:
    """409 `mark_mode_mismatch` se o endpoint não é o do modo do hábito."""
    if habit.multi_mark != multi_mark:
        raise ApiError(409, ErrorCode.MARK_MODE_MISMATCH)


def _check_marked_at(marked_at: datetime) -> None:
    if marked_at > utcnow() + FUTURE_TOLERANCE:
        raise _invalid("marked_at")


def _check_note(habit: Habit, settings: Settings, note: str | None) -> None:
    if note is None:
        return
    if not habit.notes_enabled or len(note) > settings.max_note_length:
        raise _invalid("note")


def mark_duration(habit: Habit, duration_minutes: int | None) -> int | None:
    """Duração a gravar numa marcação nova: a pedida ou a padrão do hábito; None com o recurso
    desligado (pedir uma, então, dá 422 `duration_minutes`)."""
    if not habit.duration_enabled:
        if duration_minutes is not None:
            raise _invalid("duration_minutes")
        return None
    return habit.duration_minutes if duration_minutes is None else duration_minutes


def mark_cost(habit: Habit, cost_cents: int | None) -> int | None:
    """Custo a gravar numa marcação nova (422 `cost_cents` se o valor pedido não cabe).

    Desligado: None. Nível hábito: o valor fixo do hábito (pedir outro é recusado). Nível
    marcação: o pedido ou, sem ele, o padrão do hábito.
    """
    if not habit.cost_enabled:
        if cost_cents is not None:
            raise _invalid("cost_cents")
        return None
    if habit.cost_level == CostLevel.HABIT:
        # Valor fixo do hábito: todo mundo que marca gera o mesmo custo
        if cost_cents is not None:
            raise _invalid("cost_cents")
        return habit.cost_cents
    return habit.cost_cents if cost_cents is None else cost_cents


def _snapshot(mark: Mark) -> dict[str, Any]:
    """O que a auditoria guarda da marcação (a observação, só se existe)."""
    return {
        "mark_id": mark.id,
        "author_id": mark.user_id,
        "marked_at": mark.marked_at.astimezone(UTC).isoformat(),
        "duration_minutes": mark.duration_minutes,
        "cost_cents": mark.cost_cents,
        "has_note": mark.note is not None,
    }


def _entry(session: Session, mark: Mark) -> MarkEntry:
    email = None
    if mark.user_id is not None:
        email = session.scalar(select(User.email).where(User.id == mark.user_id))
    return MarkEntry(mark, email)


def insert_mark(
    session: Session,
    habit_id: int,
    *,
    user_id: int,
    marked_at: datetime,
    note: str | None,
    duration_minutes: int | None,
    cost_cents: int | None,
    ip: str | None,
) -> MarkEntry:
    """Grava a marcação com os valores já resolvidos e o evento `mark_created`.

    Não confere acesso nem regras: quem chama já está num `write_transaction` e já validou.
    """
    mark = Mark(
        habit_id=habit_id,
        user_id=user_id,
        marked_at=marked_at,
        note=note,
        duration_minutes=duration_minutes,
        cost_cents=cost_cents,
    )
    session.add(mark)
    session.flush()
    audit.record(
        session,
        AuditEvent.MARK_CREATED,
        user_id=user_id,
        ip=ip,
        habit_id=habit_id,
        details=_snapshot(mark),
    )
    return _entry(session, mark)


def _remove(session: Session, mark: Mark, *, user_id: int, ip: str | None) -> None:
    details = _snapshot(mark)
    session.delete(mark)
    audit.record(
        session,
        AuditEvent.MARK_DELETED,
        user_id=user_id,
        ip=ip,
        habit_id=mark.habit_id,
        details=details,
    )


def _marks_between(habit_id: int, start: datetime, end: datetime) -> ColumnElement[bool]:
    return and_(Mark.habit_id == habit_id, Mark.marked_at >= start, Mark.marked_at < end)


def toggle_mark(
    session: Session,
    *,
    user_id: int,
    habit_id: int,
    day_start: datetime,
    day_end: datetime,
    marked_at: datetime,
    ip: str | None,
) -> MarkEntry | None:
    """Marca ou desmarca o dia `[day_start, day_end)` de um hábito toggle.

    Devolve a marcação criada, ou None quando o clique apagou as do dia. Levanta 404, 403, 409
    (`habit_archived`, `mark_mode_mismatch`) ou 422 (`day_end`, `marked_at`).
    """
    with write_transaction(session):
        habit = _writable_habit(session, habit_id, user_id)
        _require_mode(habit, multi_mark=False)
        if not MIN_DAY_LENGTH <= day_end - day_start <= MAX_DAY_LENGTH:
            raise _invalid("day_end")
        if not day_start <= marked_at < day_end:
            raise _invalid("marked_at")
        _check_marked_at(marked_at)
        existing = session.scalars(
            select(Mark)
            .where(_marks_between(habit_id, day_start, day_end))
            .order_by(Mark.id)
            .execution_options(populate_existing=True)
        ).all()
        if existing:
            for mark in existing:
                _remove(session, mark, user_id=user_id, ip=ip)
            return None
        return insert_mark(
            session,
            habit_id,
            user_id=user_id,
            marked_at=marked_at,
            note=None,
            duration_minutes=mark_duration(habit, None),
            cost_cents=mark_cost(habit, None),
            ip=ip,
        )


def create_mark(
    session: Session,
    settings: Settings,
    *,
    user_id: int,
    timezone: str,
    habit_id: int,
    marked_at: datetime,
    note: str | None,
    duration_minutes: int | None,
    cost_cents: int | None,
    ip: str | None,
) -> MarkEntry:
    """Cria uma marcação num hábito com várias por dia. `timezone`: o fuso salvo de quem marca.

    Levanta 404, 403, 409 (`habit_archived`, `mark_mode_mismatch`, `mark_limit_reached`) ou 422
    (`marked_at`, `note`, `duration_minutes`, `cost_cents`).
    """
    with write_transaction(session):
        habit = _writable_habit(session, habit_id, user_id)
        _require_mode(habit, multi_mark=True)
        _check_marked_at(marked_at)
        _check_note(habit, settings, note)
        duration_minutes = mark_duration(habit, duration_minutes)
        cost_cents = mark_cost(habit, cost_cents)
        start, end = day_bounds(marked_at, ZoneInfo(timezone))
        marks_in_day = session.scalar(
            select(func.count()).select_from(Mark).where(_marks_between(habit_id, start, end))
        )
        if marks_in_day >= settings.max_marks_per_day:
            raise ApiError(409, ErrorCode.MARK_LIMIT_REACHED)
        return insert_mark(
            session,
            habit_id,
            user_id=user_id,
            marked_at=marked_at,
            note=note,
            duration_minutes=duration_minutes,
            cost_cents=cost_cents,
            ip=ip,
        )


def _get_mark(session: Session, habit_id: int, mark_id: int) -> Mark:
    mark = session.scalar(
        select(Mark)
        .where(Mark.id == mark_id, Mark.habit_id == habit_id)
        .execution_options(populate_existing=True)
    )
    if mark is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    return mark


def _check_update(habit: Habit, settings: Settings, values: Mapping[str, Any]) -> None:
    if "note" in values:
        if not habit.notes_enabled:
            raise _invalid("note")
        _check_note(habit, settings, values["note"])
    if "duration_minutes" in values and not habit.duration_enabled:
        raise _invalid("duration_minutes")
    if "cost_cents" in values and (not habit.cost_enabled or habit.cost_level != CostLevel.MARK):
        raise _invalid("cost_cents")


def _change(name: str, old: Any, new: Any) -> dict[str, Any]:
    # A observação vai só pelo nome: o texto do usuário não entra na auditoria
    if name == "note":
        return {"field": name}
    return {"field": name, "old": old, "new": new}


def update_mark(
    session: Session,
    settings: Settings,
    *,
    user_id: int,
    habit_id: int,
    mark_id: int,
    values: Mapping[str, Any],
    ip: str | None,
) -> MarkEntry:
    """Muda `note`, `duration_minutes` e `cost_cents` (só os enviados em `values`).

    Levanta 404 (hábito ou marcação), 403, 409 `habit_archived` ou 422 (campo de recurso
    desligado, custo no nível hábito, observação longa). Sem mudança, nada é gravado.
    """
    with write_transaction(session):
        habit = _writable_habit(session, habit_id, user_id)
        mark = _get_mark(session, habit_id, mark_id)
        _check_update(habit, settings, values)
        changes = []
        for name in ("note", "duration_minutes", "cost_cents"):
            if name in values and getattr(mark, name) != values[name]:
                changes.append(_change(name, getattr(mark, name), values[name]))
                setattr(mark, name, values[name])
        if changes:
            audit.record(
                session,
                AuditEvent.MARK_UPDATED,
                user_id=user_id,
                ip=ip,
                habit_id=habit_id,
                details={"mark_id": mark_id, "changes": changes},
            )
        return _entry(session, mark)


def delete_mark(
    session: Session, *, user_id: int, habit_id: int, mark_id: int, ip: str | None
) -> None:
    """Apaga a marcação. Levanta 404 (hábito ou marcação), 403 ou 409 `habit_archived`."""
    with write_transaction(session):
        _writable_habit(session, habit_id, user_id)
        _remove(session, _get_mark(session, habit_id, mark_id), user_id=user_id, ip=ip)


def list_marks(
    session: Session,
    *,
    user_id: int,
    habit_id: int,
    start: datetime,
    end: datetime,
    cursor: str | None,
    limit: int,
) -> MarkPage:
    """Marcações do hábito com `marked_at` em `[start, end)`, por `marked_at` e id.

    Intervalo vazio, invertido ou maior que `MAX_LIST_RANGE`: 422 `to`. Cursor inválido: 422
    `cursor`. Todo papel lê, inclusive em arquivado.
    """
    if end <= start or end - start > MAX_LIST_RANGE:
        raise _invalid("to")
    after = None if cursor is None else decode_cursor(cursor)
    get_habit_access(session, habit_id, user_id)
    query = (
        select(Mark, User.email)
        .outerjoin(User, User.id == Mark.user_id)
        .where(_marks_between(habit_id, start, end))
    )
    if after is not None:
        after_marked_at, after_id = after
        query = query.where(
            or_(
                Mark.marked_at > after_marked_at,
                and_(Mark.marked_at == after_marked_at, Mark.id > after_id),
            )
        )
    rows = session.execute(
        query.order_by(Mark.marked_at, Mark.id)
        .limit(limit + 1)
        .execution_options(populate_existing=True)
    ).all()
    entries = [MarkEntry(mark, email) for mark, email in rows[:limit]]
    next_cursor = encode_cursor(entries[-1].mark) if len(rows) > limit else None
    return MarkPage(entries, next_cursor)
