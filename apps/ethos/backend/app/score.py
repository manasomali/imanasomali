"""Pontuação e checagem de meta dos hábitos, usada pela tela e pelos alertas.

Funções puras: não abrem banco nem leem o relógio por conta própria. Quem chama
monta as estruturas abaixo a partir dos modelos e passa o fuso de quem vê
(`users.timezone`) e, se quiser, o instante "agora" (padrão: `datetime.now(UTC)`).

Entrada (dataclasses imutáveis, todos os instantes com fuso, de preferência UTC;
instante sem fuso é recusado com `ValueError`):

- `Habit`: a configuração atual do hábito.
  - `goal_type`: `"min"`, `"max"` ou `"exact"`; `goal_count`: o N da meta
    (N ≥ 1, exceto em `"max"`, que aceita N = 0).
  - `goal_period`: `"week"` (semana ISO, começa na segunda), `"month"` ou `"year"`.
  - `multi_mark`: várias marcações por dia; desligado é "toggle".
  - `duration_enabled` e `duration_minutes` (≥ 1 quando a duração está ligada).
  - `score_threshold`: limite de sucesso, de 1 a 100.
  - `cost_enabled`, `cost_limit_cents` (opcional, ≥ 0) e `cost_limit_period`
    (obrigatório quando há limite).
  - `created_at` e `archived_at` (`None` quando não está arquivado).
- `Mark`: `marked_at`, `duration_minutes` e `cost_cents` da marcação (os dois
  últimos opcionais e ≥ 0).
- `Pause`: `started_at` e `ended_at` (`None` enquanto a pausa está aberta). A
  pausa vale no intervalo `[started_at, ended_at)`, então pausa de duração zero
  não pausa nada, e retomar exatamente na virada do período não tira o período
  seguinte da pontuação.

Saída:

- `evaluate()` é a função única da pontuação e do ritmo. Devolve `Evaluation`:
  - `periods`: os períodos considerados, do mais antigo ao mais novo, cada um com
    valor, meta cumprida e gasto;
  - `score`: 0 a 100, ou `None` ("sem dados") quando nenhum período é considerado
    (ex.: todos pausados, ou `now` antes da criação);
  - `success`: `score >= score_threshold`, ou `None` junto com "sem dados";
  - `pace`: o ritmo do período atual, para o alerta de meta, ou `None` quando o
    alerta não deve ser avaliado (período da criação, pausa no período, arquivado).
  A tela usa `periods`, `score` e `success`; os alertas, `pace`. Mostrar ou não a
  pontuação (`score_enabled`) é decisão de quem chama.
- `check_cost()`: gasto do período de limite atual, para o alerta de custo.
- `summarize_periods()`: valor, meta e gasto de cada período de um intervalo de
  datas (relatório), sem filtro de criação ou de pausa.
- `period_containing()` / `period_at()`: os limites de um período no fuso dado.

Regras (ethos-plan.md, "meta e periodicidade", "pontuação", "pausar e arquivar",
"alertas" e "custo"):

- Valor do período: com duração ligada, a soma dos minutos das marcações,
  comparada com N * `duration_minutes`; senão, o número de marcações (várias por
  dia) ou o número de dias com pelo menos uma marcação (toggle).
- Períodos considerados: do período da criação até o atual, inclusive, sem os
  períodos que tiveram pausa. O atual entra com o valor de agora, mesmo
  incompleto: no meio da semana, uma meta mínima ainda não atingida conta como não
  cumprida, e a pontuação oscila ao longo do período. O da criação entra também
  (senão contaria enquanto é o atual e sumiria quando fecha). Arquivado congela em
  `archived_at`: o período do arquivamento passa a ser o "atual", com o valor até
  o arquivamento.
- Marcações antes de `created_at` (histórico registrado depois) e, no arquivado,
  depois de `archived_at` ficam fora da pontuação. No período atual entram todas as
  marcações dele: o backend recusa marcação mais de 1 min no futuro, então "até
  agora" é o que já foi marcado (o ritmo conta do mesmo jeito).
- Pontuação: porcentagem de períodos cumpridos, arredondada meio para cima com
  inteiros (`floor(x + 0.5)`), nunca com o `round` do Python.
- Ritmo: `esperado = N * segundos passados // segundos do período`, só inteiros.
  Os segundos são reais (em UTC), então semanas com mudança de horário de verão
  têm 167 h ou 169 h.
- Recursos desligados (duração, custo) são ignorados, mesmo com dados guardados.
"""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo

type GoalType = Literal["min", "max", "exact"]
type PeriodKind = Literal["week", "month", "year"]
type CostLevel = Literal["ok", "warning", "exceeded"]

GOAL_TYPES: frozenset[str] = frozenset({"min", "max", "exact"})
PERIOD_KINDS: frozenset[str] = frozenset({"week", "month", "year"})

# Alerta de custo: aviso quando o gasto do período chega a esta porcentagem do limite
COST_WARNING_PERCENT = 80

_ONE_SECOND = timedelta(seconds=1)


def _require_aware(name: str, value: datetime) -> None:
    # astimezone() num datetime sem fuso assume o fuso da máquina: recusa antes
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} precisa ter fuso")


def _require_tz(tz: tzinfo) -> None:
    # Com tz=None, astimezone() também cairia no fuso da máquina
    if not isinstance(tz, tzinfo):
        raise TypeError("tz precisa ser um fuso (zoneinfo.ZoneInfo)")


def _require_kind(kind: str) -> None:
    if kind not in PERIOD_KINDS:
        raise ValueError(f"período desconhecido: {kind!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class Habit:
    goal_type: GoalType
    goal_count: int
    goal_period: PeriodKind
    created_at: datetime
    multi_mark: bool = False
    duration_enabled: bool = False
    duration_minutes: int | None = None
    score_threshold: int = 70
    cost_enabled: bool = False
    cost_limit_cents: int | None = None
    cost_limit_period: PeriodKind | None = None
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.goal_type not in GOAL_TYPES:
            raise ValueError(f"tipo de meta desconhecido: {self.goal_type!r}")
        _require_kind(self.goal_period)
        minimum = 0 if self.goal_type == "max" else 1
        if self.goal_count < minimum:
            raise ValueError(f"goal_count precisa ser >= {minimum} em {self.goal_type!r}")
        if self.duration_enabled and (self.duration_minutes is None or self.duration_minutes < 1):
            raise ValueError("duration_minutes precisa ser >= 1 com a duração ligada")
        if not 1 <= self.score_threshold <= 100:
            raise ValueError("score_threshold precisa estar entre 1 e 100")
        if self.cost_limit_cents is not None:
            if self.cost_limit_cents < 0:
                raise ValueError("cost_limit_cents não pode ser negativo")
            if self.cost_limit_period is None:
                raise ValueError("cost_limit_period é obrigatório quando há limite de custo")
            _require_kind(self.cost_limit_period)
        _require_aware("created_at", self.created_at)
        if self.archived_at is not None:
            _require_aware("archived_at", self.archived_at)


@dataclass(frozen=True, slots=True, kw_only=True)
class Mark:
    marked_at: datetime
    duration_minutes: int | None = None
    cost_cents: int | None = None

    def __post_init__(self) -> None:
        _require_aware("marked_at", self.marked_at)
        if self.duration_minutes is not None and self.duration_minutes < 0:
            raise ValueError("duration_minutes não pode ser negativo")
        if self.cost_cents is not None and self.cost_cents < 0:
            raise ValueError("cost_cents não pode ser negativo")


@dataclass(frozen=True, slots=True, kw_only=True)
class Pause:
    started_at: datetime
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware("started_at", self.started_at)
        if self.ended_at is not None:
            _require_aware("ended_at", self.ended_at)
            if self.ended_at < self.started_at:
                raise ValueError("ended_at não pode ser antes de started_at")


@dataclass(frozen=True, slots=True)
class Period:
    """Um período no fuso de quem vê: `[first_day, end_day)` em datas locais e
    `[starts_at, ends_at)` nos instantes UTC correspondentes."""

    first_day: date
    end_day: date
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class PeriodResult:
    period: Period
    value: int
    met: bool
    # Soma de cost_cents das marcações; None com o custo desligado
    spend_cents: int | None


@dataclass(frozen=True, slots=True)
class Pace:
    period: Period
    value: int
    # N, ou N * duration_minutes com a duração ligada
    target: int
    # floor(target * fração do período que já passou)
    expected: int
    behind: bool
    # Regra do alerta de meta: min atrasado; max atingiu ou passou (e houve
    # alguma marcação); exact passou ou atrasado
    alert: bool


@dataclass(frozen=True, slots=True)
class Evaluation:
    periods: tuple[PeriodResult, ...]
    score: int | None
    success: bool | None
    pace: Pace | None


@dataclass(frozen=True, slots=True)
class CostCheck:
    period: Period
    spend_cents: int
    limit_cents: int
    level: CostLevel


def round_half_up(numerator: int, denominator: int) -> int:
    """`floor(numerator / denominator + 0.5)` com inteiros, para frações >= 0."""
    if numerator < 0 or denominator <= 0:
        raise ValueError("fração precisa ser >= 0 e ter denominador positivo")
    return (2 * numerator + denominator) // (2 * denominator)


def _period_first_day(day: date, kind: PeriodKind) -> date:
    if kind == "week":
        return day - timedelta(days=day.weekday())
    if kind == "month":
        return day.replace(day=1)
    return day.replace(month=1, day=1)


def _next_first_day(first_day: date, kind: PeriodKind) -> date:
    if kind == "week":
        return first_day + timedelta(days=7)
    if kind == "month":
        return date(first_day.year + first_day.month // 12, first_day.month % 12 + 1, 1)
    return date(first_day.year + 1, 1, 1)


def _local_midnight(day: date, tz: tzinfo) -> datetime:
    # Meia-noite que não existe (horário de verão que começa às 00:00) vira, com
    # fold=0, o instante da mudança: o primeiro instante do dia
    return datetime.combine(day, time(), tzinfo=tz).astimezone(UTC)


def period_containing(day: date, kind: PeriodKind, tz: ZoneInfo) -> Period:
    """O período do tipo `kind` que contém a data local `day`, no fuso `tz`."""
    _require_kind(kind)
    _require_tz(tz)
    first_day = _period_first_day(day, kind)
    end_day = _next_first_day(first_day, kind)
    return Period(first_day, end_day, _local_midnight(first_day, tz), _local_midnight(end_day, tz))


def period_at(instant: datetime, kind: PeriodKind, tz: ZoneInfo) -> Period:
    """O período do tipo `kind` que contém `instant`, visto no fuso `tz`."""
    _require_aware("instant", instant)
    _require_tz(tz)
    return period_containing(instant.astimezone(tz).date(), kind, tz)


def goal_target(habit: Habit) -> int:
    """O alvo da meta na unidade do valor do período (vezes, dias ou minutos)."""
    if habit.duration_enabled:
        # __post_init__ garante duration_minutes >= 1 com a duração ligada
        return habit.goal_count * (habit.duration_minutes or 0)
    return habit.goal_count


def goal_met(habit: Habit, value: int) -> bool:
    target = goal_target(habit)
    if habit.goal_type == "min":
        return value >= target
    if habit.goal_type == "max":
        return value <= target
    return value == target


type _Entry = tuple[date, Mark]


def _bucket(marks: Iterable[Mark], kind: PeriodKind, tz: tzinfo) -> dict[date, list[_Entry]]:
    """Agrupa as marcações pelo primeiro dia do período, com o dia local de cada uma."""
    buckets: dict[date, list[_Entry]] = {}
    for mark in marks:
        day = mark.marked_at.astimezone(tz).date()
        buckets.setdefault(_period_first_day(day, kind), []).append((day, mark))
    return buckets


def _summarize(habit: Habit, period: Period, entries: Sequence[_Entry]) -> PeriodResult:
    if habit.duration_enabled:
        # Marcação sem minutos (feita com a duração desligada) soma 0
        value = sum(mark.duration_minutes or 0 for _, mark in entries)
    elif habit.multi_mark:
        value = len(entries)
    else:
        # Toggle conta dias, mesmo que o hábito já tenha tido várias marcações por dia
        value = len({day for day, _ in entries})
    spend = sum(mark.cost_cents or 0 for _, mark in entries) if habit.cost_enabled else None
    return PeriodResult(period, value, goal_met(habit, value), spend)


def _paused(period: Period, pauses: Sequence[Pause]) -> bool:
    # Interseção não vazia de [started_at, ended_at) com [starts_at, ends_at)
    for pause in pauses:
        end = period.ends_at if pause.ended_at is None else min(pause.ended_at, period.ends_at)
        if max(pause.started_at, period.starts_at) < end:
            return True
    return False


def _scored_marks(habit: Habit, marks: Iterable[Mark]) -> Iterator[Mark]:
    """As marcações que a pontuação vê: a partir da criação e, no arquivado, até o arquivamento.
    O ritmo usa as mesmas: ele não avalia o período da criação nem o hábito arquivado."""
    archived_at = habit.archived_at
    for mark in marks:
        if mark.marked_at < habit.created_at:
            continue
        if archived_at is not None and mark.marked_at > archived_at:
            continue
        yield mark


def _resolve_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    _require_aware("now", now)
    return now.astimezone(UTC)


def _pace(
    habit: Habit,
    buckets: dict[date, list[_Entry]],
    pauses: Sequence[Pause],
    tz: ZoneInfo,
    now: datetime,
    creation: Period,
) -> Pace | None:
    if habit.archived_at is not None:
        return None
    current = period_at(now, habit.goal_period, tz)
    # O período da criação não foi vivido inteiro: o ritmo mediria desde antes do hábito
    if current.first_day <= creation.first_day or _paused(current, pauses):
        return None
    value = _summarize(habit, current, buckets.get(current.first_day, ())).value
    target = goal_target(habit)
    elapsed = (now - current.starts_at) // _ONE_SECOND
    total = (current.ends_at - current.starts_at) // _ONE_SECOND
    expected = target * elapsed // total
    behind = value < expected
    if habit.goal_type == "min":
        alert = behind
    elif habit.goal_type == "max":
        # Com N = 0, "atingiu N" valeria sem nenhuma marcação: só avisa quando houve uma
        alert = value >= max(target, 1)
    else:
        alert = value > target or behind
    return Pace(current, value, target, expected, behind, alert)


def evaluate(
    habit: Habit,
    marks: Iterable[Mark],
    pauses: Iterable[Pause],
    tz: ZoneInfo,
    now: datetime | None = None,
) -> Evaluation:
    """Pontuação, sucesso/falha e ritmo do hábito no fuso `tz`."""
    _require_tz(tz)
    now = _resolve_now(now)
    pauses = tuple(pauses)
    kind = habit.goal_period
    buckets = _bucket(_scored_marks(habit, marks), kind, tz)
    creation = period_at(habit.created_at, kind, tz)
    frozen_at = now if habit.archived_at is None else min(now, habit.archived_at)
    current = period_at(frozen_at, kind, tz)

    results: list[PeriodResult] = []
    period = creation
    while period.first_day <= current.first_day:
        if not _paused(period, pauses):
            results.append(_summarize(habit, period, buckets.get(period.first_day, ())))
        period = period_containing(period.end_day, kind, tz)

    score = round_half_up(100 * sum(r.met for r in results), len(results)) if results else None
    success = None if score is None else score >= habit.score_threshold
    pace = _pace(habit, buckets, pauses, tz, now, creation)
    return Evaluation(tuple(results), score, success, pace)


def check_cost(
    habit: Habit,
    marks: Iterable[Mark],
    pauses: Iterable[Pause],
    tz: ZoneInfo,
    now: datetime | None = None,
) -> CostCheck | None:
    """Gasto do período de limite atual, ou `None` quando o alerta de custo não se
    aplica: custo desligado, sem limite, arquivado, período da criação ou pausa."""
    _require_tz(tz)
    now = _resolve_now(now)
    limit = habit.cost_limit_cents
    kind = habit.cost_limit_period
    if not habit.cost_enabled or limit is None or kind is None or habit.archived_at is not None:
        return None
    current = period_at(now, kind, tz)
    creation = period_at(habit.created_at, kind, tz)
    if current.first_day <= creation.first_day or _paused(current, tuple(pauses)):
        return None
    entries = _bucket(marks, kind, tz).get(current.first_day, ())
    spend = sum(mark.cost_cents or 0 for _, mark in entries)
    level: CostLevel
    if spend > limit:
        level = "exceeded"
    elif spend > 0 and spend * 100 >= limit * COST_WARNING_PERCENT:
        level = "warning"
    else:
        level = "ok"
    return CostCheck(current, spend, limit, level)


def summarize_periods(
    habit: Habit,
    marks: Iterable[Mark],
    tz: ZoneInfo,
    first_day: date,
    last_day: date,
) -> tuple[PeriodResult, ...]:
    """Valor, meta e gasto de cada período que toca `[first_day, last_day]` (datas
    locais, inclusivas). Não filtra criação nem pausa: isso é da pontuação."""
    _require_tz(tz)
    if last_day < first_day:
        raise ValueError("last_day não pode ser antes de first_day")
    kind = habit.goal_period
    buckets = _bucket(marks, kind, tz)
    results: list[PeriodResult] = []
    period = period_containing(first_day, kind, tz)
    while period.first_day <= last_day:
        results.append(_summarize(habit, period, buckets.get(period.first_day, ())))
        period = period_containing(period.end_day, kind, tz)
    return tuple(results)
