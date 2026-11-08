"""Contas no painel do admin (ETH-62): listar, bloquear, desbloquear, trocar o email, excluir e os
envios de email das últimas 24 h.

Quem chama (as rotas) garante que quem pede é admin (`AdminUser`). Cada escrita abre o próprio
`write_transaction` (BEGIN IMMEDIATE) e confere de novo, dentro dele, que quem age continua admin
ativo (`ensure_admin`): dois admins que se bloqueiam ao mesmo tempo não deixam o serviço sem
nenhum, porque o segundo já não passa (401). Com isso e com o admin não podendo bloquear a si
mesmo (409 `cannot_block_self`), bloquear nunca tira o último admin ativo: quem bloqueia continua
sendo um. Bloquear outro admin é permitido. A exclusão é a de `app/deletion.py` (último admin
ativo: 409 `last_admin`).

Conta em exclusão (`status=deleting`) aparece na listagem, mas não é bloqueada, desbloqueada nem
tem o email trocado (404 `not_found`, como uma conta que já não existe): ela está saindo de todas as
aplicações. Excluir de novo uma conta em exclusão não grava nada e só tenta de novo as aplicações
que faltam.

Auditoria (todo evento sobre outra conta leva o id dela em `details.target_user_id`, que é como a
exclusão da conta acha a linha e tira o IP e os emails; ver `app/audit.py`); `user_id` é o admin:

- `user_blocked`: `{target_user_id, sessions}` (sessões apagadas); `user_unblocked`:
  `{target_user_id}`. Bloquear quem já está bloqueado (ou desbloquear quem está ativo) não muda
  nada e não grava;
- `email_changed`: `{target_user_id, old_email, new_email, sessions}`;
- excluir: o `account_deletion_started` do passo 1 (`app/deletion.py`) e, no fim, o
  `account_deleted` com o admin.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app import audit, deletion
from app.audit import AuditEvent
from app.auth.service import account_emails
from app.config import IMAGO_APP_NAME, Settings
from app.db import require_write_transaction, write_transaction
from app.deletion import TARGET_USER_KEY, DeletionMode
from app.errors import ApiError, ErrorCode
from app.internal.tasks import request_tasks
from app.mail import quota
from app.mail.catalog import EmailChangedNew, EmailChangedOld
from app.mail.kinds import MailKind
from app.mail.language import pick_locale
from app.mail.sender import OutgoingEmail
from app.models import (
    MAX_ACCOUNT_ID,
    LoginCode,
    MailLog,
    TaskAction,
    User,
    UserSession,
    UserStatus,
    utcnow,
)

# Paginação da listagem: padrão e máximo por página
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
# Janela dos envios de email no painel (a maior janela do teto)
MAIL_WINDOW = timedelta(hours=24)


class AccountStatus(StrEnum):
    """Filtro `status` da listagem."""

    # Entra e recebe código
    ACTIVE = "active"
    # `is_active` desligado pelo admin: não recebe código nem entra; os dados ficam
    BLOCKED = "blocked"
    # Exclusão em andamento
    DELETING = "deleting"


@dataclass(frozen=True, slots=True)
class AccountPage:
    users: list[User]
    # Cursor da próxima página; None na última
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class EmailChange:
    """Conta com o email novo e os avisos a mandar depois do commit (antigo e novo)."""

    user: User
    emails: tuple[OutgoingEmail, ...]


# --- cursor ---

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)
_CURSOR_RE = re.compile(r"(-?[0-9]{1,18})\.([1-9][0-9]{0,15})")


def encode_cursor(instant: datetime, account_id: int) -> str:
    """Cursor opaco da conta com esse `created_at` e esse id: `<microssegundos>.<id>`."""
    return f"{(instant - _EPOCH) // _MICROSECOND}.{account_id}"


def decode_cursor(value: str) -> tuple[datetime, int]:
    """Instante (UTC) e id do cursor; cursor inválido dá 422 `validation_error` em `cursor`."""
    match = _CURSOR_RE.fullmatch(value)
    if match is None or int(match[2]) > MAX_ACCOUNT_ID:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, field="cursor")
    try:
        instant = _EPOCH + int(match[1]) * _MICROSECOND
    except OverflowError:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, field="cursor") from None
    return instant, int(match[2])


# --- leitura ---


def _status_condition(status: AccountStatus) -> Any:
    if status is AccountStatus.DELETING:
        return User.status == UserStatus.DELETING.value
    return and_(
        User.status == UserStatus.ACTIVE.value,
        User.is_active.is_(status is AccountStatus.ACTIVE),
    )


def list_accounts(
    session: Session,
    *,
    email: str | None,
    status: AccountStatus | None,
    cursor: str | None,
    limit: int,
) -> AccountPage:
    """Uma página das contas, das mais novas para as mais antigas (`created_at`, id).

    `email`: trecho do email (espaços nas pontas e maiúsculas não importam); `status`: o da
    conta. `limit`: 1 a `MAX_PAGE_SIZE` (a rota confere). Cursor inválido: 422 `cursor`. Paginação
    por chave, sem OFFSET: contas novas entre uma página e outra não empurram nem repetem nada.
    """
    conditions: list[Any] = []
    term = (email or "").strip().lower()
    if term:
        # instr e não LIKE: `%` e `_` no trecho são letras, não curingas
        conditions.append(func.instr(User.email, term) > 0)
    if status is not None:
        conditions.append(_status_condition(status))
    if cursor is not None:
        after_at, after_id = decode_cursor(cursor)
        conditions.append(
            or_(
                User.created_at < after_at,
                and_(User.created_at == after_at, User.id < after_id),
            )
        )
    users = list(
        session.scalars(
            select(User)
            .where(*conditions)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(limit + 1)
            # Relê as contas mesmo que a sessão já tenha os objetos (ex.: o admin)
            .execution_options(populate_existing=True)
        )
    )
    next_cursor = None
    if len(users) > limit:
        users = users[:limit]
        next_cursor = encode_cursor(users[-1].created_at, users[-1].id)
    return AccountPage(users, next_cursor)


@dataclass(frozen=True, slots=True)
class AppMail:
    app: str
    code: int
    account: int
    notification: int


@dataclass(frozen=True, slots=True)
class MailWindow:
    sent: int
    # Teto de códigos e emails de conta; notificações param antes, em `notification_limit`
    limit: int
    notification_limit: int


@dataclass(frozen=True, slots=True)
class MailStats:
    window_hours: int
    by_app: list[AppMail]
    day: MailWindow
    hour: MailWindow


def mail_stats(session: Session, settings: Settings) -> MailStats:
    """Envios das últimas 24 h por aplicação e tipo, e as duas janelas do teto (`quota.py`).

    O imago e as aplicações do `IMAGO_APPS` aparecem sempre (com zero, se não mandaram nada), nessa
    ordem; uma aplicação que saiu do `IMAGO_APPS` e ainda tem envios na janela vem depois.
    """
    now = utcnow()
    rows = session.execute(
        select(MailLog.app, MailLog.kind, func.count())
        .where(MailLog.created_at > now - MAIL_WINDOW)
        .group_by(MailLog.app, MailLog.kind)
    ).all()
    counts = {(app, kind): total for app, kind, total in rows}
    names = [IMAGO_APP_NAME, *settings.app_names]
    names += sorted({app for app, _ in counts} - set(names))
    by_app = [
        AppMail(
            app=name,
            code=counts.get((name, MailKind.CODE.value), 0),
            account=counts.get((name, MailKind.ACCOUNT.value), 0),
            notification=counts.get((name, MailKind.NOTIFICATION.value), 0),
        )
        for name in names
    ]
    caps = dict(quota.limits(settings, MailKind.CODE))
    notification_caps = dict(quota.limits(settings, MailKind.NOTIFICATION))
    day, hour = (
        MailWindow(
            sent=quota.sent_in(session, window, now),
            limit=caps[window],
            notification_limit=notification_caps[window],
        )
        for window in ("day", "hour")
    )
    return MailStats(
        window_hours=MAIL_WINDOW // timedelta(hours=1), by_app=by_app, day=day, hour=hour
    )


# --- escrita ---


def ensure_admin(session: Session, admin_id: int) -> None:
    """Confere, dentro do `write_transaction`, que `admin_id` continua admin ativo.

    401 `unauthorized` se a conta sumiu, foi bloqueada ou entrou em exclusão no meio (como a
    dependência de sessão); 403 `forbidden` se perdeu o admin.
    """
    require_write_transaction(session)
    row = session.execute(
        select(User.is_active, User.is_admin, User.status).where(User.id == admin_id)
    ).one_or_none()
    if row is None or not row.is_active or row.status != UserStatus.ACTIVE.value:
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    if not row.is_admin:
        raise ApiError(403, ErrorCode.FORBIDDEN)


def _not_found() -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND)


def _target(session: Session, account_id: int) -> User:
    """A conta alvo, relida na transação; 404 se não existe ou está em exclusão."""
    user = deletion.reload_user(session, account_id)
    if user is None or user.status != UserStatus.ACTIVE.value:
        raise _not_found()
    return user


def _delete_sessions(session: Session, account_id: int) -> int:
    result = session.execute(
        delete(UserSession).where(UserSession.user_id == account_id),
        execution_options={"synchronize_session": False},
    )
    return result.rowcount


def set_active(
    session: Session, *, admin_id: int, account_id: int, is_active: bool, ip: str | None
) -> User:
    """Bloqueia (`is_active` falso, apaga as sessões da conta) ou desbloqueia a conta.

    O bloqueado não recebe código nem entra; os dados ficam. 409 `cannot_block_self` para a
    própria conta; 404 se não existe ou está em exclusão. Sem mudança: nada é gravado.
    """
    if not is_active and account_id == admin_id:
        raise ApiError(409, ErrorCode.CANNOT_BLOCK_SELF)
    with write_transaction(session):
        ensure_admin(session, admin_id)
        user = _target(session, account_id)
        if user.is_active != is_active:
            user.is_active = is_active
            if is_active:
                event, details = AuditEvent.USER_UNBLOCKED, {TARGET_USER_KEY: account_id}
            else:
                sessions = _delete_sessions(session, account_id)
                event = AuditEvent.USER_BLOCKED
                details = {TARGET_USER_KEY: account_id, "sessions": sessions}
            audit.record(session, event, user_id=admin_id, ip=ip, details=details)
    return user


def change_email(
    session: Session,
    settings: Settings,
    *,
    admin_id: int,
    account_id: int,
    new_email: str,
    ip: str | None,
) -> EmailChange:
    """Troca o email da conta (pedido feito ao suporte) e devolve os avisos a mandar.

    `new_email` já normalizado (como no login). 404 se a conta não existe ou está em exclusão;
    409 `email_in_use` (field `new_email`) se o email já tem conta, inclusive se é o atual dela,
    sem mudar nada. Na troca, na mesma transação:

    - todas as sessões da conta são apagadas (ela entra de novo com o email novo);
    - os códigos ainda válidos do email antigo e os da conta vencem agora: um código mandado ao
      endereço antigo não serve mais para nada. As linhas ficam, porque os limites de envio
      contam as linhas de `login_codes`;
    - uma tarefa `refresh` para cada aplicação, que guarda o email em `app_users`;
    - os avisos ("seu email foi trocado" ao antigo, "este é o novo email" ao novo), no idioma da
      conta, reservam o lugar no teto de envio (recusados pelo teto, avisam o suporte).
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
        request_tasks(session, settings, user_id=account_id, action=TaskAction.REFRESH)
        locale = pick_locale(user.locale)
        emails = account_emails(
            session,
            settings,
            [
                OutgoingEmail(old_email, locale, EmailChangedOld(new_email=new_email)),
                OutgoingEmail(new_email, locale, EmailChangedNew()),
            ],
        )
    return EmailChange(user, emails)


def delete_account(
    session: Session, settings: Settings, *, admin_id: int, account_id: int, ip: str | None
) -> bool:
    """Passo 1 da exclusão da conta pelo admin (`app/deletion.py`), sem código.

    Devolve True se a exclusão começou agora e False se a conta já estava em exclusão (nada é
    gravado; quem chama tenta de novo as aplicações que faltam). Conta bloqueada também é apagada.
    404 se a conta não existe; 409 `last_admin`. O admin apagando a própria conta pelo painel conta
    como exclusão pela própria pessoa (sem IP).
    """
    by_self = account_id == admin_id
    with write_transaction(session):
        ensure_admin(session, admin_id)
        user = deletion.reload_user(session, account_id)
        if user is None:
            raise _not_found()
        if user.status == UserStatus.DELETING.value:
            return False
        deletion.start_deletion(
            session,
            settings,
            user,
            actor_id=admin_id,
            mode=DeletionMode.SELF if by_self else DeletionMode.ADMIN,
            ip=None if by_self else ip,
        )
    deletion.log_started(account_id)
    return True
