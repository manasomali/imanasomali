"""Entrada e resposta de `GET /habits/progress`.

- `from` e `to`: datas locais `YYYY-MM-DD` (só esse formato: nada de horário, fuso ou número), no
  fuso de quem pede, as duas inclusivas, de `MIN_DAY` a `MAX_DAY`. O intervalo máximo (5 anos) é
  conferido no `service.py`, que vê as duas juntas.
- `habit_ids`: id repetido na query (`?habit_ids=1&habit_ids=2`), cada um de 1 até o maior inteiro
  do SQLite, no máximo `MAX_HABIT_IDS`.

Na resposta, campos de recursos desligados nem aparecem: `score` (dentro do `habit`, como no
`GET /habits`), `spend_cents` dos períodos e `cost_periods`. `marks_range` vem sempre (null sem
marcação).
"""

import re
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

from app.habits.access import MAX_ID
from app.habits.schemas import HabitOut

# Mesmo piso das datas das marcações (`app/marks/schemas.MIN_INSTANT`)
MIN_DAY = date(1900, 1, 1)
# Longe de qualquer uso e dos limites do `date` (ano 9999), que estourariam no fim do período
MAX_DAY = date(2999, 12, 31)
# Ids por request; sem `habit_ids`, vêm todos os hábitos que o usuário acessa
MAX_HABIT_IDS = 100

_DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _iso_day(value: Any) -> Any:
    # Sem isso, o pydantic aceitaria "2026-03-01T00:00:00" e número (segundos desde 1970)
    if not isinstance(value, str) or _DAY_RE.fullmatch(value) is None:
        raise ValueError("data no formato YYYY-MM-DD")
    # fromisoformat recusa dia que não existe (2026-02-30) com ValueError, que vira 422
    return date.fromisoformat(value)


def _is_none(value: Any) -> bool:
    return value is None


# Data local do intervalo
Day = Annotated[date, BeforeValidator(_iso_day), Field(ge=MIN_DAY, le=MAX_DAY)]
# Um id de `habit_ids`
HabitIdItem = Annotated[int, Field(ge=1, le=MAX_ID)]


class PeriodOut(BaseModel):
    """Um período da meta (semana ISO, mês ou ano), com as datas locais inclusivas."""

    first_day: date
    last_day: date
    # Dias marcados (toggle), marcações (várias por dia) ou minutos (duração ligada)
    value: int
    met: bool
    # Soma de cost_cents das marcações do período; só com o custo ligado
    spend_cents: int | None = Field(default=None, exclude_if=_is_none)


class CostPeriodOut(BaseModel):
    """Um período do limite de custo (`cost_limit_period`), com as datas locais inclusivas."""

    first_day: date
    last_day: date
    spend_cents: int
    # spend * 100 / limite, arredondado meio para cima (pode passar de 100); null com limite 0
    limit_percent: int | None


class MarksRangeOut(BaseModel):
    """Dias locais da primeira e da última marcação do hábito, em todo o tempo (fora do
    intervalo pedido também)."""

    first_day: date
    last_day: date


class HabitProgressOut(BaseModel):
    # A configuração, o papel e, com a pontuação ligada, `score: {value, success}`
    habit: HabitOut
    # Alvo da meta na unidade de `value`: N, ou N * duration_minutes com a duração ligada
    goal_target: int
    periods: list[PeriodOut]
    # Só com o custo ligado e um limite
    cost_periods: list[CostPeriodOut] | None = Field(default=None, exclude_if=_is_none)
    # Sempre presente; null sem nenhuma marcação
    marks_range: MarksRangeOut | None


class ProgressOut(BaseModel):
    first_day: date = Field(serialization_alias="from")
    last_day: date = Field(serialization_alias="to")
    # Fuso de quem pede (`users.timezone`), usado em todos os cálculos
    timezone: str
    habits: list[HabitProgressOut]
