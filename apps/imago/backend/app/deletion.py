"""Exclusão de conta (ETH-61), pela própria pessoa (com código por email) e pelo admin (ETH-62).

Pela pessoa: `request_account_deletion` manda um código `delete_account` para o email atual (mesmos
limites, validade e tentativas do código de login, em `app/auth/service.py`) e `delete_own_account`
confere o código e começa a exclusão. Pelo admin, sem código: `app/admin/accounts.py` chama o
mesmo `start_deletion`. A conta apaga em todas as aplicações, em três passos (imago-plan.md,
"exclusão de conta"):

1. `start_deletion`, no `write_transaction` (BEGIN IMMEDIATE) de quem chama, com a conta relida
   nele: confere que ela não é o último admin ativo (409 `last_admin`), muda o status para
   `deleting`, apaga as sessões, os códigos e as tarefas `refresh` pendentes, cria uma tarefa
   `delete` para cada aplicação do `IMAGO_APPS` (`app/internal/tasks.py`) e grava
   `account_deletion_started` (quem pediu e como). Depois do commit, `log_started` grava no log só
   o id da conta (`DELETED_LOG_FORMAT`): é a lista que o `reapply-deletions` lê depois de um
   restore. Daí em diante a pessoa não entra, não recebe código e o email dela não cria conta nova;
2. `continue_deletion`, em `BackgroundTasks` depois da resposta: as tarefas `delete` chamam
   `POST /internal/users/{id}/delete` em cada aplicação, que apaga na própria transação, com as
   regras dela. O que falhar fica para o `run-tasks` (de hora em hora);
3. `finish_deletion`, quando não sobra tarefa `delete` pendente (logo depois do passo 2 ou no
   `run-tasks`, `finish_ready_deletions`), numa transação BEGIN IMMEDIATE que confere se a linha
   ainda existe: assim ele roda uma vez só, mesmo com a request e o `run-tasks` terminando a última
   tarefa ao mesmo tempo. Lê o email, apaga a auditoria da própria conta (`ACCOUNT_EVENTS`: auth,
   termos, perfil e `admin_created`) e os `account_deletion_started` dela, tira o IP e os emails das
   linhas que citam a conta (pelo `user_id`, pelo email no `details` ou pelo
   `details.target_user_id` das ações do admin sobre ela, como a troca de email), apaga os códigos
   dos emails que foram dela, apaga a linha em `users` (o CASCADE leva sessões, códigos e
   tarefas) e grava `account_deleted` com o id e quem apagou, sem email nem IP. Depois do commit,
   o "conta excluída" vai para o email lido, pelo teto de envio (`account_emails`: recusado pelo
   teto, avisa o suporte).

Quem apagou e se o email sai ficam no `account_deletion_started` (o passo 3 pode rodar horas
depois, noutro processo): `{"by_admin": false}` com `user_id` = a conta (a própria pessoa, ou o
admin apagando a própria conta pelo painel), `{"by_admin": true}` com `user_id` = o admin, ou
`{"reapplied": true}` (o `reapply-deletions`, sem email). O `account_deleted` copia isso: `user_id`
= o admin, ou None.

O último admin ativo (admin, não bloqueado e fora de exclusão, sem outro igual) não pode ser
apagado, nem por ele mesmo nem por outro admin. Admin bloqueado não conta, porque não entra.
"""

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app import audit
from app.audit import AUTH_EVENTS, AuditEvent
from app.auth import service
from app.auth.service import CodeRequestResult, VerifyFailure, account_emails
from app.config import Settings
from app.db import require_write_transaction, write_transaction
from app.errors import ApiError, ErrorCode
from app.internal.tasks import TaskContext, cancel_tasks, request_tasks, run_pending
from app.mail.catalog import AccountDeleted
from app.mail.language import pick_locale
from app.mail.sender import Mailer, OutgoingEmail
from app.models import AppTask, AuditLog, LoginCode, TaskAction, User, UserSession, UserStatus

logger = logging.getLogger(__name__)

# Linha do log do passo 1, só com o id numérico. O `reapply-deletions` (app/reapply.py) procura
# exatamente esta linha no journald: mudar o texto quebra a leitura das linhas antigas. Nenhuma
# outra linha deste logger pode começar com "conta "
DELETED_LOG_FORMAT = "conta %d excluída"
# Chave do `details` com a conta alvo de um evento (ações do admin e o passo 1 da exclusão)
TARGET_USER_KEY = "target_user_id"
# Eventos da própria conta, apagados com ela. O `account_deletion_started` sai pela conta alvo
# (`target_user_id`), não pelo autor: o de um admin que apagou outra conta continua valendo para o
# passo 3 dela, mesmo que o admin seja apagado antes
ACCOUNT_EVENTS: frozenset[AuditEvent] = AUTH_EVENTS | {
    AuditEvent.TERMS_ACCEPTED,
    AuditEvent.PROFILE_UPDATED,
    AuditEvent.ADMIN_CREATED,
}
# Chaves do `email_changed` com os emails que a conta teve
_EMAIL_KEYS = ("old_email", "new_email")


class DeletionMode(StrEnum):
    """Quem pediu a exclusão: decide o `account_deleted` e se o "conta excluída" sai."""

    # A própria pessoa (DELETE /me), ou o admin apagando a própria conta pelo painel
    SELF = "self"
    # O admin, pela conta de outra pessoa (DELETE /admin/users/{id})
    ADMIN = "admin"
    # O reapply-deletions, depois de um restore: sem email
    REAPPLIED = "reapplied"


@dataclass(frozen=True, slots=True)
class FinishedDeletion:
    """Conta apagada no passo 3 e os emails a mandar depois do commit."""

    account_id: int
    mode: DeletionMode
    emails: tuple[OutgoingEmail, ...]


# --- regras ---


def is_last_admin(session: Session, user: User) -> bool:
    """Diz se `user` é o último admin ativo (admin, não bloqueado e fora de exclusão)."""
    if not (user.is_admin and service.can_sign_in(user)):
        return False
    others = session.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.is_admin.is_(True),
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE.value,
            User.id != user.id,
        )
    )
    return not others


def ensure_not_last_admin(session: Session, user: User) -> None:
    """409 `last_admin` se `user` é o último admin ativo."""
    if is_last_admin(session, user):
        raise ApiError(409, ErrorCode.LAST_ADMIN)


def reload_user(session: Session, user_id: int) -> User | None:
    """A conta relida do banco (mesmo que a sessão já tenha o objeto), ou None."""
    return session.scalar(_user_query(user_id))


def _user_query(user_id: int) -> Select[tuple[User]]:
    return select(User).where(User.id == user_id).execution_options(populate_existing=True)


def _signed_in_user(session: Session, user_id: int) -> User:
    """A conta relida na transação; 401 se foi apagada, bloqueada ou entrou em exclusão no meio."""
    user = reload_user(session, user_id)
    if user is None or not service.can_sign_in(user):
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    return user


def _execute(session: Session, statement: Any) -> int:
    return session.execute(statement, execution_options={"synchronize_session": False}).rowcount


# --- pela própria pessoa ---


def request_account_deletion(
    session: Session, settings: Settings, *, user_id: int, ip: str | None
) -> CodeRequestResult:
    """Manda o código de exclusão para o email atual da conta (202) ou recusa (429).

    Levanta 401 se a conta sumiu, foi bloqueada ou já está em exclusão, e 409 `last_admin`.
    """
    with write_transaction(session):
        user = _signed_in_user(session, user_id)
        ensure_not_last_admin(session, user)
        return service.request_delete_code(session, settings, user=user, ip=ip)


def delete_own_account(
    session: Session, settings: Settings, *, user_id: int, code: str
) -> VerifyFailure | None:
    """Confere o código e faz o passo 1 da exclusão. None: começou; senão o código foi recusado.

    A tentativa fica gravada mesmo quando o código é recusado. Levanta 401 (conta sumiu, foi
    bloqueada ou já está em exclusão) e 409 `last_admin`. Quem chama agenda `continue_deletion`.
    """
    with write_transaction(session):
        user = _signed_in_user(session, user_id)
        ensure_not_last_admin(session, user)
        if not service.use_delete_code(session, user=user, code=code):
            return VerifyFailure.INVALID_CODE
        start_deletion(session, settings, user, actor_id=user_id, mode=DeletionMode.SELF)
    log_started(user_id)
    return None


# --- passo 1 ---


def start_deletion(
    session: Session,
    settings: Settings,
    user: User,
    *,
    actor_id: int | None,
    mode: DeletionMode,
    ip: str | None = None,
) -> None:
    """Passo 1 (ver o docstring do módulo). Exige `write_transaction`, com `user` relido nela.

    `actor_id`: quem pediu (a própria conta, o admin, ou None no reapply-deletions); `ip`: o do
    admin (o da própria pessoa não é gravado: seria dado dela). Levanta 409 `last_admin`.
    Depois do commit, quem chama grava `log_started` (menos o reapply-deletions).
    """
    require_write_transaction(session)
    ensure_not_last_admin(session, user)
    account_id = user.id
    user.status = UserStatus.DELETING.value
    _execute(session, delete(UserSession).where(UserSession.user_id == account_id))
    _execute(
        session,
        delete(LoginCode).where(
            or_(LoginCode.user_id == account_id, LoginCode.email == user.email)
        ),
    )
    cancel_tasks(session, user_id=account_id, action=TaskAction.REFRESH)
    request_tasks(session, settings, user_id=account_id, action=TaskAction.DELETE)
    record_started(session, account_id, actor_id=actor_id, mode=mode, ip=ip)


def record_started(
    session: Session,
    account_id: int,
    *,
    actor_id: int | None,
    mode: DeletionMode,
    ip: str | None = None,
) -> None:
    """Grava o `account_deletion_started`, que diz ao passo 3 quem apagou e se manda o email."""
    details: dict[str, Any] = {TARGET_USER_KEY: account_id}
    if mode is DeletionMode.REAPPLIED:
        details["reapplied"] = True
    else:
        details["by_admin"] = mode is DeletionMode.ADMIN
    audit.record(
        session, AuditEvent.ACCOUNT_DELETION_STARTED, user_id=actor_id, ip=ip, details=details
    )


def log_started(account_id: int) -> None:
    # Só o id numérico: depois de restaurar um backup, estas linhas dizem o que apagar de novo
    logger.info(DELETED_LOG_FORMAT, account_id)


# --- passo 2 ---


def continue_deletion(context: TaskContext, mailer: Mailer, account_id: int) -> None:
    """Passos 2 e 3 de uma conta, para `BackgroundTasks`: nunca levanta.

    Chama o `delete` de cada aplicação (tarefas pendentes) e, se nenhuma ficou pendente, termina
    a exclusão e manda os emails. Um erro inesperado vira uma linha de log; o `run-tasks` continua
    de onde parou.
    """
    try:
        run_pending(context, user_id=account_id, action=TaskAction.DELETE)
        finish_and_notify(context, mailer, account_id)
    except Exception as exc:
        logger.error(
            "a exclusão da conta %d não continuou (%s); fica para o run-tasks",
            account_id,
            type(exc).__name__,
        )


def finish_and_notify(context: TaskContext, mailer: Mailer, account_id: int) -> bool:
    """Passo 3 da conta e, depois do commit, os emails. True se a exclusão terminou agora."""
    with context.session_factory() as session:
        finished = finish_deletion(session, context.settings, account_id)
    if finished is None:
        return False
    for outgoing in finished.emails:
        mailer.send(outgoing)
    return True


def finish_ready_deletions(context: TaskContext, mailer: Mailer) -> int:
    """Passo 3 de cada conta em exclusão sem tarefa `delete` pendente (`run-tasks`).

    Devolve quantas exclusões terminaram. Pega também as que não terminaram na request (o serviço
    reiniciou no meio, ou o `IMAGO_APPS` estava vazio e o passo 2 não rodou).
    """
    pending = exists().where(
        AppTask.user_id == User.id,
        AppTask.action == TaskAction.DELETE.value,
        AppTask.done_at.is_(None),
    )
    with context.session_factory() as session:
        account_ids = list(
            session.scalars(
                select(User.id)
                .where(User.status == UserStatus.DELETING.value, ~pending)
                .order_by(User.id)
            )
        )
    return sum(finish_and_notify(context, mailer, account_id) for account_id in account_ids)


# --- passo 3 ---


def finish_deletion(
    session: Session, settings: Settings, account_id: int
) -> FinishedDeletion | None:
    """Passo 3 (ver o docstring do módulo). None se não há o que fazer: a conta não existe (outra
    execução já terminou), não está em exclusão ou ainda tem tarefa `delete` pendente."""
    with write_transaction(session):
        user = reload_user(session, account_id)
        if user is None or user.status != UserStatus.DELETING.value:
            return None
        if session.scalar(
            select(func.count())
            .select_from(AppTask)
            .where(
                AppTask.user_id == account_id,
                AppTask.action == TaskAction.DELETE.value,
                AppTask.done_at.is_(None),
            )
        ):
            return None
        mode, actor_id = _who_deleted(session, account_id)
        email, locale = user.email, user.locale
        emails = _emails_of(session, account_id, email)
        _clean_audit(session, account_id, email)
        _delete_codes(session, account_id, emails)
        _execute(session, delete(User).where(User.id == account_id))
        session.expunge(user)
        details: dict[str, Any] = {"account_id": account_id}
        if mode is DeletionMode.REAPPLIED:
            details["reapplied"] = True
        else:
            details["by_admin"] = mode is DeletionMode.ADMIN
        audit.record(session, AuditEvent.ACCOUNT_DELETED, user_id=actor_id, details=details)
        outgoing: tuple[OutgoingEmail, ...] = ()
        if mode is not DeletionMode.REAPPLIED:
            outgoing = account_emails(
                session, settings, [OutgoingEmail(email, pick_locale(locale), AccountDeleted())]
            )
    logger.info("exclusão da conta %d concluída", account_id)
    return FinishedDeletion(account_id=account_id, mode=mode, emails=outgoing)


def _target_is(account_id: int) -> Any:
    return func.json_extract(AuditLog.details, f"$.{TARGET_USER_KEY}") == account_id


def _who_deleted(session: Session, account_id: int) -> tuple[DeletionMode, int | None]:
    """Como a exclusão começou e quem apagou, pelo último `account_deletion_started`.

    Sem o evento (não acontece pelo app), vale como pela própria pessoa.
    """
    started = session.scalar(
        select(AuditLog)
        .where(AuditLog.event == AuditEvent.ACCOUNT_DELETION_STARTED.value, _target_is(account_id))
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    if started is None:
        return DeletionMode.SELF, None
    if started.details.get("reapplied"):
        return DeletionMode.REAPPLIED, None
    if started.details.get("by_admin"):
        # user_id None: o admin que apagou foi apagado depois (SET NULL)
        return DeletionMode.ADMIN, started.user_id
    return DeletionMode.SELF, None


def _emails_of(session: Session, account_id: int, email: str) -> set[str]:
    """O email atual e os que a conta teve antes (troca de email pelo admin)."""
    emails = {email}
    changes = session.scalars(
        select(AuditLog.details).where(
            AuditLog.event == AuditEvent.EMAIL_CHANGED.value, _target_is(account_id)
        )
    )
    for details in changes:
        for key in _EMAIL_KEYS:
            # Já None se a auditoria foi anonimizada antes (o admin que trocou foi apagado)
            value = details.get(key)
            if isinstance(value, str):
                emails.add(value)
    return emails


def _delete_codes(session: Session, account_id: int, emails: set[str]) -> None:
    """Apaga os códigos da conta e dos emails que foram dela.

    Um email antigo que já é de outra conta fica de fora: os códigos dele podem ser da outra
    pessoa (e somem em até 1 dia, pela retenção).
    """
    taken = set(
        session.scalars(select(User.email).where(User.email.in_(emails), User.id != account_id))
    )
    _execute(
        session,
        delete(LoginCode).where(
            or_(LoginCode.user_id == account_id, LoginCode.email.in_(emails - taken))
        ),
    )


def _clean_audit(session: Session, account_id: int, email: str) -> None:
    """Apaga a auditoria da conta e anonimiza a que fica.

    Roda antes de apagar a linha em `users`, cujo `SET NULL` levaria o `user_id` que diz quais
    linhas eram dela.
    """
    _execute(
        session,
        delete(AuditLog).where(
            or_(
                and_(
                    AuditLog.user_id == account_id,
                    AuditLog.event.in_([event.value for event in ACCOUNT_EVENTS]),
                ),
                and_(
                    AuditLog.event == AuditEvent.ACCOUNT_DELETION_STARTED.value,
                    _target_is(account_id),
                ),
            )
        ),
    )
    _scrub_emails(session, account_id, email)
    _execute(
        session,
        update(AuditLog)
        .where(or_(AuditLog.user_id == account_id, _target_is(account_id)))
        .values(ip=None),
    )
    _execute(session, update(AuditLog).where(AuditLog.user_id == account_id).values(user_id=None))


def _scrub_emails(session: Session, account_id: int, email: str) -> None:
    """Tira os emails do `details` das linhas que citam a conta e têm algum "@"."""
    # O email como fica no JSON gravado (ensure_ascii; os emails do imago já são ASCII)
    needle = json.dumps(email)[1:-1]
    rows = session.execute(
        select(AuditLog.id, AuditLog.details).where(
            func.instr(AuditLog.details, "@") > 0,
            or_(
                AuditLog.user_id == account_id,
                func.instr(func.lower(AuditLog.details), needle) > 0,
                _target_is(account_id),
            ),
        )
    ).all()
    if rows:
        # UPDATE por chave primária, em lote
        session.execute(
            update(AuditLog),
            [{"id": row_id, "details": without_emails(details)} for row_id, details in rows],
        )


def without_emails(value: Any) -> Any:
    """Cópia de um valor JSON com todo texto que contém "@" trocado por None."""
    if isinstance(value, dict):
        return {key: without_emails(item) for key, item in value.items()}
    if isinstance(value, list):
        return [without_emails(item) for item in value]
    if isinstance(value, str) and "@" in value:
        return None
    return value
