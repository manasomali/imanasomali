"""Corpos e respostas da API de hábitos.

Validação de cada campo isolado (tamanhos e formatos do plano, "tamanhos e formatos"); as regras
que dependem de outros campos ou da config (teto da meta, recompensa só com pontuação etc.) ficam
em `service.check_config`, que vê a configuração inteira depois da mudança.

- Textos: espaços nas pontas saem; texto opcional vazio vira `null`. Nome, sigla, recompensa e
  punição são de uma linha; a descrição aceita quebra de linha e tab. Outros caracteres de
  controle e os que invertem a direção do texto (fazem um texto parecer outro) são recusados.
- Sigla: 1 a 4 letras (A-Z) ou números (0-9), salva em maiúsculas.
- Booleanos e inteiros são estritos: `"true"`, `1` no lugar de `true`, `"3"` ou `3.0` são
  recusados.
- Campos desconhecidos (`status`, `owner_id`...) são recusados (422).
"""

import re
import unicodedata
from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, Strict, field_validator

from app.habits.access import HabitRole
from app.models import (
    DEFAULT_SCORE_THRESHOLD,
    HABIT_CODE_MAX_LENGTH,
    HABIT_DESCRIPTION_MAX_LENGTH,
    HABIT_NAME_MAX_LENGTH,
    HABIT_PUNISHMENT_MAX_LENGTH,
    HABIT_REWARD_MAX_LENGTH,
    CostLevel,
    GoalType,
    HabitColor,
    HabitStatus,
    Period,
)

# Duração de uma sessão: até um dia inteiro
MAX_DURATION_MINUTES = 24 * 60
# Teto de valores em centavos (10 bilhões na unidade de dinheiro). Mesmo somando o máximo de
# marcações por dia durante anos, a soma cabe no inteiro de 64 bits do SQLite
MAX_MONEY_CENTS = 10**12
# Teto absoluto de N, antes da regra que depende do período e da config (service.check_config)
MAX_GOAL_COUNT = 10**9

_CODE_RE = re.compile(rf"[A-Za-z0-9]{{1,{HABIT_CODE_MAX_LENGTH}}}")
# Únicos caracteres de controle aceitos num texto de várias linhas
_MULTILINE_CONTROLS = frozenset("\n\t")
# Embutir, sobrepor e isolar a direção do texto (bidi): U+202A a U+202E e U+2066 a U+2069
_BIDI_CONTROLS = frozenset(map(chr, [*range(0x202A, 0x202F), *range(0x2066, 0x206A)]))


def check_controls(value: str, *, multiline: bool) -> None:
    """Recusa caracteres de controle (com `multiline`, aceita quebra de linha e tab) e os que
    invertem a direção do texto. Levanta ValueError (vira 422 no validador do pydantic)."""
    allowed = _MULTILINE_CONTROLS if multiline else frozenset()
    for char in value:
        # Cc: controle (\x00, \r, ESC...). Outros invisíveis (ZWJ dos emoji) passam
        if (unicodedata.category(char) == "Cc" and char not in allowed) or char in _BIDI_CONTROLS:
            raise ValueError("caractere de controle não permitido")


def _text(max_length: int, *, multiline: bool = False, required: bool = False) -> Any:
    def validate(value: str) -> str | None:
        value = value.strip()
        if not value:
            if required:
                raise ValueError("não pode ser vazio")
            return None
        if len(value) > max_length:
            raise ValueError(f"no máximo {max_length} caracteres")
        check_controls(value, multiline=multiline)
        return value

    return AfterValidator(validate)


def _code(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    # fullmatch e [A-Za-z0-9]: nada de letras de outros alfabetos nem \n no fim
    if _CODE_RE.fullmatch(value) is None:
        raise ValueError(f"1 a {HABIT_CODE_MAX_LENGTH} letras ou números")
    return value.upper()


Name = Annotated[str, _text(HABIT_NAME_MAX_LENGTH, required=True)]
Code = Annotated[str, AfterValidator(_code)]
Description = Annotated[str, _text(HABIT_DESCRIPTION_MAX_LENGTH, multiline=True)]
Reward = Annotated[str, _text(HABIT_REWARD_MAX_LENGTH)]
Punishment = Annotated[str, _text(HABIT_PUNISHMENT_MAX_LENGTH)]
Flag = Annotated[bool, Strict()]
GoalCount = Annotated[int, Strict(), Field(ge=0, le=MAX_GOAL_COUNT)]
DurationMinutes = Annotated[int, Strict(), Field(ge=1, le=MAX_DURATION_MINUTES)]
ScoreThreshold = Annotated[int, Strict(), Field(ge=1, le=100)]
Money = Annotated[int, Strict(), Field(ge=0, le=MAX_MONEY_CENTS)]

# Campos da configuração, na ordem da tabela `habits`
CONFIG_FIELDS = (
    "name",
    "code",
    "description",
    "color",
    "goal_type",
    "goal_count",
    "goal_period",
    "multi_mark",
    "duration_enabled",
    "duration_minutes",
    "notes_enabled",
    "score_enabled",
    "score_threshold",
    "reward",
    "punishment",
    "cost_enabled",
    "cost_level",
    "cost_cents",
    "cost_limit_cents",
    "cost_limit_period",
)
# Campos que aceitam null (o resto é obrigatório no banco)
NULLABLE_FIELDS = frozenset(
    {
        "code",
        "description",
        "duration_minutes",
        "reward",
        "punishment",
        "cost_cents",
        "cost_limit_cents",
        "cost_limit_period",
    }
)


class HabitCreate(BaseModel):
    """Configuração de um hábito novo. Recursos opcionais vêm desligados por padrão."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    code: Code | None = None
    description: Description | None = None
    color: HabitColor
    goal_type: GoalType
    goal_count: GoalCount
    goal_period: Period
    # false: toggle (uma marcação por dia)
    multi_mark: Flag = False
    duration_enabled: Flag = False
    duration_minutes: DurationMinutes | None = None
    notes_enabled: Flag = False
    score_enabled: Flag = False
    score_threshold: ScoreThreshold = DEFAULT_SCORE_THRESHOLD
    reward: Reward | None = None
    punishment: Punishment | None = None
    cost_enabled: Flag = False
    cost_level: CostLevel = CostLevel.HABIT
    cost_cents: Money | None = None
    cost_limit_cents: Money | None = None
    cost_limit_period: Period | None = None


class HabitUpdate(BaseModel):
    """Mudança parcial: campo ausente não muda; `null` só nos campos opcionais."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    code: Code | None = None
    description: Description | None = None
    color: HabitColor | None = None
    goal_type: GoalType | None = None
    goal_count: GoalCount | None = None
    goal_period: Period | None = None
    multi_mark: Flag | None = None
    duration_enabled: Flag | None = None
    duration_minutes: DurationMinutes | None = None
    notes_enabled: Flag | None = None
    score_enabled: Flag | None = None
    score_threshold: ScoreThreshold | None = None
    reward: Reward | None = None
    punishment: Punishment | None = None
    cost_enabled: Flag | None = None
    cost_level: CostLevel | None = None
    cost_cents: Money | None = None
    cost_limit_cents: Money | None = None
    cost_limit_period: Period | None = None

    @field_validator(*(name for name in CONFIG_FIELDS if name not in NULLABLE_FIELDS))
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        # Só roda quando o campo veio no corpo. O nome só vira None se veio null (texto vazio
        # já foi recusado pelo validador dele)
        if value is None:
            raise ValueError("não pode ser null")
        return value


class HabitScore(BaseModel):
    """Pontuação no fuso de quem pede. `value` e `success` null: "sem dados"."""

    value: int | None
    success: bool | None


def _is_none(value: Any) -> bool:
    return value is None


class HabitOut(BaseModel):
    id: int
    # Papel de quem pede: owner, editor ou viewer
    role: HabitRole
    name: str
    code: str | None
    # O que a tela mostra: a sigla quando definida, senão o nome
    label: str
    description: str | None
    color: HabitColor
    goal_type: GoalType
    goal_count: int
    goal_period: Period
    multi_mark: bool
    duration_enabled: bool
    duration_minutes: int | None
    notes_enabled: bool
    score_enabled: bool
    score_threshold: int
    reward: str | None
    punishment: str | None
    cost_enabled: bool
    cost_level: CostLevel
    cost_cents: int | None
    cost_limit_cents: int | None
    cost_limit_period: Period | None
    status: HabitStatus
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Só com a pontuação ligada; desligada, a chave nem aparece na resposta
    score: HabitScore | None = Field(default=None, exclude_if=_is_none)


class HabitList(BaseModel):
    habits: list[HabitOut]
