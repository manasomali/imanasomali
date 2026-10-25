"""Progresso dos hábitos num intervalo de datas: os dados do relatório e do export (ETH-23).

Todo cálculo sai do `app/score.py`, no fuso de quem pede (`users.timezone`), como no calendário:

- `periods`: `score.summarize_periods` nos períodos da meta (`goal_period`) que tocam o intervalo.
  Cada período vem inteiro, com o valor e o gasto do período todo, mesmo que o intervalo comece
  ou acabe no meio dele. Não filtra criação nem pausa: são os números do que foi marcado.
- Pontuação e sucesso/falha: `score.evaluate`, só com `score_enabled`. É a pontuação atual do
  hábito, a mesma do `GET /habits` (da criação até o período anterior ao atual, ou congelada no
  arquivamento), não uma pontuação recortada pelo intervalo.
- Gasto (só com `cost_enabled`): a soma de `cost_cents` das marcações, como gravado na criação de
  cada uma (nível hábito ou nível marcação dá na mesma). Vem em cada período da meta e, quando há
  limite, também nos períodos do limite (`cost_limit_period`, que pode ser outro: meta semanal com
  limite mensal), com a porcentagem do limite arredondada meio para cima, só com inteiros.

Intervalo (`check_range`): datas locais inclusivas, `from` <= `to`, cobrindo no máximo 5 anos de
dias: de 1/1/2021, vai até 31/12/2025; 1/1/2026 já seria 5 anos e 1 dia. De 29/2, o aniversário
num ano não bissexto é 1/3.

Marcações de todo o tempo (`marks_range`): o primeiro e o último dia local com marcação no
hábito, fora do intervalo pedido também (inclusive antes da criação). É o que o "exportar tudo" do
front usa para saber de onde até onde buscar as marcações, sem sondar ano por ano.

Hábitos (`accessible_habits`): os que o usuário acessa (dono, editor ou viewer), inclusive
arquivados, que guardam histórico e entram no "exportar tudo". Id sem acesso, ou que não existe,
some da resposta, sem erro: a API nunca revela que um hábito de outra pessoa existe.

Leitura em lote, sem N+1: hábitos (2 consultas), marcações e pausas (1 cada), em qualquer número de
hábitos, todas na mesma transação de leitura da request.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app import score
from app.errors import ApiError, ErrorCode
from app.habits.access import HabitAccess
from app.habits.scoring import load_marks, load_pauses, to_score_habit
from app.habits.service import list_habits

# Maior intervalo de um relatório (ethos-plan.md, "relatório e export")
MAX_RANGE_YEARS = 5


def range_end(first_day: date) -> date:
    """Primeiro dia que já passa do intervalo máximo que começa em `first_day`."""
    year = first_day.year + MAX_RANGE_YEARS
    try:
        return first_day.replace(year=year)
    except ValueError:
        # 29/2 num ano que não é bissexto
        return date(year, 3, 1)


def check_range(first_day: date, last_day: date) -> None:
    """422 `validation_error` em `to` se ele é antes de `from` ou passa de 5 anos."""
    if last_day < first_day or last_day >= range_end(first_day):
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, field="to")


def accessible_habits(
    session: Session, user_id: int, habit_ids: Collection[int] | None
) -> list[HabitAccess]:
    """Hábitos que `user_id` acessa, com o papel, por id; com `habit_ids`, só esses."""
    accesses = [*list_habits(session, user_id), *list_habits(session, user_id, archived=True)]
    if habit_ids is not None:
        wanted = set(habit_ids)
        accesses = [access for access in accesses if access.habit.id in wanted]
    return sorted(accesses, key=lambda access: access.habit.id)


@dataclass(frozen=True, slots=True)
class CostPeriod:
    period: score.Period
    spend_cents: int
    # None com limite 0 (porcentagem indefinida)
    limit_percent: int | None


@dataclass(frozen=True, slots=True)
class HabitProgress:
    access: HabitAccess
    goal_target: int
    periods: tuple[score.PeriodResult, ...]
    # Só com a pontuação ligada
    evaluation: score.Evaluation | None
    # Só com o custo ligado e um limite
    cost_periods: tuple[CostPeriod, ...] | None
    # Primeiro e último dia local com marcação, em todo o tempo; None sem marcação
    marks_range: tuple[date, date] | None


def marks_range(marks: Sequence[score.Mark], tz: ZoneInfo) -> tuple[date, date] | None:
    """O dia local da primeira e da última marcação (de todo o tempo); None sem marcação."""
    if not marks:
        return None
    instants = [mark.marked_at for mark in marks]
    return min(instants).astimezone(tz).date(), max(instants).astimezone(tz).date()


def limit_percent(spend_cents: int, limit_cents: int) -> int | None:
    """Gasto em porcentagem do limite, meio para cima; None com limite 0."""
    if limit_cents == 0:
        return None
    return score.round_half_up(100 * spend_cents, limit_cents)


def _cost_periods(
    habit: score.Habit,
    marks: Sequence[score.Mark],
    tz: ZoneInfo,
    first_day: date,
    last_day: date,
) -> tuple[CostPeriod, ...] | None:
    limit, kind = habit.cost_limit_cents, habit.cost_limit_period
    if not habit.cost_enabled or limit is None or kind is None:
        return None
    # O mesmo resumo da meta, nos períodos do limite: dele só vale o gasto
    results = score.summarize_periods(
        replace(habit, goal_period=kind), marks, tz, first_day, last_day
    )
    periods = []
    for result in results:
        # Com o custo ligado, o score.py sempre soma o gasto (marcação sem custo soma 0)
        spend = result.spend_cents or 0
        periods.append(CostPeriod(result.period, spend, limit_percent(spend, limit)))
    return tuple(periods)


def habit_progress(
    access: HabitAccess,
    marks: Sequence[score.Mark],
    pauses: Sequence[score.Pause],
    tz: ZoneInfo,
    first_day: date,
    last_day: date,
    *,
    now: datetime,
) -> HabitProgress:
    """O progresso de um hábito, com as marcações e pausas dele já carregadas."""
    habit = to_score_habit(access.habit)
    evaluation = None
    if access.habit.score_enabled:
        evaluation = score.evaluate(habit, marks, pauses, tz, now)
    return HabitProgress(
        access=access,
        goal_target=score.goal_target(habit),
        periods=score.summarize_periods(habit, marks, tz, first_day, last_day),
        evaluation=evaluation,
        cost_periods=_cost_periods(habit, marks, tz, first_day, last_day),
        marks_range=marks_range(marks, tz),
    )


def build_progress(
    session: Session,
    accesses: Sequence[HabitAccess],
    tz: ZoneInfo,
    first_day: date,
    last_day: date,
    *,
    now: datetime,
) -> list[HabitProgress]:
    """O progresso de cada hábito, na ordem recebida, com uma consulta de marcações e uma de
    pausas no total. As pausas só importam para a pontuação: só as dos hábitos com ela ligada."""
    habit_ids = [access.habit.id for access in accesses]
    marks = load_marks(session, habit_ids)
    pauses = load_pauses(
        session, [access.habit.id for access in accesses if access.habit.score_enabled]
    )
    return [
        habit_progress(
            access,
            marks[access.habit.id],
            pauses.get(access.habit.id, []),
            tz,
            first_day,
            last_day,
            now=now,
        )
        for access in accesses
    ]
