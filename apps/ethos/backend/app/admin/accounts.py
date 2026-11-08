"""Quem usa o ethos, no painel de admin (ETH-28): listar e ver o conteúdo dos hábitos.

As contas (bloquear, trocar email, excluir) são do imago (`/imago/admin`); aqui fica só quem usa o
ethos (`app_users`) e o conteúdo dos hábitos de cada um. Quem chama (as rotas) garante que quem
pede é admin (`AdminUser`, pelo `X-User-Admin` do imago).

Contagens e datas da listagem:

- `habit_count`: hábitos dos quais a pessoa é dona, em qualquer status (ativos, pausados e
  arquivados). `mark_count`: marcações que ela fez, em qualquer hábito (`marks.user_id`). As duas
  saem de subconsultas correlacionadas na mesma consulta da página: uma consulta por página, sem
  N+1.
- Primeiro acesso: `app_users.first_seen_at` (o primeiro request com login no ethos; para as
  contas de antes do imago, o cadastro no ethos).
- Filtros de data: datas locais inclusivas no fuso de quem pede (o admin), como no histórico.

Auditoria: `admin_viewed_habits` com `user_id` = o admin e `{target_user_id, habit_id?}`, uma
linha por chamada (cada página). O id da pessoa vai em `details.target_user_id`, que é como a
exclusão dos dados dela acha a linha (`app/internal/service.py`).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.db import write_transaction
from app.errors import ApiError, ErrorCode
from app.internal.service import TARGET_USER_KEY
from app.marks.service import MarkEntry
from app.models import AppUser, Habit, Mark
from app.pagination import decode_cursor, encode_cursor

# Paginação das listas do admin (como o histórico): padrão e máximo por página
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class UserFilters:
    """Filtros da listagem, todos opcionais e combinados com E.

    `email`: trecho do email (espaços nas pontas e maiúsculas não importam). Datas: locais e
    inclusivas, no fuso de quem pede.
    """

    email: str | None = None
    first_seen_from: date | None = None
    first_seen_to: date | None = None


@dataclass(frozen=True, slots=True)
class UserSummary:
    """Quem usa o ethos, com as contagens da listagem."""

    user: AppUser
    habit_count: int
    mark_count: int


@dataclass(frozen=True, slots=True)
class UserPage:
    entries: list[UserSummary]
    # Cursor da próxima página; None na última
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class UserContent:
    """Conteúdo dos hábitos de uma pessoa: todos os hábitos dela e uma página das marcações."""

    summary: UserSummary
    habits: list[Habit]
    marks: list[MarkEntry]
    next_cursor: str | None


def _not_found() -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND)


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    # Meia-noite que não existe (horário de verão às 00:00) vira, com fold=0, o instante da
    # mudança, como no histórico
    return datetime.combine(day, time(), tzinfo=tz).astimezone(UTC)


def _conditions(filters: UserFilters, tz: ZoneInfo) -> list[Any]:
    first, last = filters.first_seen_from, filters.first_seen_to
    if first is not None and last is not None and last < first:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, field="first_seen_to")
    conditions: list[Any] = []
    if first is not None:
        conditions.append(AppUser.first_seen_at >= _local_midnight(first, tz))
    if last is not None:
        conditions.append(AppUser.first_seen_at < _local_midnight(last + timedelta(days=1), tz))
    term = (filters.email or "").strip().lower()
    if term:
        # instr e não LIKE: `%` e `_` no trecho são letras, não curingas
        conditions.append(func.instr(AppUser.email, term) > 0)
    return conditions


def _summary_query() -> Select[tuple[AppUser, int, int]]:
    habit_count = (
        select(func.count(Habit.id))
        .where(Habit.owner_id == AppUser.id)
        .correlate(AppUser)
        .scalar_subquery()
    )
    mark_count = (
        select(func.count(Mark.id))
        .where(Mark.user_id == AppUser.id)
        .correlate(AppUser)
        .scalar_subquery()
    )
    # populate_existing: relê a linha mesmo que a sessão já tenha o objeto
    return select(AppUser, habit_count, mark_count).execution_options(populate_existing=True)


def list_users(
    session: Session, *, tz: ZoneInfo, filters: UserFilters, cursor: str | None, limit: int
) -> UserPage:
    """Uma página de quem usa o ethos, do primeiro acesso mais novo ao mais antigo.

    `tz`: o fuso de quem pede, para as datas dos filtros. `limit`: 1 a `MAX_PAGE_SIZE` (a rota
    confere). Data final antes da inicial: 422 em `first_seen_to`; cursor inválido: 422 `cursor`.
    """
    conditions = _conditions(filters, tz)
    if cursor is not None:
        after_at, after_id = decode_cursor(cursor)
        conditions.append(
            or_(
                AppUser.first_seen_at < after_at,
                and_(AppUser.first_seen_at == after_at, AppUser.id < after_id),
            )
        )
    rows = session.execute(
        _summary_query()
        .where(*conditions)
        .order_by(AppUser.first_seen_at.desc(), AppUser.id.desc())
        .limit(limit + 1)
    ).all()
    entries = [UserSummary(user, habits, marks) for user, habits, marks in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = entries[-1].user
        next_cursor = encode_cursor(last.first_seen_at, last.id)
    return UserPage(entries, next_cursor)


def _summary(session: Session, user_id: int) -> UserSummary:
    """A pessoa com as contagens; 404 se ela não usa o ethos (sem linha em `app_users`)."""
    row = session.execute(_summary_query().where(AppUser.id == user_id)).one_or_none()
    if row is None:
        raise _not_found()
    user, habits, marks = row
    return UserSummary(user, habits, marks)


def view_user_habits(
    session: Session,
    *,
    admin_id: int,
    user_id: int,
    habit_id: int | None,
    cursor: str | None,
    limit: int,
) -> UserContent:
    """Conteúdo dos hábitos da pessoa, para o admin, e o `admin_viewed_habits` na auditoria.

    Hábitos: todos aqueles de que ela é dona, em qualquer status, por id (a configuração; hábitos
    de outras pessoas em que ela é membro ficam na página do dono). Marcações: de todos os autores
    nesses hábitos (ou só em `habit_id`), com as observações, das mais recentes para as mais
    antigas (`marked_at`, id), `limit` por página.

    A leitura e o registro vão no mesmo `write_transaction`: o conteúdo só sai se a auditoria foi
    gravada. Pessoa que não usa o ethos, ou `habit_id` que não é dela: 404, sem registro. Cursor
    inválido: 422 `cursor`.
    """
    after = None if cursor is None else decode_cursor(cursor)
    with write_transaction(session):
        summary = _summary(session, user_id)
        habits = list(
            session.scalars(
                select(Habit)
                .where(Habit.owner_id == user_id)
                .order_by(Habit.id)
                .execution_options(populate_existing=True)
            )
        )
        if habit_id is not None and all(habit.id != habit_id for habit in habits):
            raise _not_found()
        conditions: list[Any] = [Habit.owner_id == user_id]
        if habit_id is not None:
            conditions.append(Mark.habit_id == habit_id)
        if after is not None:
            after_at, after_id = after
            conditions.append(
                or_(Mark.marked_at < after_at, and_(Mark.marked_at == after_at, Mark.id < after_id))
            )
        rows = session.execute(
            select(Mark, AppUser.email)
            .join(Habit, Habit.id == Mark.habit_id)
            .outerjoin(AppUser, AppUser.id == Mark.user_id)
            .where(*conditions)
            .order_by(Mark.marked_at.desc(), Mark.id.desc())
            .limit(limit + 1)
            .execution_options(populate_existing=True)
        ).all()
        details: dict[str, Any] = {TARGET_USER_KEY: user_id}
        if habit_id is not None:
            details["habit_id"] = habit_id
        # Sem `habit_id` na coluna: a linha não pode sumir com o hábito nem aparecer no histórico
        audit.record(session, AuditEvent.ADMIN_VIEWED_HABITS, user_id=admin_id, details=details)
    marks = [MarkEntry(mark, email) for mark, email in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        next_cursor = encode_cursor(marks[-1].mark.marked_at, marks[-1].mark.id)
    return UserContent(summary, habits, marks, next_cursor)
