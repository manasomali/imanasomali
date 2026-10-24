from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import time_machine
from hypothesis import given, settings
from hypothesis import strategies as st

from app.score import (
    GOAL_TYPES,
    PERIOD_KINDS,
    Habit,
    Mark,
    Pause,
    check_cost,
    evaluate,
    goal_target,
    period_at,
    period_containing,
    round_half_up,
    summarize_periods,
)

# America/Sao_Paulo não tem horário de verão desde 2019: UTC-3 o ano todo
SP = ZoneInfo("America/Sao_Paulo")
TOKYO = ZoneInfo("Asia/Tokyo")
NY = ZoneInfo("America/New_York")
KIRITIMATI = ZoneInfo("Pacific/Kiritimati")  # UTC+14
PAGO_PAGO = ZoneInfo("Pacific/Pago_Pago")  # UTC-11

# Segundas-feiras de referência
JAN_5 = date(2026, 1, 5)
JAN_12 = date(2026, 1, 12)
JAN_19 = date(2026, 1, 19)


def at(tz, *args):
    """Instante a partir do horário local em `tz`."""
    return datetime(*args, tzinfo=tz)


def noon(day, tz=SP):
    return datetime.combine(day, time(12), tzinfo=tz)


def make_habit(**overrides):
    # Padrão: "pelo menos 1x por semana", criado numa quinta (semana de 29/12/2025)
    fields = {
        "goal_type": "min",
        "goal_count": 1,
        "goal_period": "week",
        "created_at": noon(date(2026, 1, 1)),
    }
    fields.update(overrides)
    return Habit(**fields)


def weekly(pattern, **habit_fields):
    """Avalia um hábito semanal ("pelo menos 1x") com uma semana considerada por
    item de `pattern`, a partir de 05/01/2026; True = semana com marcação."""
    marks = [
        Mark(marked_at=noon(JAN_5 + timedelta(weeks=i))) for i, met in enumerate(pattern) if met
    ]
    now = noon(JAN_5 + timedelta(weeks=len(pattern), days=1))
    return evaluate(make_habit(**habit_fields), marks, [], SP, now)


# --- meta em cada tipo e período ---------------------------------------------

# (criação, primeiro dia do único período considerado, "agora")
PERIOD_SETUPS = {
    "week": (date(2026, 1, 1), JAN_5, date(2026, 1, 13)),
    "month": (date(2025, 12, 15), date(2026, 1, 5), date(2026, 2, 10)),
    "year": (date(2024, 6, 1), date(2025, 1, 5), date(2026, 3, 1)),
}


@pytest.mark.parametrize("kind", ["week", "month", "year"])
@pytest.mark.parametrize(
    ("goal_type", "marked_days", "expected_met"),
    [
        ("min", 2, False),
        ("min", 3, True),
        ("min", 4, True),
        ("max", 2, True),
        ("max", 3, True),
        ("max", 4, False),
        ("exact", 2, False),
        ("exact", 3, True),
        ("exact", 4, False),
    ],
)
def test_goal_table(kind, goal_type, marked_days, expected_met):
    created, first_day, now = PERIOD_SETUPS[kind]
    habit = make_habit(
        goal_type=goal_type, goal_count=3, goal_period=kind, created_at=noon(created)
    )
    marks = [Mark(marked_at=noon(first_day + timedelta(days=i))) for i in range(marked_days)]

    result = evaluate(habit, marks, [], SP, noon(now))

    assert len(result.periods) == 1
    assert result.periods[0].value == marked_days
    assert result.periods[0].met is expected_met
    assert result.score == (100 if expected_met else 0)


def test_monthly_periods_cross_december():
    habit = make_habit(goal_period="month", created_at=noon(date(2025, 11, 20)))
    marks = [Mark(marked_at=noon(date(2025, 12, 31))), Mark(marked_at=noon(date(2026, 1, 1)))]

    result = evaluate(habit, marks, [], SP, noon(date(2026, 2, 3)))

    assert [r.period.first_day for r in result.periods] == [date(2025, 12, 1), date(2026, 1, 1)]
    assert [r.period.end_day for r in result.periods] == [date(2026, 1, 1), date(2026, 2, 1)]
    assert [r.value for r in result.periods] == [1, 1]


# --- semana ISO, virada de ano, horário de verão e fusos ---------------------


def test_iso_week_53_crosses_the_year():
    assert date(2026, 12, 28).isocalendar()[:2] == (2026, 53)
    week = period_containing(date(2027, 1, 3), "week", SP)
    assert (week.first_day, week.end_day) == (date(2026, 12, 28), date(2027, 1, 4))

    habit = make_habit(goal_count=2, created_at=noon(date(2026, 12, 16)))
    marks = [Mark(marked_at=noon(date(2026, 12, 31))), Mark(marked_at=noon(date(2027, 1, 2)))]
    result = evaluate(habit, marks, [], SP, noon(date(2027, 1, 5)))

    assert [r.period.first_day for r in result.periods] == [date(2026, 12, 21), date(2026, 12, 28)]
    assert [r.value for r in result.periods] == [0, 2]
    assert result.score == 50


@pytest.mark.parametrize(
    ("marked_at", "expected_score"),
    [
        # 2027-01-01 02:30 em UTC, mas ainda 2026 em São Paulo
        (at(SP, 2026, 12, 31, 23, 30), 100),
        (at(SP, 2027, 1, 1, 0, 30), 0),
    ],
)
def test_year_boundary_uses_the_local_date(marked_at, expected_score):
    habit = make_habit(goal_period="year", created_at=at(SP, 2025, 5, 1))

    result = evaluate(
        habit, [Mark(marked_at=marked_at.astimezone(UTC))], [], SP, at(SP, 2027, 2, 1)
    )

    assert [r.period.first_day for r in result.periods] == [date(2026, 1, 1)]
    assert result.score == expected_score


def test_dst_weeks_have_their_real_length():
    spring = period_containing(date(2026, 3, 4), "week", NY)
    fall = period_containing(date(2026, 10, 28), "week", NY)

    assert spring.ends_at - spring.starts_at == timedelta(hours=167)
    assert fall.ends_at - fall.starts_at == timedelta(hours=169)
    assert spring.starts_at == datetime(2026, 3, 2, 5, tzinfo=UTC)
    assert spring.ends_at == datetime(2026, 3, 9, 4, tzinfo=UTC)


def test_dst_mark_on_sunday_night_stays_in_its_week():
    habit = make_habit(created_at=at(NY, 2026, 2, 18, 12))
    # Domingo 23:30 já em horário de verão: segunda 03:30 em UTC
    marks = [Mark(marked_at=at(NY, 2026, 3, 8, 23, 30).astimezone(UTC))]

    result = evaluate(habit, marks, [], NY, at(NY, 2026, 3, 10, 12))

    assert [(r.period.first_day, r.value) for r in result.periods] == [
        (date(2026, 2, 23), 0),
        (date(2026, 3, 2), 1),
    ]


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # 7 * 23h55 / 167 h = 1,002: só dá 1 com a semana de 167 h reais (com 168 h, 0)
        (at(NY, 2026, 3, 2, 23, 55), 1),
        (at(NY, 2026, 3, 2, 23, 50), 0),
    ],
)
def test_pace_uses_the_real_length_of_a_dst_week(now, expected):
    habit = make_habit(goal_count=7, created_at=at(NY, 2026, 2, 18, 12))

    pace = evaluate(habit, [], [], NY, now).pace

    assert pace.expected == expected
    assert pace.behind is (expected == 1)


@pytest.mark.parametrize(
    ("tz", "week_with_mark", "week_starts_at"),
    [
        # A mesma marcação (segunda 10:30 UTC) cai na terça em Kiritimati e no domingo
        # em Pago Pago, em semanas diferentes
        (KIRITIMATI, JAN_5, datetime(2026, 1, 4, 10, tzinfo=UTC)),
        (PAGO_PAGO, date(2025, 12, 29), datetime(2025, 12, 29, 11, tzinfo=UTC)),
    ],
)
def test_extreme_timezones(tz, week_with_mark, week_starts_at):
    habit = make_habit(created_at=datetime(2025, 12, 10, 12, tzinfo=UTC))
    marks = [Mark(marked_at=datetime(2026, 1, 5, 10, 30, tzinfo=UTC))]

    result = evaluate(habit, marks, [], tz, datetime(2026, 1, 20, 12, tzinfo=UTC))

    assert [r.period.first_day for r in result.periods] == [
        date(2025, 12, 15),
        date(2025, 12, 22),
        date(2025, 12, 29),
        JAN_5,
        JAN_12,
    ]
    met = [r.period for r in result.periods if r.met]
    assert [p.first_day for p in met] == [week_with_mark]
    assert met[0].starts_at == week_starts_at
    assert result.score == 20


def test_same_habit_in_two_timezones():
    habit = make_habit(created_at=datetime(2025, 12, 31, 12, tzinfo=UTC))
    marks = [
        Mark(marked_at=datetime(2026, 1, 7, 12, tzinfo=UTC)),
        # Domingo 20:00 em São Paulo, segunda 08:00 em Tóquio
        Mark(marked_at=at(SP, 2026, 1, 11, 20).astimezone(UTC)),
    ]
    now = datetime(2026, 1, 20, 12, tzinfo=UTC)

    in_sao_paulo = evaluate(habit, marks, [], SP, now)
    in_tokyo = evaluate(habit, marks, [], TOKYO, now)

    assert [r.value for r in in_sao_paulo.periods] == [2, 0]
    assert in_sao_paulo.score == 50
    assert [r.value for r in in_tokyo.periods] == [1, 1]
    assert in_tokyo.score == 100


# --- criação, período atual, pausa e arquivamento ----------------------------


def test_habit_created_today_has_no_data():
    now = at(SP, 2026, 1, 7, 15)
    habit = make_habit(created_at=now - timedelta(hours=1))

    result = evaluate(habit, [Mark(marked_at=now)], [], SP, now)

    assert result.periods == ()
    assert result.score is None
    assert result.success is None


def test_weekly_habit_created_on_wednesday_starts_on_the_next_monday():
    habit = make_habit(created_at=at(SP, 2026, 1, 7, 10))
    # A semana da criação está cumprida, mas não conta
    marks = [Mark(marked_at=at(SP, 2026, 1, 7, 11)), Mark(marked_at=at(SP, 2026, 1, 8, 11))]

    on_next_monday = evaluate(habit, marks, [], SP, at(SP, 2026, 1, 12, 10))
    a_week_later = evaluate(habit, marks, [], SP, at(SP, 2026, 1, 20, 10))

    assert on_next_monday.score is None
    assert [r.period.first_day for r in a_week_later.periods] == [JAN_12]
    assert a_week_later.score == 0


def test_habit_created_at_monday_midnight_skips_that_week_too():
    habit = make_habit(created_at=at(SP, 2026, 1, 5, 0, 0))
    marks = [Mark(marked_at=noon(JAN_5))]

    assert evaluate(habit, marks, [], SP, at(SP, 2026, 1, 13)).score is None
    later = evaluate(habit, marks, [], SP, at(SP, 2026, 1, 20))
    assert [r.period.first_day for r in later.periods] == [JAN_12]


def test_monthly_habit_created_on_the_first_has_no_data_next_month():
    habit = make_habit(goal_period="month", created_at=at(SP, 2026, 1, 1, 0, 0))
    marks = [Mark(marked_at=noon(date(2026, 1, 2)))]

    assert evaluate(habit, marks, [], SP, noon(date(2026, 2, 15))).score is None


def test_marks_before_creation_do_not_count():
    habit = make_habit(created_at=noon(date(2025, 12, 31)))
    # Histórico registrado antes da criação: semanas não consideradas
    marks = [Mark(marked_at=noon(date(2025, 12, 1))), Mark(marked_at=noon(date(2025, 12, 30)))]

    result = evaluate(habit, marks, [], SP, noon(date(2026, 1, 13)))

    assert [(r.period.first_day, r.value) for r in result.periods] == [(JAN_5, 0)]
    assert result.score == 0


def test_pause_in_the_middle_of_a_period_skips_it():
    marks = [Mark(marked_at=noon(JAN_5)), Mark(marked_at=noon(JAN_19))]
    pause = Pause(started_at=at(SP, 2026, 1, 14, 10), ended_at=at(SP, 2026, 1, 15, 10))
    now = noon(date(2026, 1, 27))

    without_pause = evaluate(make_habit(), marks, [], SP, now)
    with_pause = evaluate(make_habit(), marks, [pause], SP, now)

    assert without_pause.score == 67
    assert [r.period.first_day for r in with_pause.periods] == [JAN_5, JAN_19]
    assert with_pause.score == 100


def test_pause_edges():
    pauses = [
        # Retomada exatamente na segunda 00:00: só a semana de 05/01 fica fora
        Pause(started_at=at(SP, 2026, 1, 8, 9), ended_at=at(SP, 2026, 1, 12, 0)),
        # Pausa de duração zero não pausa nada
        Pause(started_at=at(SP, 2026, 1, 21, 9), ended_at=at(SP, 2026, 1, 21, 9)),
    ]

    result = evaluate(make_habit(), [], pauses, SP, noon(date(2026, 1, 27)))

    assert [r.period.first_day for r in result.periods] == [JAN_12, JAN_19]


def test_open_pause_skips_every_period_after_it_and_the_pace():
    pause = Pause(started_at=at(SP, 2026, 1, 14, 10))

    result = evaluate(make_habit(), [Mark(marked_at=noon(JAN_5))], [pause], SP, noon(JAN_19))

    assert [r.period.first_day for r in result.periods] == [JAN_5]
    assert result.pace is None


def test_archived_habit_freezes_on_the_archive_date():
    habit = make_habit(archived_at=at(SP, 2026, 1, 21, 10))
    marks = [
        Mark(marked_at=noon(JAN_5)),
        # Depois do arquivamento: não entram
        Mark(marked_at=noon(date(2026, 1, 26))),
        Mark(marked_at=noon(date(2026, 2, 2))),
    ]

    soon = evaluate(habit, marks, [], SP, noon(date(2026, 2, 10)))
    much_later = evaluate(habit, marks, [], SP, noon(date(2027, 6, 1)))

    assert soon == much_later
    assert [r.period.first_day for r in soon.periods] == [JAN_5, JAN_12]
    assert soon.score == 50
    assert soon.pace is None


def test_now_before_creation_has_no_data_and_no_pace():
    habit = make_habit(created_at=noon(JAN_19))

    result = evaluate(habit, [], [], SP, noon(JAN_12))

    assert result.score is None
    assert result.pace is None


# --- valor do período ---------------------------------------------------------


def test_toggle_counts_days_and_multi_counts_marks():
    # Três marcações no mesmo dia, de quando o hábito aceitava várias por dia
    marks = [Mark(marked_at=at(SP, 2026, 1, 6, hour)) for hour in (8, 12, 20)]
    now = noon(date(2026, 1, 13))

    toggle = evaluate(make_habit(goal_count=2), marks, [], SP, now)
    multi = evaluate(make_habit(goal_count=2, multi_mark=True), marks, [], SP, now)

    assert (toggle.periods[0].value, toggle.periods[0].met) == (1, False)
    assert (multi.periods[0].value, multi.periods[0].met) == (3, True)


@pytest.mark.parametrize(
    ("goal_type", "minutes", "expected_met"),
    [
        # Exemplo do plano: "meditar 40 min, 1x por semana, mínimo" com 2 * 20 min
        ("min", [20, 20], True),
        ("min", [20], False),
        ("exact", [20, 20], True),
        ("exact", [30, 20], False),
        ("max", [20, 20], True),
        ("max", [20, 21], False),
    ],
)
def test_duration_compares_the_sum_of_minutes(goal_type, minutes, expected_met):
    habit = make_habit(goal_type=goal_type, duration_enabled=True, duration_minutes=40)
    marks = [Mark(marked_at=noon(JAN_5), duration_minutes=m) for m in minutes]

    result = evaluate(habit, marks, [], SP, noon(JAN_12))

    assert goal_target(habit) == 40
    assert result.periods[0].value == sum(minutes)
    assert result.periods[0].met is expected_met


def test_disabled_features_are_ignored():
    marks = [
        Mark(marked_at=noon(JAN_5), duration_minutes=90, cost_cents=500),
        Mark(marked_at=noon(date(2026, 1, 6)), cost_cents=250),
    ]
    now = noon(JAN_12)

    plain = evaluate(make_habit(goal_count=2), marks, [], SP, now).periods[0]
    with_features = evaluate(
        make_habit(goal_count=2, duration_enabled=True, duration_minutes=45, cost_enabled=True),
        marks,
        [],
        SP,
        now,
    ).periods[0]

    # Duração e custo desligados: conta dias, sem gasto
    assert (plain.value, plain.met, plain.spend_cents) == (2, True, None)
    # Ligados: a marcação sem minutos soma 0 (90 + 0 = 2 * 45)
    assert (with_features.value, with_features.met, with_features.spend_cents) == (90, True, 750)


# --- pontuação, arredondamento e limite --------------------------------------


@pytest.mark.parametrize(
    ("pattern", "expected_score"),
    [
        ([True] + [False] * 39, 3),  # 2,5%
        ([True] * 5 + [False] * 3, 63),  # 62,5%
        ([True] * 2 + [False], 67),
        ([True] + [False] * 2, 33),
    ],
)
def test_score_rounds_half_up(pattern, expected_score):
    assert weekly(pattern).score == expected_score


def test_round_half_up():
    assert round_half_up(1, 2) == 1  # o round do Python daria 0
    assert round_half_up(5, 2) == 3  # e aqui 2
    assert round_half_up(0, 7) == 0
    assert round_half_up(7, 7) == 1
    with pytest.raises(ValueError, match="denominador"):
        round_half_up(1, 0)
    with pytest.raises(ValueError, match="denominador"):
        round_half_up(-1, 2)


@pytest.mark.parametrize(
    ("pattern", "threshold", "expected_score", "expected_success"),
    [
        ([True] * 7 + [False] * 3, 70, 70, True),
        ([True] * 9 + [False] * 4, 70, 69, False),
        ([True] * 7 + [False] * 3, 71, 70, False),
        ([True], 100, 100, True),
        ([False], 1, 0, False),
    ],
)
def test_success_threshold(pattern, threshold, expected_score, expected_success):
    result = weekly(pattern, score_threshold=threshold)

    assert result.score == expected_score
    assert result.success is expected_success


# --- max com N = 0 ------------------------------------------------------------


def test_max_zero_fails_with_any_mark():
    habit = make_habit(goal_type="max", goal_count=0)

    result = evaluate(habit, [Mark(marked_at=noon(JAN_5))], [], SP, noon(date(2026, 1, 20)))

    assert [(r.value, r.met) for r in result.periods] == [(1, False), (0, True)]
    assert result.score == 50


# --- ritmo (alertas) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected", "behind"),
    [
        (at(SP, 2026, 1, 6, 23, 0), 0, False),  # terça 23:00: 3 * 47/168 = 0,8
        (at(SP, 2026, 1, 7, 7, 59, 59), 0, False),
        (at(SP, 2026, 1, 7, 8, 0), 1, True),  # quarta 08:00: 3 * 56/168 = 1 exato
        (at(SP, 2026, 1, 7, 12, 0), 1, True),
    ],
)
def test_pace_three_times_a_week(now, expected, behind):
    habit = make_habit(goal_count=3, created_at=noon(date(2025, 12, 20)))

    pace = evaluate(habit, [], [], SP, now).pace

    assert pace.period.first_day == JAN_5
    assert (pace.value, pace.target, pace.expected) == (0, 3, expected)
    assert pace.behind is behind
    assert pace.alert is behind


def test_pace_with_a_mark_is_not_behind():
    habit = make_habit(goal_count=3, created_at=noon(date(2025, 12, 20)))
    marks = [Mark(marked_at=at(SP, 2026, 1, 6, 9))]

    pace = evaluate(habit, marks, [], SP, at(SP, 2026, 1, 7, 12)).pace

    assert (pace.value, pace.behind, pace.alert) == (1, False, False)


def test_pace_is_not_evaluated_in_the_creation_period():
    habit = make_habit(goal_count=3, created_at=at(SP, 2026, 1, 5, 8))

    # Atrasado na quarta, mas a semana é a da criação
    assert evaluate(habit, [], [], SP, at(SP, 2026, 1, 7, 12)).pace is None


@pytest.mark.parametrize(
    ("goal_type", "goal_count", "marks_this_week", "expected_alert"),
    [
        ("max", 0, 0, False),
        ("max", 0, 1, True),
        ("max", 3, 2, False),
        ("max", 3, 3, True),
        ("max", 3, 4, True),
        ("exact", 2, 3, True),  # passou de N
        ("exact", 2, 0, True),  # sexta sem marcação: atrasado (2 * 4,5/7 = 1)
        ("exact", 2, 1, False),
        ("min", 2, 0, True),
        ("min", 2, 1, False),
    ],
)
def test_pace_alert_rules(goal_type, goal_count, marks_this_week, expected_alert):
    habit = make_habit(
        goal_type=goal_type,
        goal_count=goal_count,
        multi_mark=True,
        created_at=noon(date(2025, 12, 20)),
    )
    marks = [Mark(marked_at=at(SP, 2026, 1, 5, 9))] * marks_this_week

    pace = evaluate(habit, marks, [], SP, at(SP, 2026, 1, 9, 12)).pace

    assert pace.value == marks_this_week
    assert pace.alert is expected_alert


def test_pace_with_duration_uses_minutes():
    habit = make_habit(
        goal_count=2,
        duration_enabled=True,
        duration_minutes=30,
        created_at=noon(date(2025, 12, 20)),
    )
    marks = [Mark(marked_at=at(SP, 2026, 1, 5, 9), duration_minutes=25)]

    # Quinta 00:00: 60 min * 3/7 = 25
    pace = evaluate(habit, marks, [], SP, at(SP, 2026, 1, 8, 0)).pace

    assert (pace.value, pace.target, pace.expected, pace.behind) == (25, 60, 25, False)


# --- custo ----------------------------------------------------------------------


def cost_habit(**overrides):
    fields = {
        "cost_enabled": True,
        "cost_limit_cents": 1000,
        "cost_limit_period": "month",
        "created_at": noon(date(2025, 12, 15)),
    }
    fields.update(overrides)
    return make_habit(**fields)


@pytest.mark.parametrize(
    ("costs", "expected_level"),
    [
        ([], "ok"),
        ([300, None, 499], "ok"),
        ([800], "warning"),
        ([500, 500], "warning"),
        ([1001], "exceeded"),
    ],
)
def test_cost_levels(costs, expected_level):
    marks = [Mark(marked_at=noon(date(2026, 1, 10)), cost_cents=c) for c in costs]
    # Gasto do mês anterior não entra no mês atual
    marks.append(Mark(marked_at=noon(date(2025, 12, 31)), cost_cents=5000))

    check = check_cost(cost_habit(), marks, [], SP, noon(date(2026, 1, 20)))

    assert check.period.first_day == date(2026, 1, 1)
    assert check.spend_cents == sum(c or 0 for c in costs)
    assert check.limit_cents == 1000
    assert check.level == expected_level


@pytest.mark.parametrize(("cost", "expected_level"), [(0, "ok"), (1, "exceeded")])
def test_cost_limit_zero(cost, expected_level):
    habit = cost_habit(cost_limit_cents=0)
    marks = [Mark(marked_at=noon(date(2026, 1, 10)), cost_cents=cost)]

    assert check_cost(habit, marks, [], SP, noon(date(2026, 1, 20))).level == expected_level


@pytest.mark.parametrize(
    ("overrides", "pauses"),
    [
        ({"cost_enabled": False}, []),
        ({"cost_limit_cents": None, "cost_limit_period": None}, []),
        ({"archived_at": noon(date(2026, 1, 15))}, []),
        ({"created_at": noon(date(2026, 1, 3))}, []),
        ({}, [Pause(started_at=noon(date(2026, 1, 2)), ended_at=noon(date(2026, 1, 3)))]),
    ],
)
def test_cost_check_not_evaluated(overrides, pauses):
    marks = [Mark(marked_at=noon(date(2026, 1, 10)), cost_cents=5000)]

    assert check_cost(cost_habit(**overrides), marks, pauses, SP, noon(date(2026, 1, 20))) is None


# --- relatório por intervalo -----------------------------------------------------


def test_summarize_periods():
    habit = make_habit(goal_period="month", cost_enabled=True, created_at=noon(date(2026, 2, 10)))
    marks = [
        # Antes da criação: o relatório mostra mesmo assim
        Mark(marked_at=noon(date(2026, 1, 20)), cost_cents=100),
        Mark(marked_at=noon(date(2026, 3, 1)), cost_cents=200),
        Mark(marked_at=noon(date(2026, 4, 1)), cost_cents=400),
    ]

    results = summarize_periods(habit, marks, SP, date(2026, 1, 15), date(2026, 3, 2))

    assert [(r.period.first_day, r.value, r.met, r.spend_cents) for r in results] == [
        (date(2026, 1, 1), 1, True, 100),
        (date(2026, 2, 1), 0, False, 0),
        (date(2026, 3, 1), 1, True, 200),
    ]


def test_summarize_periods_rejects_an_inverted_range():
    with pytest.raises(ValueError, match="last_day"):
        summarize_periods(make_habit(), [], SP, JAN_12, JAN_5)


# --- "agora" padrão (tempo congelado) --------------------------------------------

FROZEN = datetime(2026, 1, 20, 15, tzinfo=UTC)


@time_machine.travel(FROZEN, tick=False)
def test_now_defaults_to_the_current_time():
    habit = cost_habit()
    marks = [Mark(marked_at=noon(JAN_5), cost_cents=900)]

    assert evaluate(habit, marks, [], SP) == evaluate(habit, marks, [], SP, FROZEN)
    assert check_cost(habit, marks, [], SP) == check_cost(habit, marks, [], SP, FROZEN)


@time_machine.travel(FROZEN, tick=False)
def test_habit_created_now_has_no_data():
    habit = make_habit(created_at=datetime.now(UTC))

    result = evaluate(habit, [Mark(marked_at=datetime.now(UTC))], [], SP)

    assert (result.score, result.success, result.pace) == (None, None, None)


# --- validação da entrada -----------------------------------------------------------

NAIVE = datetime(2026, 1, 5, 12)  # sem fuso de propósito


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"goal_type": "avg"}, "tipo de meta"),
        ({"goal_period": "day"}, "período desconhecido"),
        ({"goal_count": 0}, "goal_count"),
        ({"goal_type": "exact", "goal_count": 0}, "goal_count"),
        ({"goal_type": "max", "goal_count": -1}, "goal_count"),
        ({"duration_enabled": True}, "duration_minutes"),
        ({"duration_enabled": True, "duration_minutes": 0}, "duration_minutes"),
        ({"score_threshold": 0}, "score_threshold"),
        ({"score_threshold": 101}, "score_threshold"),
        ({"cost_limit_cents": -1, "cost_limit_period": "month"}, "negativo"),
        ({"cost_limit_cents": 100}, "cost_limit_period"),
        ({"cost_limit_cents": 100, "cost_limit_period": "day"}, "período desconhecido"),
        ({"created_at": NAIVE}, "created_at"),
        ({"archived_at": NAIVE}, "archived_at"),
    ],
)
def test_invalid_habit(overrides, message):
    with pytest.raises(ValueError, match=message):
        make_habit(**overrides)


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: Mark(marked_at=NAIVE), "marked_at"),
        (lambda: Mark(marked_at=noon(JAN_5), duration_minutes=-1), "duration_minutes"),
        (lambda: Mark(marked_at=noon(JAN_5), cost_cents=-1), "cost_cents"),
        (lambda: Pause(started_at=NAIVE), "started_at"),
        (lambda: Pause(started_at=noon(JAN_5), ended_at=NAIVE), "ended_at"),
        (lambda: Pause(started_at=noon(JAN_12), ended_at=noon(JAN_5)), "antes"),
    ],
)
def test_invalid_mark_and_pause(build, message):
    with pytest.raises(ValueError, match=message):
        build()


def test_invalid_call_arguments():
    with pytest.raises(TypeError, match="fuso"):
        evaluate(make_habit(), [], [], None, noon(JAN_12))
    with pytest.raises(TypeError, match="fuso"):
        period_containing(JAN_5, "week", None)
    with pytest.raises(TypeError, match="fuso"):
        period_at(noon(JAN_5), "week", None)
    with pytest.raises(ValueError, match="período desconhecido"):
        period_containing(JAN_5, "day", SP)
    with pytest.raises(ValueError, match="instant"):
        period_at(NAIVE, "week", SP)
    with pytest.raises(ValueError, match="now"):
        evaluate(make_habit(), [], [], SP, NAIVE)


def test_valid_inputs_are_accepted():
    habit = make_habit(
        goal_type="max",
        goal_count=0,
        cost_limit_cents=0,
        cost_limit_period="year",
        archived_at=noon(JAN_12),
    )
    pause = Pause(started_at=noon(JAN_5), ended_at=noon(JAN_5))

    assert habit.goal_count == 0
    assert pause.ended_at == pause.started_at


# --- propriedade -------------------------------------------------------------------

TIMEZONES = [SP, TOKYO, NY, KIRITIMATI, PAGO_PAGO, ZoneInfo("UTC")]
instants = st.datetimes(
    min_value=datetime(2024, 1, 1),  # limites do hypothesis são sem fuso
    max_value=datetime(2028, 12, 31),
    timezones=st.just(UTC),
)


@st.composite
def habits(draw):
    goal_type = draw(st.sampled_from(sorted(GOAL_TYPES)))
    duration = draw(st.none() | st.integers(1, 120))
    return Habit(
        goal_type=goal_type,
        goal_count=draw(st.integers(0 if goal_type == "max" else 1, 20)),
        goal_period=draw(st.sampled_from(sorted(PERIOD_KINDS))),
        created_at=draw(instants),
        multi_mark=draw(st.booleans()),
        duration_enabled=duration is not None,
        duration_minutes=duration,
        score_threshold=draw(st.integers(1, 100)),
        archived_at=draw(st.none() | instants),
    )


marks_strategy = st.lists(
    st.builds(Mark, marked_at=instants, duration_minutes=st.none() | st.integers(0, 600)),
    max_size=40,
)
pauses_strategy = st.lists(
    st.builds(
        lambda start, length: Pause(
            started_at=start, ended_at=None if length is None else start + length
        ),
        instants,
        st.none() | st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=60)),
    ),
    max_size=4,
)


@settings(max_examples=200, deadline=None)
@given(
    habit=habits(),
    marks=marks_strategy,
    pauses=pauses_strategy,
    tz=st.sampled_from(TIMEZONES),
    now=instants,
)
def test_score_is_always_between_0_and_100(habit, marks, pauses, tz, now):
    result = evaluate(habit, marks, pauses, tz, now)

    if result.periods:
        assert 0 <= result.score <= 100
        assert result.success is (result.score >= habit.score_threshold)
    else:
        assert result.score is None
        assert result.success is None
    if result.pace is not None:
        assert 0 <= result.pace.expected <= result.pace.target
