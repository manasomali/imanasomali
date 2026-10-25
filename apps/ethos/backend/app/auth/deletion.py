"""Exclusão de conta (ETH-27): pelo próprio usuário, com código por email, e pelo admin (ETH-28).

Pelo usuário: `request_account_deletion` manda um código `delete_account` para o email atual
(mesmos limites, validade e tentativas do código de login, em `app/auth/service.py`) e
`delete_own_account` confere o código e apaga. Pelo admin: `delete_account`, sem código, a mesma
exclusão (`_delete`). Cada uma abre o próprio `write_transaction` (BEGIN IMMEDIATE) e faz dentro
dele as leituras que decidem: a conta (relida; 401 se sumiu ou foi bloqueada no meio, no fluxo do
próprio usuário) e o último admin. Ou apaga tudo ou nada.

O último admin ativo não pode ser apagado (409 `last_admin`), nem por ele mesmo nem por outro
admin: precisa sobrar uma conta com `is_admin` e `is_active` além dela. Admin bloqueado não conta,
porque não entra.

O que é apagado (ethos-plan.md, "exclusão de conta e dados"):

- a linha em `users` e, pelo `ON DELETE CASCADE`, as sessões, os códigos ligados à conta, as
  participações em hábitos de outras pessoas (`habit_members`), os convites recebidos pela conta
  (`invited_user_id`) e os alertas;
- os hábitos dos quais ela é dona, apagados antes da conta: o CASCADE leva as marcações (também
  as dos convidados), pausas, membros, convites enviados (só o dono convida), alertas e a
  auditoria desses hábitos;
- o que é ligado pelo email, sem chave estrangeira: os `login_codes` do email e os convites
  pendentes para o email (os feitos antes da conta existir, com `invited_user_id` vazio);
- a auditoria da própria conta (`ACCOUNT_EVENTS`): os eventos de auth, `terms_accepted`,
  `profile_updated`, `admin_created` e os `habit_deleted` dos hábitos que ela já tinha apagado.

O que fica, sem identificar a pessoa:

- as marcações dela em hábitos de outras pessoas: `marks.user_id` vira NULL pelo `SET NULL`;
- as outras linhas do `audit_log` com `user_id` dela (eventos em hábitos de outras pessoas e as
  ações dela como admin): `user_id` e `ip` viram NULL;
- nos eventos de hábitos de outras pessoas, os ids dela em `details` (`ACCOUNT_ID_KEYS`:
  `author_id` das marcações, `member_id` de remoção e troca de papel) viram `null`, porque o
  histórico (`app/history/service.py`) os mostra aos membros e a marcação já aparece como de
  "usuário removido";
- toda linha que sobra e cita a conta (pelo `user_id`, pelo email no `details` ou pelo
  `details.target_user_id` dos eventos de admin sobre ela, ETH-28) perde todo texto do `details`
  que contém "@", ou seja, qualquer email (ex.: o antigo e o novo do `email_changed`). O
  `target_user_id` numérico fica, como o id da conta no `account_deleted`;
- `banners.created_by` vira NULL pelo `SET NULL`.

Por fim, `account_deleted` com `user_id` = quem apagou (None quando foi a própria conta, cuja
linha já não existe) e `{"account_id": n, "by_admin": bool}`, sem email nem IP da pessoa. Depois
do commit, o log do serviço (journald) recebe só o id numérico da conta (`DELETED_LOG_FORMAT`): é
a lista para reaplicar as exclusões depois de restaurar um backup (`reapply_deletion`, chamada
pelo `python -m app.cli reapply-deletions`, em `app/auth/reapply.py`).

Os emails ("conta excluída" para a conta e "você perdeu acesso" para cada membro dos hábitos
apagados, um por membro com todos os hábitos) são lidos antes de apagar e devolvidos para quem
chama agendar depois do commit: uma exclusão que falhou não avisa ninguém.
"""

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, delete, func, null, or_, select, update
from sqlalchemy.orm import Session

from app import audit
from app.audit import AUTH_EVENTS, AuditEvent
from app.auth import service
from app.auth.service import CodeRequestResult, OutgoingEmail, VerifyFailure
from app.config import Settings
from app.db import require_write_transaction, write_transaction
from app.errors import ApiError, ErrorCode
from app.mail.catalog import AccessLost, AccountDeleted
from app.mail.language import pick_locale
from app.models import AuditLog, Habit, HabitInvite, HabitMember, LoginCode, User

logger = logging.getLogger(__name__)

# Eventos da própria conta, apagados com ela (os sem hábito; os dos hábitos dela vão no CASCADE)
ACCOUNT_EVENTS: frozenset[AuditEvent] = AUTH_EVENTS | {
    AuditEvent.TERMS_ACCEPTED,
    AuditEvent.PROFILE_UPDATED,
    AuditEvent.ADMIN_CREATED,
    # Só o dono apaga o hábito: são os hábitos dela apagados antes
    AuditEvent.HABIT_DELETED,
}
# Chaves do `details` com o id de uma conta nos eventos de hábito: viram null na exclusão
ACCOUNT_ID_KEYS = ("author_id", "member_id")
# Chave do `details` com a conta alvo de um evento de admin (ETH-28): o id fica, os emails saem
TARGET_USER_KEY = "target_user_id"
# Linha do log de cada exclusão, só com o id numérico. O `reapply-deletions` (app/auth/reapply.py)
# procura exatamente esta linha no journald: mudar o texto quebra a leitura das linhas antigas
DELETED_LOG_FORMAT = "conta %d excluída"


class Reapplied(StrEnum):
    """Resultado de `reapply_deletion` para uma conta."""

    DELETED = "deleted"
    # A conta não existe no banco: já foi apagada (ou o backup é de antes dela nascer)
    MISSING = "missing"
    # Último admin ativo: não foi apagada (o mesmo 409 `last_admin` da API)
    LAST_ADMIN = "last_admin"


@dataclass(frozen=True, slots=True)
class AccountDeletion:
    """Conta apagada e os emails a agendar depois do commit."""

    account_id: int
    emails: tuple[OutgoingEmail, ...]


def request_account_deletion(
    session: Session, settings: Settings, *, user_id: int, ip: str | None
) -> CodeRequestResult:
    """Manda o código de exclusão para o email atual da conta (202) ou recusa (429).

    Levanta 401 se a conta sumiu ou foi bloqueada e 409 `last_admin` se é o último admin.
    """
    with write_transaction(session):
        user = _active_user(session, user_id)
        _ensure_not_last_admin(session, user)
        return service.request_delete_code(session, settings, user=user, ip=ip)


def delete_own_account(
    session: Session, *, user_id: int, code: str
) -> AccountDeletion | VerifyFailure:
    """Confere o código e apaga a conta. Código recusado: `VerifyFailure.INVALID_CODE`.

    A tentativa fica gravada mesmo quando o código é recusado. Levanta 401 (conta sumiu ou foi
    bloqueada) e 409 `last_admin`. O `account_deleted` vai sem IP: seria dado da pessoa apagada.
    """
    with write_transaction(session):
        user = _active_user(session, user_id)
        _ensure_not_last_admin(session, user)
        if not service.use_delete_code(session, user=user, code=code):
            return VerifyFailure.INVALID_CODE
        emails = _delete(session, user, actor_id=None, ip=None)
    _log_deleted(user_id)
    return AccountDeletion(account_id=user_id, emails=emails)


def delete_account(
    session: Session, *, account_id: int, actor_id: int, ip: str | None
) -> AccountDeletion:
    """Apaga a conta `account_id` a pedido de `actor_id`, sem código (admin, ETH-28).

    Quem chama garante que `actor_id` é admin. Conta bloqueada também é apagada. Levanta 404
    `not_found` (conta não existe) e 409 `last_admin`. `actor_id == account_id` (o admin apagando
    a própria conta) é gravado como exclusão pela própria conta, sem IP.
    """
    by_self = actor_id == account_id
    with write_transaction(session):
        user = session.scalar(_user_query(account_id))
        if user is None:
            raise ApiError(404, ErrorCode.NOT_FOUND)
        _ensure_not_last_admin(session, user)
        emails = _delete(
            session, user, actor_id=None if by_self else actor_id, ip=None if by_self else ip
        )
    _log_deleted(account_id)
    return AccountDeletion(account_id=account_id, emails=emails)


def reapply_deletion(session: Session, *, account_id: int) -> Reapplied:
    """Apaga de novo, depois de restaurar um backup, uma conta que o log diz ter sido excluída.

    A mesma exclusão de `delete_account`, numa transação só, com três diferenças:

    - nenhum email: a pessoa e os membros dos hábitos dela já foram avisados na exclusão
      original. Os emails que `_delete` monta são descartados aqui, e nada é agendado;
    - `account_deleted` com `user_id` None e `{"account_id": n, "reapplied": true}`: o evento
      original foi gravado depois do backup e sumiu com o restore, e quem apagou não se sabe
      mais. Como os ids não se repetem (AUTOINCREMENT), uma conta que ainda existe no banco não
      tem `account_deleted`: este não duplica nada. Conta que não existe não grava nada;
    - nenhuma linha nova no log: a da exclusão original continua no journald.

    Idempotente: conta que não existe devolve `MISSING`. O último admin ativo não é apagado
    (`LAST_ADMIN`), como na API: depois de um restore, o admin que ficou pode ainda não ser admin
    no banco restaurado. Quem chama avisa; rodar de novo depois de um `create-admin` apaga.
    """
    with write_transaction(session):
        user = session.scalar(_user_query(account_id))
        if user is None:
            return Reapplied.MISSING
        if _is_last_admin(session, user):
            return Reapplied.LAST_ADMIN
        _delete(session, user, actor_id=None, ip=None, reapplied=True)
    return Reapplied.DELETED


def _user_query(user_id: int) -> Select[tuple[User]]:
    # populate_existing: relê a linha mesmo que a sessão já tenha o objeto (da dependência)
    return select(User).where(User.id == user_id).execution_options(populate_existing=True)


def _active_user(session: Session, user_id: int) -> User:
    """A conta relida dentro da transação; 401 se foi apagada ou bloqueada no meio."""
    user = session.scalar(_user_query(user_id))
    if user is None or not user.is_active:
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    return user


def _ensure_not_last_admin(session: Session, user: User) -> None:
    """409 `last_admin` se `user` é admin e nenhuma outra conta é admin ativa."""
    if _is_last_admin(session, user):
        raise ApiError(409, ErrorCode.LAST_ADMIN)


def _is_last_admin(session: Session, user: User) -> bool:
    if not user.is_admin:
        return False
    others = session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.is_admin.is_(True), User.is_active.is_(True), User.id != user.id)
    )
    return not others


def _log_deleted(account_id: int) -> None:
    # Só o id numérico: depois de restaurar um backup, estas linhas dizem o que apagar de novo
    logger.info(DELETED_LOG_FORMAT, account_id)


def _delete(
    session: Session,
    user: User,
    *,
    actor_id: int | None,
    ip: str | None,
    reapplied: bool = False,
) -> tuple[OutgoingEmail, ...]:
    """Apaga e anonimiza tudo da conta (ver o docstring do módulo) e devolve os emails.

    Exige `write_transaction`. `actor_id`: o admin que apagou, ou None (a própria conta).
    `reapplied`: exclusão reaplicada depois de um restore (`reapply_deletion`).
    """
    require_write_transaction(session)
    account_id, email = user.id, user.email
    # Lidos antes de apagar; saem depois do commit
    emails = (
        OutgoingEmail(email, pick_locale(user.locale), AccountDeleted()),
        *_access_lost(session, account_id),
    )
    _execute(session, delete(Habit).where(Habit.owner_id == account_id))
    _clean_audit(session, account_id, email)
    _execute(session, delete(LoginCode).where(LoginCode.email == email))
    _execute(session, delete(HabitInvite).where(HabitInvite.email == email))
    _execute(session, delete(User).where(User.id == account_id))
    session.expunge(user)
    details: dict[str, Any] = (
        {"account_id": account_id, "reapplied": True}
        if reapplied
        else {"account_id": account_id, "by_admin": actor_id is not None}
    )
    audit.record(session, AuditEvent.ACCOUNT_DELETED, user_id=actor_id, ip=ip, details=details)
    return emails


def _execute(session: Session, statement: Any) -> None:
    session.execute(statement, execution_options={"synchronize_session": False})


def _access_lost(session: Session, owner_id: int) -> tuple[OutgoingEmail, ...]:
    """Um aviso por membro dos hábitos do dono, com os nomes de todos os hábitos que ele perde."""
    rows = session.execute(
        select(User.id, User.email, User.locale, Habit.name)
        .join(HabitMember, HabitMember.user_id == User.id)
        .join(Habit, Habit.id == HabitMember.habit_id)
        .where(Habit.owner_id == owner_id)
        .order_by(User.id, Habit.id)
    ).all()
    members: dict[int, tuple[str, str, list[str]]] = {}
    for member_id, email, locale, habit_name in rows:
        members.setdefault(member_id, (email, locale, []))[2].append(habit_name)
    return tuple(
        OutgoingEmail(email, pick_locale(locale), AccessLost(habit_names=tuple(names)))
        for email, locale, names in members.values()
    )


def _clean_audit(session: Session, account_id: int, email: str) -> None:
    """Apaga a auditoria da conta e anonimiza a que fica.

    Roda antes de apagar a linha em `users`, cujo `SET NULL` levaria o `user_id` que diz quais
    linhas eram dela.
    """
    _execute(
        session,
        delete(AuditLog).where(
            AuditLog.user_id == account_id,
            AuditLog.event.in_([event.value for event in ACCOUNT_EVENTS]),
        ),
    )
    _scrub_emails(session, account_id, email)
    for key in ACCOUNT_ID_KEYS:
        path = f"$.{key}"
        _execute(
            session,
            update(AuditLog)
            .where(func.json_extract(AuditLog.details, path) == account_id)
            .values(details=func.json_set(AuditLog.details, path, null())),
        )
    _execute(
        session,
        update(AuditLog).where(AuditLog.user_id == account_id).values(user_id=None, ip=None),
    )


def _scrub_emails(session: Session, account_id: int, email: str) -> None:
    """Tira os emails do `details` das linhas que citam a conta e têm algum "@"."""
    # O email como fica no JSON gravado (ensure_ascii: caracteres fora do ASCII viram \uXXXX)
    needle = json.dumps(email)[1:-1]
    rows = session.execute(
        select(AuditLog.id, AuditLog.details).where(
            func.instr(AuditLog.details, "@") > 0,
            or_(
                AuditLog.user_id == account_id,
                func.instr(func.lower(AuditLog.details), needle) > 0,
                func.json_extract(AuditLog.details, f"$.{TARGET_USER_KEY}") == account_id,
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
