"""Acesso a um hábito: quem pode ver e quem pode mudar.

Papéis (ethos-plan.md, "compartilhamento"):

- `owner`: `habits.owner_id`. Único que edita a configuração, pausa, arquiva, compartilha e apaga.
- `editor`: linha em `habit_members`. Marca, desmarca e edita marcações (de qualquer pessoa).
- `viewer`: linha em `habit_members`. Só vê.

Quem não é nenhum dos três recebe 404 `not_found`, igual a um id que não existe: a API nunca
revela que o hábito existe. Quem vê mas não pode fazer a ação recebe 403 `forbidden`.

Hábito arquivado é só leitura (ethos-plan.md, "pausar e arquivar"): toda escrita nele (editar a
configuração, pausar, retomar, marcar, desmarcar, editar marcação) recebe 409 `habit_archived`.
Desarquivar e apagar continuam permitidos ao dono. Pausado continua marcável.

Uso num endpoint (vale dentro de um `write_transaction`, onde a leitura fica protegida):

    access = get_habit_access(session, habit_id, user_id)  # 404
    habit = require_owner(access)                          # 403 para editor e viewer
    require_writable(access)                               # 409 se arquivado
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Path
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models import Habit, HabitMember, HabitStatus

# Maior inteiro do SQLite: um id acima disso daria OverflowError no driver (500), não 404
MAX_ID = 2**63 - 1

# Id de hábito no caminho (`/habits/{habit_id}`)
HabitId = Annotated[int, Path(ge=1, le=MAX_ID)]


class HabitRole(StrEnum):
    """Papel do usuário num hábito. O dono não tem linha em `habit_members`."""

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class HabitAccess:
    habit: Habit
    role: HabitRole

    @property
    def is_owner(self) -> bool:
        return self.role is HabitRole.OWNER

    @property
    def can_mark(self) -> bool:
        """Dono e editor marcam, desmarcam e editam marcações; viewer só lê."""
        return self.role is not HabitRole.VIEWER


def role_of(habit: Habit, user_id: int, member_role: str | None) -> HabitRole | None:
    """Papel de `user_id` em `habit`, dado o `habit_members.role` dele (None se não é membro)."""
    if habit.owner_id == user_id:
        return HabitRole.OWNER
    if member_role is None:
        return None
    return HabitRole(member_role)


def get_habit_access(session: Session, habit_id: int, user_id: int) -> HabitAccess:
    """O hábito e o papel de `user_id` nele; 404 `not_found` se não existe ou se não tem acesso."""
    row = session.execute(
        select(Habit, HabitMember.role)
        .outerjoin(
            HabitMember,
            and_(HabitMember.habit_id == Habit.id, HabitMember.user_id == user_id),
        )
        .where(Habit.id == habit_id)
        # Relê a linha mesmo que a sessão já tenha o objeto de outra transação
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    habit, member_role = row
    role = role_of(habit, user_id, member_role)
    if role is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    return HabitAccess(habit, role)


def require_owner(access: HabitAccess) -> Habit:
    """O hábito, se quem pede é o dono; senão 403 `forbidden` (editor e viewer)."""
    if not access.is_owner:
        raise ApiError(403, ErrorCode.FORBIDDEN)
    return access.habit


def require_writable(access: HabitAccess) -> Habit:
    """O hábito, se aceita escrita; arquivado (só leitura) dá 409 `habit_archived`.

    Confira o papel antes (`require_owner`, ou `can_mark` nas marcações): quem não pode escrever
    recebe 403 mesmo num hábito arquivado.
    """
    if access.habit.status == HabitStatus.ARCHIVED:
        raise ApiError(409, ErrorCode.HABIT_ARCHIVED)
    return access.habit
