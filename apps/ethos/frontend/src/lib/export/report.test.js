import { describe, expect, it } from 'vitest';
import { habitFixture, markFixture } from '../../test/habits';
import { fullHabit, fullMark, progressItem, reportData } from '../../test/report';
import { ALL_OPTIONS, DEFAULT_OPTIONS } from './options';
import { buildReport, habitsPerDay } from './report';

const TODAY = '2026-03-20';

function weeks(...rows) {
  return rows.map(([first_day, last_day, value, met]) => ({ first_day, last_day, value, met }));
}

describe('buildReport', () => {
  it('keeps only the marks of the period, by local day', () => {
    const marks = [
      // 23:00 de 28/2 em São Paulo: fora
      markFixture({ id: 1, marked_at: '2026-03-01T02:00:00Z' }),
      markFixture({ id: 2, marked_at: '2026-03-01T15:00:00Z' }),
      markFixture({ id: 3, marked_at: '2026-03-01T18:30:00Z' }),
      markFixture({ id: 4, marked_at: '2026-03-31T23:00:00Z' }),
      // 1/4 01:00 local: fora
      markFixture({ id: 5, marked_at: '2026-04-01T04:00:00Z' }),
    ];
    const report = buildReport(
      reportData({ habits: [progressItem(habitFixture(), { marks })] }),
      DEFAULT_OPTIONS,
      { today: TODAY },
    );

    const [item] = report.habits;
    expect(item.marks.map((mark) => [mark.id, mark.date, mark.time])).toEqual([
      [2, '2026-03-01', '12:00'],
      [3, '2026-03-01', '15:30'],
      [4, '2026-03-31', '20:00'],
    ]);
    expect([...item.days]).toEqual([
      ['2026-03-01', 2],
      ['2026-03-31', 1],
    ]);
    expect(report).toMatchObject({ from: '2026-03-01', to: '2026-03-31', timezone: 'America/Sao_Paulo' });
  });

  it('counts only the closed goal periods', () => {
    const periods = weeks(
      ['2026-02-23', '2026-03-01', 3, true],
      ['2026-03-02', '2026-03-08', 1, false],
      ['2026-03-09', '2026-03-15', 4, true],
      // A semana de hoje (20/3) ainda não acabou
      ['2026-03-16', '2026-03-22', 5, true],
    );
    const [item] = buildReport(
      reportData({ habits: [progressItem(habitFixture(), { periods, marks: [] })] }),
      DEFAULT_OPTIONS,
      { today: TODAY },
    ).habits;

    expect(item.closedPeriods).toBe(3);
    expect(item.metPeriods).toBe(2);
    expect(item.periods).toBe(periods);
    expect(item.goal).toEqual({ type: 'min', count: 3, period: 'week', target: 3, unit: 'days' });
  });

  it('fills the chosen information of a habit with every feature on', () => {
    const costPeriods = [
      { first_day: '2026-02-01', last_day: '2026-02-28', spend_cents: 100, limit_percent: 5 },
      { first_day: '2026-03-01', last_day: '2026-03-31', spend_cents: 2500, limit_percent: 125 },
    ];
    const marks = [
      fullMark({ id: 1, marked_at: '2026-03-02T15:00:00Z' }),
      fullMark({ id: 2, marked_at: '2026-03-03T15:00:00Z', duration_minutes: null, cost_cents: null }),
    ];
    const [item] = buildReport(
      reportData({ habits: [progressItem(fullHabit(), { marks, cost_periods: costPeriods })] }),
      ALL_OPTIONS,
      { today: TODAY },
    ).habits;

    expect(item.score).toEqual({ value: 80, success: true, threshold: 70 });
    expect(item.reward).toBe('Pizza');
    expect(item.punishment).toBe('Run 5 km');
    expect(item.durationMinutes).toBe(30);
    expect(item.cost).toEqual({
      level: 'mark',
      cents: 500,
      limitCents: 2000,
      limitPeriod: 'month',
      spendCents: 1250,
      latestLimit: costPeriods[1],
    });
    expect(item.costPeriods).toBe(costPeriods);
    expect(item.goal.unit).toBe('minutes');
    expect(item.goal.target).toBe(90);
  });

  it('leaves out what was not chosen or is off in the habit', () => {
    const habit = fullHabit({ score: undefined, score_enabled: false, cost_enabled: false });
    const [item] = buildReport(
      reportData({
        habits: [progressItem(habit, { marks: [fullMark()], cost_periods: [] })],
      }),
      { ...ALL_OPTIONS, duration: false },
      { today: TODAY },
    ).habits;

    expect(item.score).toBeNull();
    // Recompensa e punição dependem da pontuação
    expect(item.reward).toBeNull();
    expect(item.punishment).toBeNull();
    expect(item.cost).toBeNull();
    expect(item.costPeriods).toBeNull();
    expect(item.durationMinutes).toBeNull();
    expect(item.show).toEqual({
      score: false,
      reward: false,
      punishment: false,
      cost: false,
      duration: false,
      note: true,
      author: true,
    });
  });

  it('shows "no data" when the score has no value yet', () => {
    const habit = fullHabit({ score: { value: null, success: null } });
    const [item] = buildReport(reportData({ habits: [progressItem(habit, { marks: [] })] }), ALL_OPTIONS, {
      today: TODAY,
    }).habits;
    expect(item.score).toEqual({ value: null, success: null, threshold: 70 });
  });

  it('picks the limit period of the end of the report, or of today', () => {
    const costPeriods = [
      { first_day: '2026-02-01', last_day: '2026-02-28', spend_cents: 100, limit_percent: 5 },
      { first_day: '2026-03-01', last_day: '2026-03-31', spend_cents: 300, limit_percent: 15 },
      { first_day: '2026-04-01', last_day: '2026-04-30', spend_cents: 0, limit_percent: 0 },
    ];
    const latest = (to, today) =>
      buildReport(
        reportData({ to, habits: [progressItem(fullHabit(), { marks: [], cost_periods: costPeriods })] }),
        ALL_OPTIONS,
        { today },
      ).habits[0].cost.latestLimit;

    expect(latest('2026-02-15', TODAY)).toBe(costPeriods[0]);
    // O relatório vai além de hoje: o período de hoje
    expect(latest('2026-04-30', TODAY)).toBe(costPeriods[1]);
    // Nenhum contém a data: o último
    expect(latest('2026-05-15', '2026-06-01')).toBe(costPeriods[2]);
    // Sem limite
    expect(
      buildReport(reportData({ habits: [progressItem(fullHabit(), { marks: [] })] }), ALL_OPTIONS, {
        today: TODAY,
      }).habits[0].cost.latestLimit,
    ).toBeNull();
  });

  it('counts the habits marked on each day', () => {
    const report = buildReport(
      reportData({
        habits: [
          progressItem(habitFixture({ id: 1 }), {
            marks: [markFixture({ id: 1, marked_at: '2026-03-02T15:00:00Z' })],
          }),
          progressItem(habitFixture({ id: 2 }), {
            marks: [
              markFixture({ id: 2, habit_id: 2, marked_at: '2026-03-02T16:00:00Z' }),
              markFixture({ id: 3, habit_id: 2, marked_at: '2026-03-02T17:00:00Z' }),
              markFixture({ id: 4, habit_id: 2, marked_at: '2026-03-03T17:00:00Z' }),
            ],
          }),
        ],
      }),
      DEFAULT_OPTIONS,
      { today: TODAY },
    );

    expect([...habitsPerDay(report)]).toEqual([
      ['2026-03-02', 2],
      ['2026-03-03', 1],
    ]);
  });
});
