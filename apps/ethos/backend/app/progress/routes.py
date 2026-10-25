"""`GET /habits/progress?from=&to=&habit_ids=` (ETH-23): os dados do relatório e do export.

Exige `CurrentUser`. `from` e `to`: datas locais `YYYY-MM-DD`, inclusivas, no fuso de quem pede,
cobrindo no máximo 5 anos (senão 422 `validation_error` com o campo). `habit_ids` (opcional,
repetido: `&habit_ids=1&habit_ids=2`, até 100): só esses hábitos; sem ele, todos os que o usuário
acessa, inclusive arquivados. Hábito sem acesso some da resposta. Regras em `service.py`.

Resposta: `{"from", "to", "timezone", "habits": [...]}`, por id do hábito, cada um com:

- `habit`: o mesmo objeto do `GET /habits/{id}` (configuração, `role`, `status` e, com a
  pontuação ligada, `score: {value, success}`; desligada, a chave nem aparece);
- `goal_target`: o alvo da meta na unidade de `value` (vezes, dias ou minutos);
- `periods`: `[{first_day, last_day, value, met, spend_cents}]`, os períodos da meta que tocam o
  intervalo, inteiros; `spend_cents` só com o custo ligado;
- `cost_periods`: só com o custo ligado e um limite, `[{first_day, last_day, spend_cents,
  limit_percent}]` nos períodos do limite (`limit_percent` null com limite 0);
- `marks_range`: `{first_day, last_day}`, os dias locais da primeira e da última marcação do
  hábito em todo o tempo (não só no intervalo), ou null sem marcação. O "exportar tudo" do front
  parte dele.

Este router fica antes do de `/habits` no `create_app`: senão `/habits/progress` cairia em
`/habits/{habit_id}` e daria 422.
"""

from datetime import date, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.auth.deps import CurrentUser
from app.db import SessionDep
from app.habits.routes import habit_out
from app.habits.schemas import HabitScore
from app.models import utcnow
from app.progress import service
from app.progress.schemas import (
    MAX_HABIT_IDS,
    CostPeriodOut,
    Day,
    HabitIdItem,
    HabitProgressOut,
    MarksRangeOut,
    PeriodOut,
    ProgressOut,
)
from app.progress.service import HabitProgress
from app.score import Period

router = APIRouter(prefix="/habits", tags=["progress"])

_ONE_DAY = timedelta(days=1)


def _days(period: Period) -> dict[str, date]:
    # Datas locais inclusivas: o end_day do score.py é o primeiro dia do período seguinte
    return {"first_day": period.first_day, "last_day": period.end_day - _ONE_DAY}


def progress_out(progress: HabitProgress) -> HabitProgressOut:
    score = None
    if progress.evaluation is not None:
        score = HabitScore(value=progress.evaluation.score, success=progress.evaluation.success)
    cost_periods = None
    if progress.cost_periods is not None:
        cost_periods = [
            CostPeriodOut(
                **_days(cost.period),
                spend_cents=cost.spend_cents,
                limit_percent=cost.limit_percent,
            )
            for cost in progress.cost_periods
        ]
    marks_range = None
    if progress.marks_range is not None:
        first_day, last_day = progress.marks_range
        marks_range = MarksRangeOut(first_day=first_day, last_day=last_day)
    return HabitProgressOut(
        habit=habit_out(progress.access, score),
        goal_target=progress.goal_target,
        periods=[
            PeriodOut(
                **_days(result.period),
                value=result.value,
                met=result.met,
                spend_cents=result.spend_cents,
            )
            for result in progress.periods
        ],
        cost_periods=cost_periods,
        marks_range=marks_range,
    )


@router.get("/progress")
def get_progress(
    user: CurrentUser,
    session: SessionDep,
    first_day: Annotated[Day, Query(alias="from")],
    last_day: Annotated[Day, Query(alias="to")],
    habit_ids: Annotated[list[HabitIdItem] | None, Query(max_length=MAX_HABIT_IDS)] = None,
) -> ProgressOut:
    service.check_range(first_day, last_day)
    timezone = user.timezone
    accesses = service.accessible_habits(session, user.id, habit_ids)
    progress = service.build_progress(
        session, accesses, ZoneInfo(timezone), first_day, last_day, now=utcnow()
    )
    return ProgressOut(
        first_day=first_day,
        last_day=last_day,
        timezone=timezone,
        habits=[progress_out(item) for item in progress],
    )
