// Modelo do relatório: junta a resposta do GET /habits/progress com as marcações do período e as
// informações escolhidas. A tela, o CSV, o JSON e a imagem partem daqui, então todos mostram os
// mesmos números.
//
// Entrada (`data`, de fetchReportData em src/api/report.js):
//   {from, to, timezone, habits: [{habit, goal_target, periods, cost_periods?, marks_range, marks}]}
// com `habit` o HabitOut, `periods`/`cost_periods` como a API manda (períodos inteiros que tocam o
// intervalo) e `marks` os MarkOut do hábito (podem vir marcações fora do período: ficam de fora).
//
// Contas feitas aqui, só com as marcações do período (as pontas do intervalo cortam os períodos
// da meta, então os totais não saem dos `periods`): marcações, dias marcados, minutos e gasto.
// Os períodos da meta contam só os encerrados (último dia antes de hoje): o atual ainda não acabou.

import { localDate, localTime } from '../time';
import { normalizeOptions, visibleFields } from './options';

function goalUnit(habit) {
  if (habit.duration_enabled) return 'minutes';
  return habit.multi_mark ? 'marks' : 'days';
}

// Período do limite de custo mostrado: o que contém o fim do relatório (ou hoje, se o relatório
// vai além de hoje); sem ele, o último
function latestLimit(costPeriods, to, today) {
  if (!costPeriods || costPeriods.length === 0) return null;
  const reference = to < today ? to : today;
  return (
    costPeriods.find((period) => period.first_day <= reference && reference <= period.last_day)
    ?? costPeriods[costPeriods.length - 1]
  );
}

function buildHabit(item, options, { from, to, timezone }, today) {
  const { habit } = item;
  const show = visibleFields(habit, options);
  const marks = [];
  const days = new Map();
  let minutes = 0;
  let spend = 0;
  for (const mark of item.marks) {
    const date = localDate(mark.marked_at, timezone);
    if (date < from || date > to) continue;
    marks.push({
      id: mark.id,
      marked_at: mark.marked_at,
      date,
      time: localTime(mark.marked_at, timezone),
      author: mark.author,
      duration_minutes: mark.duration_minutes,
      cost_cents: mark.cost_cents,
      note: mark.note,
    });
    days.set(date, (days.get(date) ?? 0) + 1);
    minutes += mark.duration_minutes ?? 0;
    spend += mark.cost_cents ?? 0;
  }
  const closed = item.periods.filter((period) => period.last_day < today);
  const costPeriods = show.cost ? (item.cost_periods ?? null) : null;

  return {
    habit,
    show,
    goal: {
      type: habit.goal_type,
      count: habit.goal_count,
      period: habit.goal_period,
      target: item.goal_target,
      unit: goalUnit(habit),
    },
    score: show.score
      ? {
          value: habit.score?.value ?? null,
          success: habit.score?.success ?? null,
          threshold: habit.score_threshold,
        }
      : null,
    reward: show.reward ? habit.reward : null,
    punishment: show.punishment ? habit.punishment : null,
    cost: show.cost
      ? {
          level: habit.cost_level,
          cents: habit.cost_cents,
          limitCents: habit.cost_limit_cents,
          limitPeriod: habit.cost_limit_period,
          spendCents: spend,
          latestLimit: latestLimit(costPeriods, to, today),
        }
      : null,
    durationMinutes: show.duration ? minutes : null,
    periods: item.periods,
    costPeriods,
    closedPeriods: closed.length,
    metPeriods: closed.filter((period) => period.met).length,
    marks,
    // Dia local → número de marcações (o mapa de calor)
    days,
  };
}

/**
 * O relatório pronto: `{from, to, timezone, options, habits}`, com cada hábito em
 * `{habit, show, goal, score, reward, punishment, cost, durationMinutes, periods, costPeriods,
 * closedPeriods, metPeriods, marks, days}`. Campo de informação não visível vem null.
 * `today`: hoje ("AAAA-MM-DD") no fuso do relatório.
 */
export function buildReport(data, options, { today }) {
  const normalized = normalizeOptions(options);
  return {
    from: data.from,
    to: data.to,
    timezone: data.timezone,
    options: normalized,
    habits: data.habits.map((item) => buildHabit(item, normalized, data, today)),
  };
}

/** Quantos hábitos do relatório têm marcação em cada dia: Map dia → número de hábitos. */
export function habitsPerDay(report) {
  const result = new Map();
  for (const item of report.habits) {
    for (const date of item.days.keys()) result.set(date, (result.get(date) ?? 0) + 1);
  }
  return result;
}
