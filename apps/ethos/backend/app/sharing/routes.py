"""Endpoints do compartilhamento (ETH-24). Todos exigem `CurrentUser`; as regras ficam no
`service.py`.

Do hábito (sem acesso ao hábito: 404 `not_found`; com acesso, mas sem o papel: 403 `forbidden`):

- `POST /habits/{id}/invites` com `{email, role}` (só o dono): 202 `{"status": "sent"}`, sempre
  igual (com ou sem conta, a si mesmo, a quem já é membro). Limites: 409 `invite_limit_reached`
  e `guest_limit_reached`. Arquivado: 409 `habit_archived`. O imago diz se o email tem conta
  ativa (`lookup`); sem resposta dele, 503 `service_unavailable` e nada é gravado. O convidado com
  conta recebe o email pelo imago depois da resposta.
- `GET /habits/{id}/invites` (só o dono): `{"invites": [{id, email, role, created_at}]}`, os
  pendentes.
- `DELETE /habits/{id}/invites/{invite_id}` (só o dono): 204, cancela o pendente.
- `GET /habits/{id}/members` (todo papel): `{"members": [{user: {id, email}, role, joined_at}],
  "guest_limit": n}`, o dono primeiro; `guest_limit` é o `MAX_GUESTS_PER_HABIT` (membros +
  convites pendentes), para a tela mostrar as vagas.
- `PATCH /habits/{id}/members/{user_id}` com `{role}` (só o dono): o membro com o papel novo.
- `DELETE /habits/{id}/members/{user_id}` (só o dono): 204.
- `POST /habits/{id}/leave` (editor e viewer; o dono leva 403): 204.

Do convidado (convite que não é dele, sem conta no convite ou que não existe: 404 `not_found`):

- `GET /invites`: `{"invites": [{id, habit: {id, name, color}, owner: {id, email}, role,
  created_at}]}`, os pendentes recebidos.
- `POST /invites/{invite_id}/accept`: o hábito (como `GET /habits/{id}`), com o papel novo.
  Limite de hábitos compartilhados: 409 `shared_habit_limit_reached`.
- `POST /invites/{invite_id}/decline`: 204.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Path

from app.config import SettingsDep
from app.db import SessionDep
from app.errors import ApiError, ErrorCode
from app.habits.access import MAX_ID, HabitId
from app.habits.routes import present
from app.habits.schemas import HabitOut
from app.identity import CurrentUser
from app.imago_client import ImagoDep, ImagoUnavailableError
from app.mail.catalog import Invite
from app.mail.sender import MailerDep, schedule_email
from app.sharing import service
from app.sharing.schemas import (
    InviteCreate,
    InvitedHabit,
    InviteSent,
    MemberList,
    MemberOut,
    PendingInvite,
    PendingInviteList,
    Person,
    ReceivedInviteList,
    ReceivedInviteOut,
    RoleUpdate,
)
from app.sharing.service import MemberEntry

router = APIRouter(tags=["sharing"])

# Ids no caminho (`/invites/{invite_id}`, `/habits/{id}/members/{user_id}`)
InviteId = Annotated[int, Path(ge=1, le=MAX_ID)]
UserId = Annotated[int, Path(ge=1, le=MAX_ID)]


def member_out(entry: MemberEntry) -> MemberOut:
    return MemberOut(
        user=Person(id=entry.user_id, email=entry.email),
        role=entry.role,
        joined_at=entry.joined_at,
    )


@router.post("/habits/{habit_id}/invites", status_code=202)
def create_invite(
    habit_id: HabitId,
    body: InviteCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    imago: ImagoDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> InviteSent:
    # Antes de perguntar ao imago: quem não pode convidar não gera uma busca
    service.check_invite(session, settings, owner_id=user.id, habit_id=habit_id)
    try:
        invitee = imago.lookup_user(body.email)
    except ImagoUnavailableError:
        raise ApiError(503, ErrorCode.SERVICE_UNAVAILABLE) from None
    delivery = service.invite(
        session,
        settings,
        owner_id=user.id,
        habit_id=habit_id,
        email=body.email,
        role=body.role,
        invitee=invitee,
    )
    # A transação já fechou: o email sai depois da resposta, que é igual em todos os casos
    if delivery is not None:
        schedule_email(
            background_tasks,
            mailer,
            delivery.user_id,
            delivery.locale,
            Invite(
                habit_name=delivery.habit_name,
                inviter_email=user.email,
                role=delivery.role.value,
            ),
        )
    return InviteSent()


@router.get("/habits/{habit_id}/invites")
def list_habit_invites(
    habit_id: HabitId, user: CurrentUser, session: SessionDep
) -> PendingInviteList:
    rows = service.list_habit_invites(session, user_id=user.id, habit_id=habit_id)
    return PendingInviteList(
        invites=[
            PendingInvite(id=row.id, email=row.email, role=row.role, created_at=row.created_at)
            for row in rows
        ]
    )


@router.delete("/habits/{habit_id}/invites/{invite_id}", status_code=204)
def cancel_invite(
    habit_id: HabitId,
    invite_id: InviteId,
    user: CurrentUser,
    session: SessionDep,
) -> None:
    service.cancel_invite(session, owner_id=user.id, habit_id=habit_id, invite_id=invite_id)


@router.get("/habits/{habit_id}/members")
def list_members(
    habit_id: HabitId, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> MemberList:
    entries = service.list_members(session, user_id=user.id, habit_id=habit_id)
    return MemberList(
        members=[member_out(entry) for entry in entries],
        guest_limit=settings.max_guests_per_habit,
    )


@router.patch("/habits/{habit_id}/members/{user_id}")
def change_role(
    habit_id: HabitId,
    user_id: UserId,
    body: RoleUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> MemberOut:
    entry = service.change_role(
        session,
        owner_id=user.id,
        habit_id=habit_id,
        member_id=user_id,
        role=body.role,
    )
    return member_out(entry)


@router.delete("/habits/{habit_id}/members/{user_id}", status_code=204)
def remove_member(
    habit_id: HabitId,
    user_id: UserId,
    user: CurrentUser,
    session: SessionDep,
) -> None:
    service.remove_member(session, owner_id=user.id, habit_id=habit_id, member_id=user_id)


@router.post("/habits/{habit_id}/leave", status_code=204)
def leave_habit(habit_id: HabitId, user: CurrentUser, session: SessionDep) -> None:
    service.leave_habit(session, user_id=user.id, habit_id=habit_id)


@router.get("/invites")
def list_received_invites(user: CurrentUser, session: SessionDep) -> ReceivedInviteList:
    received = service.list_received_invites(session, user.id)
    return ReceivedInviteList(
        invites=[
            ReceivedInviteOut(
                id=item.invite.id,
                habit=InvitedHabit(
                    id=item.invite.habit_id, name=item.habit_name, color=item.habit_color
                ),
                owner=Person(id=item.owner_id, email=item.owner_email),
                role=item.invite.role,
                created_at=item.invite.created_at,
            )
            for item in received
        ]
    )


@router.post("/invites/{invite_id}/accept")
def accept_invite(
    invite_id: InviteId,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> HabitOut:
    user_id, timezone = user.id, user.timezone
    access = service.accept_invite(session, settings, user_id=user_id, invite_id=invite_id)
    [out] = present(session, [access], timezone)
    return out


@router.post("/invites/{invite_id}/decline", status_code=204)
def decline_invite(invite_id: InviteId, user: CurrentUser, session: SessionDep) -> None:
    service.decline_invite(session, user_id=user.id, invite_id=invite_id)
