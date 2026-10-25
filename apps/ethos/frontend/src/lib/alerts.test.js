import { describe, expect, it } from 'vitest';
import {
  ALERT_HOURS,
  COST_WARNING_PERCENT,
  DEFAULT_HOUR,
  WEEKDAYS,
  alertErrors,
  alertForm,
  alertPayload,
  canFallBehind,
  firstAlertDay,
  formatHour,
  hasCostAlert,
  periodFirstDay,
  weeklyPaceStart,
} from './alerts';
import { readFrontendFile } from '../test/files';

const DEFAULT_ALERT = {
  goal_enabled: false,
  cost_enabled: false,
  hour: 20,
  frequency: 'daily',
  weekday: null,
  last_sent_at: null,
};

describe('alert rules shared with the backend', () => {
  it('uses the default hour and the cost warning of the API', () => {
    const service = readFrontendFile('../backend/app/alerts/service.py');
    const score = readFrontendFile('../backend/app/score.py');

    expect(/^DEFAULT_HOUR = (\d+)$/m.exec(service)[1]).toBe(String(DEFAULT_HOUR));
    expect(/^COST_WARNING_PERCENT = (\d+)$/m.exec(score)[1]).toBe(String(COST_WARNING_PERCENT));
  });

  it('offers every whole hour and every weekday of the API', () => {
    expect(ALERT_HOURS).toEqual([...Array(24).keys()]);
    expect(WEEKDAYS).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });
});

describe('alertForm', () => {
  it('starts from the saved configuration, as text for the selects', () => {
    expect(alertForm(DEFAULT_ALERT)).toEqual({
      goal_enabled: false,
      cost_enabled: false,
      hour: '20',
      frequency: 'daily',
      weekday: '',
    });
    expect(
      alertForm({ ...DEFAULT_ALERT, goal_enabled: true, cost_enabled: true, hour: 0, frequency: 'weekly', weekday: 6 }),
    ).toEqual({ goal_enabled: true, cost_enabled: true, hour: '0', frequency: 'weekly', weekday: '6' });
  });

  it('falls back to the defaults for values it does not know', () => {
    expect(alertForm({ goal_enabled: 'yes', hour: 24, frequency: 'hourly', weekday: 7 })).toEqual({
      goal_enabled: false,
      cost_enabled: false,
      hour: String(DEFAULT_HOUR),
      frequency: 'daily',
      weekday: '',
    });
    expect(alertForm({ ...DEFAULT_ALERT, hour: 9.5, weekday: -1 })).toMatchObject({ hour: '20', weekday: '' });
  });
});

describe('alertErrors and alertPayload', () => {
  const daily = { goal_enabled: true, cost_enabled: false, hour: '7', frequency: 'daily', weekday: '' };

  it('sends the whole configuration, without a weekday in the daily mode', () => {
    expect(alertErrors(daily)).toEqual({});
    expect(alertPayload({ ...daily, weekday: '3' })).toEqual({
      goal_enabled: true,
      cost_enabled: false,
      hour: 7,
      frequency: 'daily',
      weekday: null,
    });
  });

  it('requires the weekday in the weekly mode', () => {
    const weekly = { ...daily, frequency: 'weekly' };

    expect(alertErrors(weekly)).toEqual({ weekday: 'required' });
    expect(() => alertPayload(weekly)).toThrow(RangeError);
    expect(alertErrors({ ...weekly, weekday: '7' })).toEqual({ weekday: 'invalid' });
    expect(alertErrors({ ...weekly, weekday: '1.5' })).toEqual({ weekday: 'invalid' });
    expect(alertPayload({ ...weekly, weekday: '0' })).toEqual({
      goal_enabled: true,
      cost_enabled: false,
      hour: 7,
      frequency: 'weekly',
      weekday: 0,
    });
  });

  it('refuses hours and frequencies the API refuses', () => {
    for (const hour of ['', '24', '-1', '7.0', '007', 7]) {
      expect(alertErrors({ ...daily, hour })).toEqual({ hour: 'invalid' });
    }
    expect(alertErrors({ ...daily, hour: '0' })).toEqual({});
    expect(alertErrors({ ...daily, hour: '23' })).toEqual({});
    expect(alertErrors({ ...daily, frequency: 'monthly' })).toEqual({ frequency: 'invalid' });
  });
});

describe('hasCostAlert', () => {
  const habit = { cost_enabled: true, cost_limit_cents: 10000, cost_limit_period: 'month' };

  it('needs the cost turned on and a limit', () => {
    expect(hasCostAlert(habit)).toBe(true);
    expect(hasCostAlert({ ...habit, cost_enabled: false })).toBe(false);
    expect(hasCostAlert({ ...habit, cost_limit_cents: null, cost_limit_period: null })).toBe(false);
    expect(hasCostAlert({ ...habit, cost_limit_period: null })).toBe(false);
  });
});

describe('formatHour', () => {
  it('writes the hour as the language does', () => {
    expect(formatHour(20, 'pt')).toBe('20:00');
    expect(formatHour(0, 'pt')).toBe('00:00');
    expect(formatHour(20, 'en')).toBe('8:00 PM');
    expect(formatHour(8, 'en', 15)).toBe('8:15 AM');
  });

  it('refuses what is not an hour', () => {
    expect(() => formatHour(24, 'pt')).toThrow(RangeError);
    expect(() => formatHour(1.5, 'pt')).toThrow(RangeError);
    expect(() => formatHour(1, 'pt', 60)).toThrow(RangeError);
  });
});

describe('pace', () => {
  it('cannot fall behind with a goal of 1 in the period', () => {
    expect(canFallBehind(1)).toBe(false);
    expect(canFallBehind(0)).toBe(false);
    expect(canFallBehind(2)).toBe(true);
    expect(canFallBehind(2.5)).toBe(false);
    expect(weeklyPaceStart(1)).toBeNull();
  });

  it('finds when a week without marks falls behind', () => {
    // O exemplo do plano: 3x por semana fica atrasado a partir de quarta às 08:00 (56 h)
    expect(weeklyPaceStart(3)).toEqual({ weekday: 2, hour: 8, minute: 0 });
    // 2x: metade da semana, quinta ao meio-dia
    expect(weeklyPaceStart(2)).toEqual({ weekday: 3, hour: 12, minute: 0 });
    // 7x: um dia inteiro, terça à meia-noite
    expect(weeklyPaceStart(7)).toEqual({ weekday: 1, hour: 0, minute: 0 });
    // Minutos (duração ligada): 3 x 40 min = 120, ou seja, 84 min depois do começo da semana
    expect(weeklyPaceStart(120)).toEqual({ weekday: 0, hour: 1, minute: 24 });
    // Fração de segundo arredonda para cima: 604800 / 7000 = 86,4 s
    expect(weeklyPaceStart(7000)).toEqual({ weekday: 0, hour: 0, minute: 1 });
  });
});

describe('periods of the creation', () => {
  it('finds the first day of the week, month and year', () => {
    expect(periodFirstDay('2026-03-04', 'week')).toBe('2026-03-02');
    expect(periodFirstDay('2026-03-08', 'week')).toBe('2026-03-02');
    expect(periodFirstDay('2026-03-02', 'week')).toBe('2026-03-02');
    expect(periodFirstDay('2026-03-04', 'month')).toBe('2026-03-01');
    expect(periodFirstDay('2026-03-04', 'year')).toBe('2026-01-01');
    expect(() => periodFirstDay('2026-03-04', 'day')).toThrow(RangeError);
  });

  it('says from when the alert can fire while in the period of the creation', () => {
    // Criado numa quarta à noite em São Paulo (quinta em UTC)
    const created = '2026-03-05T01:00:00Z';
    const tz = 'America/Sao_Paulo';

    expect(firstAlertDay(created, 'week', tz, new Date('2026-03-06T12:00:00Z'))).toBe('2026-03-09');
    expect(firstAlertDay(created, 'week', tz, new Date('2026-03-09T02:59:00Z'))).toBe('2026-03-09');
    expect(firstAlertDay(created, 'week', tz, new Date('2026-03-09T03:00:00Z'))).toBeNull();
    expect(firstAlertDay(created, 'month', tz, new Date('2026-03-30T12:00:00Z'))).toBe('2026-04-01');
    expect(firstAlertDay(created, 'month', tz, new Date('2026-04-01T12:00:00Z'))).toBeNull();
    expect(firstAlertDay('2026-12-10T12:00:00Z', 'month', tz, new Date('2026-12-20T12:00:00Z'))).toBe('2027-01-01');
    expect(firstAlertDay(created, 'year', tz, new Date('2026-12-31T12:00:00Z'))).toBe('2027-01-01');
    expect(firstAlertDay(created, 'year', tz, new Date('2027-01-01T12:00:00Z'))).toBeNull();
  });

  it('uses the time zone of the person for the day of the creation', () => {
    // 2026-03-02 01:00 UTC ainda é domingo, 1º de março, em São Paulo: semana anterior
    const created = '2026-03-02T01:00:00Z';
    const now = new Date('2026-03-04T12:00:00Z');

    expect(firstAlertDay(created, 'week', 'America/Sao_Paulo', now)).toBeNull();
    expect(firstAlertDay(created, 'week', 'UTC', now)).toBe('2026-03-09');
  });
});
