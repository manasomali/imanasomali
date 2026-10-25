"""Corpos e respostas da API de compartilhamento.

- Email: o mesmo tratamento do login (`app/auth/routes.Email`: strip + lower, forma simples de
  endereço, até 254 caracteres); inválido, 422 com `field: "email"`, sem o valor.
- Papel do convidado: `editor` ou `viewer` (o dono não é um papel que se dá).
- Campo desconhecido é recusado (422).

O convite pendente que o dono vê não traz `invited_user_id`: diria a ele se o email tem conta.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.auth.routes import Email
from app.habits.access import HabitRole
from app.models import HabitColor, MemberRole


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    role: MemberRole


class InviteSent(BaseModel):
    """Corpo do 202 do convite, igual em todos os casos (com ou sem conta, membro, a si mesmo)."""

    status: Literal["sent"] = "sent"


class PendingInvite(BaseModel):
    """Convite pendente de um hábito, visto pelo dono."""

    id: int
    email: str
    role: MemberRole
    created_at: datetime


class PendingInviteList(BaseModel):
    invites: list[PendingInvite]


class InvitedHabit(BaseModel):
    id: int
    name: str
    color: HabitColor


class Person(BaseModel):
    id: int
    email: str


class ReceivedInviteOut(BaseModel):
    """Convite recebido: o hábito, quem convidou e o papel oferecido."""

    id: int
    habit: InvitedHabit
    owner: Person
    role: MemberRole
    created_at: datetime


class ReceivedInviteList(BaseModel):
    invites: list[ReceivedInviteOut]


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: MemberRole


class MemberOut(BaseModel):
    """Pessoa com acesso ao hábito; o dono vem com `role: "owner"` e a criação do hábito."""

    user: Person
    role: HabitRole
    joined_at: datetime


class MemberList(BaseModel):
    """Dono e membros, e o `MAX_GUESTS_PER_HABIT` (`guest_limit`): membros + convites pendentes.

    O limite vem da config; vai aqui para a tela mostrar as vagas sem repetir o valor no front.
    """

    members: list[MemberOut]
    guest_limit: int
