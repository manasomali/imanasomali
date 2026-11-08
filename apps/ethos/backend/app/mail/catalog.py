"""Catálogo fechado dos emails do ethos: um tipo por email, com os dados que o texto usa.

Só convite, alerta e os avisos do compartilhamento (perda de acesso, hábito apagado). Os emails de
conta (código de login e de exclusão, conta excluída, troca de email, teto de envio) são do
imago. Nada de email em massa: o catálogo não tem aviso para grupos nem link de descadastro. Email
novo entra aqui, em `Email` e nos textos de `templates.py` (pt e en).

Os dados chegam prontos de quem chama (nomes, números, ids). O módulo não lê o banco nem importa
os modelos. Campos com email ficam fora do `repr`, para não vazarem num traceback.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, Literal

type PeriodKind = Literal["week", "month", "year"]
type MemberRole = Literal["editor", "viewer"]
# Meta: "behind" = atrasado no ritmo (min e exact), "reached" = chegou ao máximo (max),
# "exceeded" = passou de N (max e exact)
type GoalStatus = Literal["behind", "reached", "exceeded"]
# Custo: "warning" = chegou a 80% do limite, "exceeded" = passou do limite
type CostStatus = Literal["warning", "exceeded"]

_PERIODS = frozenset({"week", "month", "year"})


class EmailKind(StrEnum):
    INVITE = "invite"
    ALERT = "alert"
    ACCESS_LOST = "access_lost"
    HABIT_DELETED = "habit_deleted"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class Invite:
    """Convite para um hábito, enviado ao convidado que já tem conta (ETH-24)."""

    kind: ClassVar[EmailKind] = EmailKind.INVITE
    habit_name: str
    inviter_email: str = field(repr=False)
    role: MemberRole

    def __post_init__(self) -> None:
        _require(self.role in ("editor", "viewer"), "papel inválido")


@dataclass(frozen=True, slots=True, kw_only=True)
class GoalAlert:
    """Parte de meta do alerta: o valor do período atual (`done`) e o N da meta (`target`)."""

    status: GoalStatus
    done: int
    target: int
    period: PeriodKind

    def __post_init__(self) -> None:
        _require(self.status in ("behind", "reached", "exceeded"), "situação de meta inválida")
        _require(self.period in _PERIODS, "período inválido")


@dataclass(frozen=True, slots=True, kw_only=True)
class CostAlert:
    """Parte de custo do alerta: gasto e limite do período, em centavos."""

    status: CostStatus
    spent_cents: int
    limit_cents: int
    period: PeriodKind

    def __post_init__(self) -> None:
        _require(self.status in ("warning", "exceeded"), "situação de custo inválida")
        _require(self.period in _PERIODS, "período inválido")


@dataclass(frozen=True, slots=True, kw_only=True)
class Alert:
    """Alerta de um hábito, com meta e custo num email só (ETH-26). Pelo menos um dos dois."""

    kind: ClassVar[EmailKind] = EmailKind.ALERT
    habit_id: int
    habit_name: str
    goal: GoalAlert | None = None
    cost: CostAlert | None = None

    def __post_init__(self) -> None:
        _require(self.goal is not None or self.cost is not None, "alerta sem meta e sem custo")


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessLost:
    """Aviso ao membro: a conta do dono foi excluída e os hábitos sumiram (ETH-27).

    Um email por convidado, com todos os hábitos daquele dono de que ele participava.
    """

    kind: ClassVar[EmailKind] = EmailKind.ACCESS_LOST
    habit_names: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(len(self.habit_names) > 0, "sem hábitos para avisar")


@dataclass(frozen=True, slots=True, kw_only=True)
class HabitDeleted:
    """Aviso aos membros: o dono apagou o hábito (ETH-20)."""

    kind: ClassVar[EmailKind] = EmailKind.HABIT_DELETED
    habit_name: str


type Email = Invite | Alert | AccessLost | HabitDeleted
