"""Corpos e respostas da API de compartilhamento.

- Email: como o imago guarda (`normalize_email`: strip + lower, só ASCII, forma simples de
  endereço, até 254 caracteres); inválido, 422 com `field: "email"`, sem o valor. Só ASCII porque
  a conta do imago é ASCII (domínio internacional em punycode): um email com acento nunca teria
  conta.
- Papel do convidado: `editor` ou `viewer` (o dono não é um papel que se dá).
- Campo desconhecido é recusado (422).

O convite pendente que o dono vê não traz `invited_user_id`: diria a ele se o email tem conta.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict

from app.habits.access import HabitRole
from app.identity import is_identity_email
from app.models import MemberRole


def normalize_email(value: str) -> str:
    """Email com strip + lower, como o imago guarda; ValueError (422, sem o valor) se inválido."""
    email = value.strip().lower()
    if not is_identity_email(email):
        raise ValueError("email inválido")
    return email


Email = Annotated[str, AfterValidator(normalize_email)]


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
    # Nome da paleta ou "#rrggbb" (app/habits/schemas.py)
    color: str


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
