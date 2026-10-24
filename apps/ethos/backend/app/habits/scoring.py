"""Ponte entre os modelos do banco e as funções puras de `app/score.py`.

O `score.py` não abre banco: recebe dataclasses (`Habit`, `Mark`, `Pause`). Aqui ficam a
conversão e a leitura em lote, uma consulta para as marcações e outra para as pausas de todos os
hábitos pedidos (nada de uma consulta por hábito):

    evaluations = evaluate_habits(session, habits, ZoneInfo(user.timezone), now=utcnow())
    evaluations[habit.id].score

O fuso é sempre o de quem vê (`users.timezone`), como no calendário.
"""

from collections.abc import Collection, Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, score


def to_score_habit(habit: models.Habit) -> score.Habit:
    """A configuração atual do hábito no formato do `score.py`."""
    return score.Habit(
        goal_type=habit.goal_type,
        goal_count=habit.goal_count,
        goal_period=habit.goal_period,
        created_at=habit.created_at,
        multi_mark=habit.multi_mark,
        duration_enabled=habit.duration_enabled,
        duration_minutes=habit.duration_minutes,
        score_threshold=habit.score_threshold,
        cost_enabled=habit.cost_enabled,
        cost_limit_cents=habit.cost_limit_cents,
        cost_limit_period=habit.cost_limit_period,
        archived_at=habit.archived_at,
    )


def load_marks(
    session: Session, habit_ids: Collection[int], *, since_creation: bool = False
) -> dict[int, list[score.Mark]]:
    """Marcações de cada hábito (todos os ids presentes na resposta, mesmo sem marcação).

    Com `since_creation`, só as feitas a partir da criação do hábito: as anteriores (histórico
    registrado depois) nunca entram na pontuação nem no ritmo, que começam no primeiro período
    completo depois da criação.
    """
    marks: dict[int, list[score.Mark]] = {habit_id: [] for habit_id in habit_ids}
    if not marks:
        return marks
    query = select(
        models.Mark.habit_id,
        models.Mark.marked_at,
        models.Mark.duration_minutes,
        models.Mark.cost_cents,
    ).where(models.Mark.habit_id.in_(marks))
    if since_creation:
        query = query.join(models.Habit, models.Habit.id == models.Mark.habit_id).where(
            models.Mark.marked_at >= models.Habit.created_at
        )
    for habit_id, marked_at, duration_minutes, cost_cents in session.execute(query):
        marks[habit_id].append(
            score.Mark(
                marked_at=marked_at, duration_minutes=duration_minutes, cost_cents=cost_cents
            )
        )
    return marks


def load_pauses(session: Session, habit_ids: Collection[int]) -> dict[int, list[score.Pause]]:
    """Pausas de cada hábito (todos os ids presentes na resposta, mesmo sem pausa)."""
    pauses: dict[int, list[score.Pause]] = {habit_id: [] for habit_id in habit_ids}
    if not pauses:
        return pauses
    query = select(
        models.HabitPause.habit_id, models.HabitPause.started_at, models.HabitPause.ended_at
    ).where(models.HabitPause.habit_id.in_(pauses))
    for habit_id, started_at, ended_at in session.execute(query):
        pauses[habit_id].append(score.Pause(started_at=started_at, ended_at=ended_at))
    return pauses


def evaluate_habits(
    session: Session, habits: Iterable[models.Habit], tz: ZoneInfo, *, now: datetime
) -> dict[int, score.Evaluation]:
    """`score.evaluate` de cada hábito, por id, com duas consultas no total.

    Avalia todos os hábitos recebidos; mostrar ou não a pontuação (`score_enabled`) é decisão de
    quem chama.
    """
    by_id = {habit.id: habit for habit in habits}
    marks = load_marks(session, by_id, since_creation=True)
    pauses = load_pauses(session, by_id)
    return {
        habit_id: score.evaluate(to_score_habit(habit), marks[habit_id], pauses[habit_id], tz, now)
        for habit_id, habit in by_id.items()
    }
