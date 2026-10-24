"""Contas no painel de admin (ETH-28): listar, ver o conteúdo dos hábitos, bloquear, desbloquear
e trocar o email. A exclusão pelo admin é a de `app/auth/deletion.py` (`delete_account`).

Quem chama (as rotas) garante que quem pede é admin (`AdminUser`). Cada escrita abre o próprio
`write_transaction` (BEGIN IMMEDIATE) e confere de novo, dentro dele, que quem age continua admin
ativo (`ensure_admin`): dois admins que se bloqueiam ao mesmo tempo não deixam o serviço sem
nenhum, porque o segundo já não passa (401). Com isso e com o admin não podendo bloquear a si
mesmo (409 `cannot_block_self`), bloquear nunca tira o último admin ativo: quem bloqueia continua
sendo um. Bloquear outro admin é permitido.

Contagens e datas da listagem:

- `habit_count`: hábitos dos quais a conta é dona, em qualquer status (ativos, pausados e
  arquivados). `mark_count`: marcações que a conta fez, em qualquer hábito (`marks.user_id`).
  As duas saem de subconsultas correlacionadas na mesma consulta da página: uma consulta por
  página, sem N+1.
- Último login: a coluna `users.last_login_at`, gravada pelo `verify_login_code` a cada login
  (vazia em conta que nunca entrou pelo código, como as do `seed`). Não vem das sessões (que somem
  no logout e ao vencer) nem do evento `login` da auditoria (apagado depois de 90 dias).
- Filtros de data: datas locais inclusivas no fuso de quem pede (o admin), como no histórico.

Auditoria (todo evento sobre outra conta leva o id dela em `details.target_user_id`, que é como a
exclusão da conta acha a linha e tira os emails; ver `app/audit.py`); `user_id` é o admin:

- `admin_viewed_habits`: `{target_user_id, habit_id?}`, uma linha por chamada (cada página);
- `user_blocked`: `{target_user_id, sessions}` (sessões apagadas); `user_unblocked`:
  `{target_user_id}`. Bloquear quem já está bloqueado (ou desbloquear quem está ativo) não muda
  nada e não grava;
- `email_changed`: `{target_user_id, old_email, new_email, sessions}`.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.auth.deletion import TARGET_USER_KEY
from app.auth.service import OutgoingEmail
from app.db import require_write_transaction, write_transaction
from app.errors import ApiError, ErrorCode
from app.mail.catalog import EmailChangedNew, EmailChangedOld
from app.mail.language import pick_locale
from app.marks.service import MarkEntry
from app.models import Habit, LoginCode, Mark, User, UserSession, utcnow
from app.pagination import decode_cursor, encode_cursor

# Paginação das listas do admin (como o histórico): padrão e máximo por página
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class AccountStatus(StrEnum):
    ACTIVE = "active"
    # `is_active` desligado pelo admin: não recebe código nem entra; os dados ficam
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class AccountFilters:
    """Filtros da listagem, todos opcionais e combinados com E.

    `email`: trecho do email (espaços nas pontas e maiúsculas não importam). Datas: locais e
    inclusivas, no fuso de quem pede.
    """

    email: str | None = None
    status: AccountStatus | None = None
    created_from: date | None = None
    created_to: date | None = None
    last_login_from: date | None = None
    last_login_to: date | None = None


@dataclass(frozen=True, slots=True)
class AccountSummary:
    """Uma conta com as contagens da listagem."""

    user: User
    habit_count: int
    mark_count: int


@dataclass(frozen=True, slots=True)
class AccountPage:
    entries: list[AccountSummary]
    # Cursor da próxima página; None na última
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AccountContent:
    """Conteúdo dos hábitos de uma conta: todos os hábitos dela e uma página das marcações."""

    account: AccountSummary
    habits: list[Habit]
    marks: list[MarkEntry]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class EmailChange:
    """Conta com o email novo e os avisos a agendar depois do commit (antigo e novo)."""

    account: AccountSummary
    emails: tuple[OutgoingEmail, ...]


def ensure_admin(session: Session, admin_id: int) -> None:
    """Confere, dentro do `write_transaction`, que `admin_id` continua admin ativo.

    401 `unauthorized` se a conta sumiu ou foi bloqueada no meio (como a dependência de sessão);
    403 `forbidden` se perdeu o admin.
    """
    require_write_transaction(session)
    row = session.execute(
        select(User.is_active, User.is_admin).where(User.id == admin_id)
    ).one_or_none()
    if row is None or not row.is_active:
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    if not row.is_admin:
        raise ApiError(403, ErrorCode.FORBIDDEN)


def _not_found() -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND)


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    # Meia-noite que não existe (horário de verão às 00:00) vira, com fold=0, o instante da
    # mudança, como no histórico
    return datetime.combine(day, time(), tzinfo=tz).astimezone(UTC)


def _date_range(
    column: Any, first: date | None, last: date | None, tz: ZoneInfo, field: str
) -> list[Any]:
    """Condições de `column` entre as datas locais `first` e `last` (inclusivas)."""
    if first is not None and last is not None and last < first:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, field=field)
    conditions = []
    if first is not None:
        conditions.append(column >= _local_midnight(first, tz))
    if last is not None:
        conditions.append(column < _local_midnight(last + timedelta(days=1), tz))
    return conditions


def _conditions(filters: AccountFilters, tz: ZoneInfo) -> list[Any]:
    conditions = [
        *_date_range(User.created_at, filters.created_from, filters.created_to, tz, "created_to"),
        # Conta que nunca entrou (last_login_at NULL) não passa em nenhum filtro de login
        *_date_range(
            User.last_login_at, filters.last_login_from, filters.last_login_to, tz, "last_login_to"
        ),
    ]
    term = (filters.email or "").strip().lower()
    if term:
        # instr e não LIKE: `%` e `_` no trecho são letras, não curingas
        conditions.append(func.instr(User.email, term) > 0)
    if filters.status is not None:
        conditions.append(User.is_active.is_(filters.status is AccountStatus.ACTIVE))
    return conditions


def _summary_query() -> Select[tuple[User, int, int]]:
    habit_count = (
        select(func.count(Habit.id))
        .where(Habit.owner_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    mark_count = (
        select(func.count(Mark.id)).where(Mark.user_id == User.id).correlate(User).scalar_subquery()
    )
    # populate_existing: relê a conta mesmo que a sessão já tenha o objeto (ex.: o admin)
    return select(User, habit_count, mark_count).execution_options(populate_existing=True)


def list_accounts(
    session: Session, *, tz: ZoneInfo, filters: AccountFilters, cursor: str | None, limit: int
) -> AccountPage:
    """Uma página das contas, das mais novas para as mais antigas (`created_at`, id).

    `tz`: o fuso de quem pede, para as datas dos filtros. `limit`: 1 a `MAX_PAGE_SIZE` (a rota
    confere). Data final antes da inicial: 422 em `created_to` ou `last_login_to`; cursor
    inválido: 422 `cursor`.
    """
    conditions = _conditions(filters, tz)
    if cursor is not None:
        after_at, after_id = decode_cursor(cursor)
        conditions.append(
            or_(
                User.created_at < after_at,
                and_(User.created_at == after_at, User.id < after_id),
            )
        )
    rows = session.execute(
        _summary_query()
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(limit + 1)
    ).all()
    entries = [AccountSummary(user, habits, marks) for user, habits, marks in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = entries[-1].user
        next_cursor = encode_cursor(last.created_at, last.id)
    return AccountPage(entries, next_cursor)


def _summary(session: Session, account_id: int) -> AccountSummary:
    """A conta com as contagens; 404 se não existe."""
    row = session.execute(_summary_query().where(User.id == account_id)).one_or_none()
    if row is None:
        raise _not_found()
    user, habits, marks = row
    return AccountSummary(user, habits, marks)


def _target(session: Session, account_id: int) -> User:
    """A conta alvo, relida dentro da transação; 404 se não existe."""
    user = session.scalar(
        select(User).where(User.id == account_id).execution_options(populate_existing=True)
    )
    if user is None:
        raise _not_found()
    return user


def _delete_sessions(session: Session, account_id: int) -> int:
    result = session.execute(
        delete(UserSession).where(UserSession.user_id == account_id),
        execution_options={"synchronize_session": False},
    )
    return result.rowcount


def view_account_habits(
    session: Session,
    *,
    admin_id: int,
    account_id: int,
    habit_id: int | None,
    cursor: str | None,
    limit: int,
    ip: str | None,
) -> AccountContent:
    """Conteúdo dos hábitos da conta, para o admin, e o `admin_viewed_habits` na auditoria.

    Hábitos: todos aqueles de que a conta é dona, em qualquer status, por id (a configuração;
    hábitos de outras pessoas em que ela é membro ficam na página do dono). Marcações: de todos os
    autores nesses hábitos (ou só em `habit_id`), com as observações, das mais recentes para as
    mais antigas (`marked_at`, id), `limit` por página.

    A leitura e o registro vão no mesmo `write_transaction`: o conteúdo só sai se a auditoria foi
    gravada. Conta que não existe, ou `habit_id` que não é dela: 404, sem registro. Cursor
    inválido: 422 `cursor`.
    """
    after = None if cursor is None else decode_cursor(cursor)
    with write_transaction(session):
        ensure_admin(session, admin_id)
        account = _summary(session, account_id)
        habits = list(
            session.scalars(
                select(Habit)
                .where(Habit.owner_id == account_id)
                .order_by(Habit.id)
                .execution_options(populate_existing=True)
            )
        )
        if habit_id is not None and all(habit.id != habit_id for habit in habits):
            raise _not_found()
        conditions: list[Any] = [Habit.owner_id == account_id]
        if habit_id is not None:
            conditions.append(Mark.habit_id == habit_id)
        if after is not None:
            after_at, after_id = after
            conditions.append(
                or_(Mark.marked_at < after_at, and_(Mark.marked_at == after_at, Mark.id < after_id))
            )
        rows = session.execute(
            select(Mark, User.email)
            .join(Habit, Habit.id == Mark.habit_id)
            .outerjoin(User, User.id == Mark.user_id)
            .where(*conditions)
            .order_by(Mark.marked_at.desc(), Mark.id.desc())
            .limit(limit + 1)
            .execution_options(populate_existing=True)
        ).all()
        details: dict[str, Any] = {TARGET_USER_KEY: account_id}
        if habit_id is not None:
            details["habit_id"] = habit_id
        # Sem `habit_id` na coluna: a linha não pode sumir com o hábito nem aparecer no histórico
        audit.record(
            session, AuditEvent.ADMIN_VIEWED_HABITS, user_id=admin_id, ip=ip, details=details
        )
    marks = [MarkEntry(mark, email) for mark, email in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        next_cursor = encode_cursor(marks[-1].mark.marked_at, marks[-1].mark.id)
    return AccountContent(account, habits, marks, next_cursor)


def block_account(
    session: Session, *, admin_id: int, account_id: int, ip: str | None
) -> AccountSummary:
    """Bloqueia a conta (`is_active` desligado) e apaga as sessões dela.

    O bloqueado não recebe código nem entra (as sessões que sobrassem já dariam 401); os dados
    ficam. 409 `cannot_block_self` para a própria conta; 404 se não existe. Já bloqueada: nada muda.
    """
    if account_id == admin_id:
        raise ApiError(409, ErrorCode.CANNOT_BLOCK_SELF)
    with write_transaction(session):
        ensure_admin(session, admin_id)
        user = _target(session, account_id)
        if user.is_active:
            user.is_active = False
            sessions = _delete_sessions(session, account_id)
            audit.record(
                session,
                AuditEvent.USER_BLOCKED,
                user_id=admin_id,
                ip=ip,
                details={TARGET_USER_KEY: account_id, "sessions": sessions},
            )
        return _summary(session, account_id)


def unblock_account(
    session: Session, *, admin_id: int, account_id: int, ip: str | None
) -> AccountSummary:
    """Desbloqueia a conta (`is_active` ligado). 404 se não existe. Já ativa: nada muda."""
    with write_transaction(session):
        ensure_admin(session, admin_id)
        user = _target(session, account_id)
        if not user.is_active:
            user.is_active = True
            audit.record(
                session,
                AuditEvent.USER_UNBLOCKED,
                user_id=admin_id,
                ip=ip,
                details={TARGET_USER_KEY: account_id},
            )
        return _summary(session, account_id)


def change_email(
    session: Session, *, admin_id: int, account_id: int, new_email: str, ip: str | None
) -> EmailChange:
    """Troca o email da conta (pedido feito ao suporte) e devolve os avisos a agendar.

    `new_email` já normalizado (`normalize_email`). 404 se a conta não existe; 409
    `email_in_use` (field `new_email`) se o email já tem conta, inclusive se é o atual dela, sem
    mudar nada. Na troca, na mesma transação:

    - todas as sessões da conta são apagadas (ela entra de novo com o email novo);
    - os códigos ainda válidos do email antigo e os da conta (login e exclusão) vencem agora: um
      código mandado ao endereço antigo não serve mais para nada. As linhas ficam, porque os
      limites de envio contam as linhas de `login_codes`;
    - os convites pendentes recebidos continuam: são da conta (`invited_user_id`), não do email.

    Os avisos ("seu email foi trocado" ao antigo, "este é o novo email" ao novo) saem no idioma
    da conta, depois do commit.
    """
    with write_transaction(session):
        ensure_admin(session, admin_id)
        user = _target(session, account_id)
        if session.scalar(select(User.id).where(User.email == new_email)) is not None:
            raise ApiError(409, ErrorCode.EMAIL_IN_USE, field="new_email")
        old_email = user.email
        user.email = new_email
        sessions = _delete_sessions(session, account_id)
        now = utcnow()
        session.execute(
            update(LoginCode)
            .where(
                or_(LoginCode.email == old_email, LoginCode.user_id == account_id),
                LoginCode.used_at.is_(None),
                LoginCode.expires_at > now,
            )
            .values(expires_at=now),
            execution_options={"synchronize_session": False},
        )
        audit.record(
            session,
            AuditEvent.EMAIL_CHANGED,
            user_id=admin_id,
            ip=ip,
            details={
                TARGET_USER_KEY: account_id,
                "old_email": old_email,
                "new_email": new_email,
                "sessions": sessions,
            },
        )
        locale = pick_locale(user.locale)
        account = _summary(session, account_id)
    emails = (
        OutgoingEmail(old_email, locale, EmailChangedOld(new_email=new_email)),
        OutgoingEmail(new_email, locale, EmailChangedNew()),
    )
    return EmailChange(account, emails)
