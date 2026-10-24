"""Regras do compartilhamento (ETH-24): convidar, cancelar, aceitar, recusar, sair, trocar papel e
remover membro (ethos-plan.md, "compartilhamento").

Cada escrita abre o próprio `write_transaction` (BEGIN IMMEDIATE) e faz dentro dele as leituras
que decidem a escrita (acesso, limites, convite, membro): duas requests em paralelo no limite
não passam dele, porque a segunda espera a trava da primeira e conta de novo. Erros de regra
saem como `ApiError` e desfazem a transação.

Convidar (só o dono; hábito arquivado, que é só leitura, dá 409 `habit_archived`):

- A resposta é sempre a mesma ("convite enviado"), com ou sem conta para o email, a si mesmo, a
  quem já é membro ou a quem já tem convite pendente. Os ramos de email com e sem conta fazem as
  mesmas consultas e as mesmas escritas (o convite e o `invite_created`); o email ao convidado
  sai depois da resposta (`BackgroundTasks`), então não pesa no tempo dela.
- Email sem conta: o convite fica pendente para sempre, com `invited_user_id` vazio, e nunca é
  entregue. O convite só aparece para quem tinha a conta no momento do convite: a conta criada
  depois com o mesmo email não o vê nem o aceita.
- A si mesmo, a quem já é membro e a quem já tem convite pendente no hábito: nada muda (nem
  evento, nem email, nem conta no limite). Para mudar o papel de um convite pendente, o dono o
  cancela e convida de novo.
- Limites, conferidos antes de tudo (a mesma resposta para qualquer email):
  `MAX_INVITES_PER_DAY` por dono, somando todos os hábitos, nas últimas 24 h (409
  `invite_limit_reached`; contagem em `app/sharing/quota.py`) e `MAX_GUESTS_PER_HABIT`, membros +
  convites pendentes do hábito (409 `guest_limit_reached`).
- Conta bloqueada (`is_active` falso) recebe o convite pendente, mas não o email.

Aceitar e recusar: só o convidado (`invited_user_id`); convite de outra pessoa, sem conta ou que
não existe dá 404 `not_found` (igual nos três, sem revelar nada). Aceitar respeita
`MAX_SHARED_HABITS_PER_USER`, hábitos de outras pessoas dos quais o usuário participa, de qualquer
status (409 `shared_habit_limit_reached`, e o convite continua pendente). O hábito compartilhado
conta só no limite do dono (`count_owned_habits` só olha `habits.owner_id`). Aceitar, recusar e
cancelar apagam a linha do convite.

Sair (o convidado) e remover (o dono): a linha de `habit_members` sai junto com os alertas da
pessoa naquele hábito; as marcações dela ficam. O dono não sai do próprio hábito (403
`forbidden`: ele apaga o hábito). Trocar papel (só o dono): de editor para viewer apaga os
alertas da pessoa no hábito, na mesma transação (viewer não tem alertas). Pedir o papel atual
não muda nada nem grava evento.

Em hábito arquivado, só convidar é recusado: cancelar, aceitar, recusar, sair, remover e trocar
papel continuam (mexem no acesso, não no conteúdo do hábito).

Auditoria (sempre com `habit_id`, para o histórico do hábito; sem email no `details`, que
revelaria ao histórico se o email tem conta e teria de ser apagado na exclusão de conta):

- `invite_created` (`user_id` = dono): `{"invite_id", "role"}`;
- `invite_canceled` (dono): `{"invite_id", "role"}`;
- `invite_accepted` e `invite_declined` (`user_id` = convidado): `{"invite_id", "role"}`;
- `member_left` (quem saiu): `{"role"}`;
- `member_removed` (dono): `{"member_id", "role"}`;
- `member_role_changed` (dono): `{"member_id", "changes": [{"field": "role", "old", "new"}]}`.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.config import Settings
from app.db import write_transaction
from app.errors import ApiError, ErrorCode
from app.habits.access import (
    HabitAccess,
    HabitRole,
    get_habit_access,
    require_owner,
    require_writable,
    role_of,
)
from app.mail.language import Locale, pick_locale
from app.models import Alert, Habit, HabitInvite, HabitMember, MemberRole, User, utcnow
from app.sharing.quota import count_recent_invites


def _not_found() -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND)


@dataclass(frozen=True, slots=True)
class InviteDelivery:
    """Email de convite a mandar depois do commit (só para quem tem conta ativa)."""

    to: str
    locale: Locale
    habit_name: str
    role: MemberRole


@dataclass(frozen=True, slots=True)
class MemberEntry:
    """Uma pessoa com acesso ao hábito: o dono (com `joined_at` = criação do hábito) ou membro."""

    user_id: int
    email: str
    role: HabitRole
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class ReceivedInvite:
    """Convite pendente recebido, com o que o convidado precisa para decidir."""

    invite: HabitInvite
    habit_name: str
    habit_color: str
    owner_id: int
    owner_email: str


def count_guests(session: Session, habit_id: int) -> int:
    """Convidados do hábito que contam no `MAX_GUESTS_PER_HABIT`: membros + convites pendentes."""
    members = session.scalar(
        select(func.count()).select_from(HabitMember).where(HabitMember.habit_id == habit_id)
    )
    pending = session.scalar(
        select(func.count()).select_from(HabitInvite).where(HabitInvite.habit_id == habit_id)
    )
    return members + pending


def count_shared_habits(session: Session, user_id: int) -> int:
    """Hábitos de outras pessoas dos quais o usuário participa (`MAX_SHARED_HABITS_PER_USER`)."""
    return session.scalar(
        select(func.count()).select_from(HabitMember).where(HabitMember.user_id == user_id)
    )


def _delete_alerts(session: Session, habit_id: int, user_id: int) -> None:
    session.execute(
        delete(Alert).where(Alert.habit_id == habit_id, Alert.user_id == user_id),
        execution_options={"synchronize_session": False},
    )


def invite(
    session: Session,
    settings: Settings,
    *,
    owner_id: int,
    habit_id: int,
    email: str,
    role: MemberRole,
    ip: str | None,
) -> InviteDelivery | None:
    """Convida `email` (já normalizado) para o hábito com `role`.

    Devolve o email a mandar depois do commit, ou None (sem conta, conta bloqueada ou nada
    mudou). Levanta 404, 403, 409 `habit_archived`, `invite_limit_reached` ou
    `guest_limit_reached`.
    """
    with write_transaction(session):
        access = get_habit_access(session, habit_id, owner_id)
        require_owner(access)
        habit = require_writable(access)
        now = utcnow()
        if count_recent_invites(session, owner_id, now=now) >= settings.max_invites_per_day:
            raise ApiError(409, ErrorCode.INVITE_LIMIT_REACHED)
        if count_guests(session, habit_id) >= settings.max_guests_per_habit:
            raise ApiError(409, ErrorCode.GUEST_LIMIT_REACHED)
        # As mesmas três consultas, com o mesmo SQL, com e sem conta para o email
        invitee = session.execute(
            select(User.id, User.locale, User.is_active).where(User.email == email)
        ).one_or_none()
        invitee_id = None if invitee is None else invitee.id
        pending = session.scalar(
            select(HabitInvite.id).where(
                HabitInvite.habit_id == habit_id, HabitInvite.email == email
            )
        )
        member = session.scalar(
            select(HabitMember.user_id)
            .join(User, User.id == HabitMember.user_id)
            .where(HabitMember.habit_id == habit_id, User.email == email)
        )
        if pending is not None or member is not None or invitee_id == habit.owner_id:
            return None
        row = HabitInvite(
            habit_id=habit_id,
            email=email,
            invited_user_id=invitee_id,
            role=role.value,
            created_at=now,
        )
        session.add(row)
        session.flush()
        audit.record(
            session,
            AuditEvent.INVITE_CREATED,
            user_id=owner_id,
            ip=ip,
            habit_id=habit_id,
            details={"invite_id": row.id, "role": role.value},
        )
        habit_name = habit.name
    if invitee is None or not invitee.is_active:
        return None
    return InviteDelivery(
        to=email, locale=pick_locale(invitee.locale), habit_name=habit_name, role=role
    )


def _habit_invite(session: Session, habit_id: int, invite_id: int) -> HabitInvite:
    row = session.scalar(
        select(HabitInvite)
        .where(HabitInvite.id == invite_id, HabitInvite.habit_id == habit_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _not_found()
    return row


def cancel_invite(
    session: Session, *, owner_id: int, habit_id: int, invite_id: int, ip: str | None
) -> None:
    """Cancela o convite pendente do hábito. Levanta 404 (hábito ou convite) ou 403."""
    with write_transaction(session):
        require_owner(get_habit_access(session, habit_id, owner_id))
        row = _habit_invite(session, habit_id, invite_id)
        role = row.role
        session.delete(row)
        audit.record(
            session,
            AuditEvent.INVITE_CANCELED,
            user_id=owner_id,
            ip=ip,
            habit_id=habit_id,
            details={"invite_id": invite_id, "role": role},
        )


def list_habit_invites(session: Session, *, user_id: int, habit_id: int) -> list[HabitInvite]:
    """Convites pendentes do hábito, em ordem de criação. Levanta 404 ou 403 (só o dono)."""
    require_owner(get_habit_access(session, habit_id, user_id))
    return list(
        session.scalars(
            select(HabitInvite)
            .where(HabitInvite.habit_id == habit_id)
            .order_by(HabitInvite.id)
            .execution_options(populate_existing=True)
        )
    )


def list_received_invites(session: Session, user_id: int) -> list[ReceivedInvite]:
    """Convites pendentes endereçados ao usuário (`invited_user_id`), em ordem de criação."""
    rows = session.execute(
        select(HabitInvite, Habit.name, Habit.color, User.id, User.email)
        .join(Habit, Habit.id == HabitInvite.habit_id)
        .join(User, User.id == Habit.owner_id)
        .where(HabitInvite.invited_user_id == user_id)
        .order_by(HabitInvite.id)
        .execution_options(populate_existing=True)
    ).all()
    return [ReceivedInvite(*row) for row in rows]


def _received_invite(session: Session, user_id: int, invite_id: int) -> HabitInvite:
    # Filtrar pelo convidado na consulta: convite alheio, sem conta ou inexistente dão o mesmo 404
    row = session.scalar(
        select(HabitInvite)
        .where(HabitInvite.id == invite_id, HabitInvite.invited_user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _not_found()
    return row


def accept_invite(
    session: Session, settings: Settings, *, user_id: int, invite_id: int, ip: str | None
) -> HabitAccess:
    """Aceita o convite e devolve o hábito com o papel novo.

    Levanta 404 (convite que não é do usuário) ou 409 `shared_habit_limit_reached`.
    """
    with write_transaction(session):
        row = _received_invite(session, user_id, invite_id)
        habit_id = row.habit_id
        habit, member_role = session.execute(
            select(Habit, HabitMember.role)
            .outerjoin(
                HabitMember,
                and_(HabitMember.habit_id == Habit.id, HabitMember.user_id == user_id),
            )
            .where(Habit.id == habit_id)
            .execution_options(populate_existing=True)
        ).one()
        current = role_of(habit, user_id, member_role)
        if current is not None:
            # Já tem acesso (o email da conta mudou depois do convite): o convite só sai
            session.delete(row)
            return HabitAccess(habit, current)
        if count_shared_habits(session, user_id) >= settings.max_shared_habits_per_user:
            raise ApiError(409, ErrorCode.SHARED_HABIT_LIMIT_REACHED)
        role = row.role
        session.add(HabitMember(habit_id=habit_id, user_id=user_id, role=role))
        session.delete(row)
        audit.record(
            session,
            AuditEvent.INVITE_ACCEPTED,
            user_id=user_id,
            ip=ip,
            habit_id=habit_id,
            details={"invite_id": invite_id, "role": role},
        )
    return HabitAccess(habit, HabitRole(role))


def decline_invite(session: Session, *, user_id: int, invite_id: int, ip: str | None) -> None:
    """Recusa o convite. Levanta 404 (convite que não é do usuário)."""
    with write_transaction(session):
        row = _received_invite(session, user_id, invite_id)
        habit_id, role = row.habit_id, row.role
        session.delete(row)
        audit.record(
            session,
            AuditEvent.INVITE_DECLINED,
            user_id=user_id,
            ip=ip,
            habit_id=habit_id,
            details={"invite_id": invite_id, "role": role},
        )


def list_members(session: Session, *, user_id: int, habit_id: int) -> list[MemberEntry]:
    """O dono e os membros do hábito, nessa ordem (membros por entrada). Todo papel vê; 404."""
    habit = get_habit_access(session, habit_id, user_id).habit
    owner_email = session.scalar(select(User.email).where(User.id == habit.owner_id))
    rows = session.execute(
        select(HabitMember.user_id, User.email, HabitMember.role, HabitMember.joined_at)
        .join(User, User.id == HabitMember.user_id)
        .where(HabitMember.habit_id == habit_id)
        .order_by(HabitMember.joined_at, HabitMember.user_id)
    ).all()
    owner = MemberEntry(habit.owner_id, owner_email, HabitRole.OWNER, habit.created_at)
    return [owner] + [
        MemberEntry(member_id, email, HabitRole(role), joined_at)
        for member_id, email, role, joined_at in rows
    ]


def _member(session: Session, habit_id: int, member_id: int) -> HabitMember:
    row = session.scalar(
        select(HabitMember)
        .where(HabitMember.habit_id == habit_id, HabitMember.user_id == member_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _not_found()
    return row


def leave_habit(session: Session, *, user_id: int, habit_id: int, ip: str | None) -> None:
    """O membro sai do hábito; marcações ficam, alertas dele no hábito saem. 404 ou 403 (dono)."""
    with write_transaction(session):
        access = get_habit_access(session, habit_id, user_id)
        if access.is_owner:
            raise ApiError(403, ErrorCode.FORBIDDEN)
        session.execute(
            delete(HabitMember).where(
                HabitMember.habit_id == habit_id, HabitMember.user_id == user_id
            ),
            execution_options={"synchronize_session": False},
        )
        _delete_alerts(session, habit_id, user_id)
        audit.record(
            session,
            AuditEvent.MEMBER_LEFT,
            user_id=user_id,
            ip=ip,
            habit_id=habit_id,
            details={"role": access.role.value},
        )


def remove_member(
    session: Session, *, owner_id: int, habit_id: int, member_id: int, ip: str | None
) -> None:
    """O dono remove o membro; marcações ficam, alertas dele no hábito saem. 404 ou 403."""
    with write_transaction(session):
        require_owner(get_habit_access(session, habit_id, owner_id))
        row = _member(session, habit_id, member_id)
        role = row.role
        session.delete(row)
        _delete_alerts(session, habit_id, member_id)
        audit.record(
            session,
            AuditEvent.MEMBER_REMOVED,
            user_id=owner_id,
            ip=ip,
            habit_id=habit_id,
            details={"member_id": member_id, "role": role},
        )


def change_role(
    session: Session,
    *,
    owner_id: int,
    habit_id: int,
    member_id: int,
    role: MemberRole,
    ip: str | None,
) -> MemberEntry:
    """Troca o papel do membro (o mesmo papel: nada muda). Levanta 404 ou 403.

    De editor para viewer, os alertas dele no hábito saem na mesma transação.
    """
    with write_transaction(session):
        require_owner(get_habit_access(session, habit_id, owner_id))
        row = _member(session, habit_id, member_id)
        old = row.role
        if old != role:
            row.role = role.value
            if role is MemberRole.VIEWER:
                _delete_alerts(session, habit_id, member_id)
            audit.record(
                session,
                AuditEvent.MEMBER_ROLE_CHANGED,
                user_id=owner_id,
                ip=ip,
                habit_id=habit_id,
                details={
                    "member_id": member_id,
                    "changes": [{"field": "role", "old": old, "new": role.value}],
                },
            )
        email = session.scalar(select(User.email).where(User.id == member_id))
        entry = MemberEntry(member_id, email, HabitRole(row.role), row.joined_at)
    return entry
