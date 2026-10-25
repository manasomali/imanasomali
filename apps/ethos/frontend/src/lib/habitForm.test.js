import { describe, expect, it } from 'vitest';
import { habitFixture } from '../test/habits';
import { readFrontendFile } from '../test/files';
import {
  DEFAULT_SCORE_THRESHOLD,
  FORM_FIELDS,
  MAX_MARKS_PER_DAY,
  PERIOD_DAYS,
  TEXT_LIMITS,
  goalSummary,
  habitForm,
  habitPayload,
  hasForbiddenControls,
  maxGoalCount,
  minGoalCount,
  textLength,
  turnedOff,
  visibleFields,
} from './habitForm';

const NEW = habitForm(null, 'en');

function form(overrides = {}) {
  return { ...NEW, name: 'Running', ...overrides };
}

describe('constants match the backend', () => {
  it('uses the text limits and the default threshold of app/models.py', () => {
    const models = readFrontendFile('../backend/app/models.py');
    const constant = (name) => Number(new RegExp(`^${name} = (\\d+)$`, 'm').exec(models)[1]);

    expect(TEXT_LIMITS).toEqual({
      name: constant('HABIT_NAME_MAX_LENGTH'),
      code: constant('HABIT_CODE_MAX_LENGTH'),
      description: constant('HABIT_DESCRIPTION_MAX_LENGTH'),
      reward: constant('HABIT_REWARD_MAX_LENGTH'),
      punishment: constant('HABIT_PUNISHMENT_MAX_LENGTH'),
    });
    expect(DEFAULT_SCORE_THRESHOLD).toBe(constant('DEFAULT_SCORE_THRESHOLD'));
  });

  it('uses the period days of the service and the default MAX_MARKS_PER_DAY', () => {
    const service = readFrontendFile('../backend/app/habits/service.py');
    const config = readFrontendFile('../backend/app/config.py');

    expect(service).toMatch(
      `PERIOD_DAYS = {Period.WEEK: ${PERIOD_DAYS.week}, Period.MONTH: ${PERIOD_DAYS.month}, Period.YEAR: ${PERIOD_DAYS.year}}`,
    );
    expect(config).toMatch(new RegExp(`^\\s+max_marks_per_day: Limit = ${MAX_MARKS_PER_DAY}$`, 'm'));
  });

  it('knows every configuration field of the API', () => {
    const schemas = readFrontendFile('../backend/app/habits/schemas.py');
    const block = /^CONFIG_FIELDS = \(([\s\S]*?)\n\)/m.exec(schemas)[1];
    const fields = [...block.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);

    expect([...FORM_FIELDS].sort()).toEqual(fields.sort());
  });
});

describe('text rules', () => {
  it('counts Unicode characters without the spaces at the ends', () => {
    expect(textLength('  abc  ')).toBe(3);
    expect(textLength('🏃🏃')).toBe(2);
  });

  it('refuses control and bidi characters, allowing line breaks only in multiline texts', () => {
    expect(hasForbiddenControls('plain text')).toBe(false);
    expect(hasForbiddenControls('a\nb')).toBe(true);
    expect(hasForbiddenControls('a\nb\tc', { multiline: true })).toBe(false);
    expect(hasForbiddenControls('a\rb', { multiline: true })).toBe(true);
    expect(hasForbiddenControls('a‮b', { multiline: true })).toBe(true);
    expect(hasForbiddenControls('a⁦b')).toBe(true);
    expect(hasForbiddenControls('👩‍💻')).toBe(false);
  });
});

describe('goal limits', () => {
  it('accepts N = 0 only in the max type', () => {
    expect(minGoalCount('max')).toBe(0);
    expect(minGoalCount('min')).toBe(1);
    expect(minGoalCount('exact')).toBe(1);
  });

  it('caps N by the days of the period, times MAX_MARKS_PER_DAY with several marks per day', () => {
    expect(maxGoalCount('week', false)).toBe(7);
    expect(maxGoalCount('month', false)).toBe(28);
    expect(maxGoalCount('year', false)).toBe(365);
    expect(maxGoalCount('week', true)).toBe(7 * 999);
    expect(maxGoalCount('unknown', false)).toBe(7);
  });
});

describe('habitForm', () => {
  it('starts a new habit with every feature off and the score threshold at 70', () => {
    expect(NEW).toMatchObject({
      color: 'teal',
      custom_color: '',
      goal_type: 'min',
      goal_count: '1',
      goal_period: 'week',
      multi_mark: false,
      duration_enabled: false,
      notes_enabled: false,
      score_enabled: false,
      score_threshold: '70',
      cost_enabled: false,
      cost_level: 'habit',
      cost_limit_period: '',
    });
  });

  it('shows a saved habit as text, money in the language of the form', () => {
    const habit = habitFixture({
      description: null,
      duration_minutes: 40,
      cost_cents: 123450,
      cost_limit_cents: 5000,
      cost_limit_period: 'month',
      color: 'mauve',
    });

    expect(habitForm(habit, 'pt')).toMatchObject({
      code: 'RUN',
      description: '',
      color: 'teal',
      goal_count: '3',
      duration_minutes: '40',
      cost_cents: '1.234,50',
      cost_limit_cents: '50,00',
      cost_limit_period: 'month',
    });
    expect(habitForm(habitFixture({ code: null }), 'en')).toMatchObject({
      code: '',
      duration_minutes: '',
      cost_cents: '',
      cost_limit_period: '',
    });
  });

  it('keeps a custom color (ETH-49) as the color and as the last custom one', () => {
    expect(habitForm(habitFixture({ color: '#0a1b2c' }), 'en')).toMatchObject({
      color: '#0a1b2c',
      custom_color: '#0a1b2c',
    });
    expect(habitForm(habitFixture({ color: 'pink' }), 'en')).toMatchObject({ color: 'pink', custom_color: '' });
  });
});

describe('visibleFields and turnedOff', () => {
  it('hides the fields of the features that are off', () => {
    expect(visibleFields(NEW)).not.toContain('duration_minutes');
    expect(visibleFields(NEW)).not.toContain('reward');
    expect(visibleFields(NEW)).not.toContain('cost_cents');
    expect(visibleFields(form({ duration_enabled: true }))).toContain('duration_minutes');
    expect(visibleFields(form({ score_enabled: true }))).toEqual(
      expect.arrayContaining(['score_threshold', 'reward', 'punishment']),
    );
    expect(visibleFields(form({ cost_enabled: true }))).toEqual(
      expect.arrayContaining(['cost_level', 'cost_cents', 'cost_limit_cents', 'cost_limit_period']),
    );
  });

  it('lists the features saved on and now off', () => {
    const habit = habitFixture({ duration_enabled: true, cost_enabled: true, multi_mark: true });
    const current = habitForm(habit, 'en');

    expect(turnedOff(current, habit)).toEqual([]);
    expect(turnedOff({ ...current, duration_enabled: false, multi_mark: false }, habit)).toEqual([
      'multi_mark',
      'duration_enabled',
    ]);
    expect(turnedOff(NEW, null)).toEqual([]);
  });
});

describe('habitPayload: creating', () => {
  it('sends the configuration with the visible fields only', () => {
    const { values, errors } = habitPayload(
      form({ name: '  Running  ', code: ' run1 ', description: ' Every morning\n ', goal_count: '3' }),
      'en',
    );

    expect(errors).toEqual({});
    expect(values).toEqual({
      name: 'Running',
      code: 'RUN1',
      description: 'Every morning',
      color: 'teal',
      goal_type: 'min',
      goal_count: 3,
      goal_period: 'week',
      multi_mark: false,
      duration_enabled: false,
      notes_enabled: false,
      score_enabled: false,
      cost_enabled: false,
    });
  });

  it('turns empty optional texts into null', () => {
    const { values } = habitPayload(form({ code: '  ', description: '' }), 'en');

    expect(values.code).toBeNull();
    expect(values.description).toBeNull();
  });

  it('sends the fields of the features that are on', () => {
    const { values, errors } = habitPayload(
      form({
        duration_enabled: true,
        duration_minutes: '40',
        score_enabled: true,
        score_threshold: '80',
        reward: 'Pizza',
        punishment: '',
        cost_enabled: true,
        cost_level: 'mark',
        cost_cents: '',
        cost_limit_period: 'month',
        cost_limit_cents: '1,234.5',
      }),
      'en',
    );

    expect(errors).toEqual({});
    expect(values).toMatchObject({
      duration_minutes: 40,
      score_threshold: 80,
      reward: 'Pizza',
      punishment: null,
      cost_level: 'mark',
      cost_cents: null,
      cost_limit_cents: 123450,
      cost_limit_period: 'month',
    });
  });

  it('drops the limit amount when there is no limit period', () => {
    const { values, errors } = habitPayload(
      form({ cost_enabled: true, cost_cents: '8', cost_limit_cents: '100', cost_limit_period: '' }),
      'en',
    );

    expect(errors).toEqual({});
    expect(values).toMatchObject({ cost_cents: 800, cost_limit_cents: null, cost_limit_period: null });
  });

  it.each([
    [{ name: ' ' }, 'name', { code: 'required' }],
    [{ name: 'x'.repeat(61) }, 'name', { code: 'too_long', max: 60 }],
    [{ name: 'a‮b' }, 'name', { code: 'invalid_chars' }],
    [{ code: 'ab-1' }, 'code', { code: 'invalid_code' }],
    [{ code: 'ABCDE' }, 'code', { code: 'invalid_code' }],
    [{ code: 'ÁB' }, 'code', { code: 'invalid_code' }],
    [{ description: 'x'.repeat(501) }, 'description', { code: 'too_long', max: 500 }],
    [{ description: 'a\u0000b' }, 'description', { code: 'invalid_chars' }],
    [{ color: 'mauve' }, 'color', { code: 'required' }],
    [{ color: '#0A1B2C' }, 'color', { code: 'required' }],
    [{ color: '#fff' }, 'color', { code: 'required' }],
    [{ goal_type: 'most' }, 'goal_type', { code: 'required' }],
    [{ goal_period: 'day' }, 'goal_period', { code: 'required' }],
    [{ goal_count: '0' }, 'goal_count', { code: 'goal_range', min: 1, max: 7 }],
    [{ goal_count: '0', goal_type: 'exact' }, 'goal_count', { code: 'goal_range', min: 1, max: 7 }],
    [{ goal_count: '8' }, 'goal_count', { code: 'goal_range', min: 1, max: 7 }],
    [{ goal_count: '29', goal_period: 'month' }, 'goal_count', { code: 'goal_range', min: 1, max: 28 }],
    [{ goal_count: '1.5' }, 'goal_count', { code: 'goal_range', min: 1, max: 7 }],
    [{ goal_count: '' }, 'goal_count', { code: 'goal_range', min: 1, max: 7 }],
    [{ goal_count: '-1', goal_type: 'max' }, 'goal_count', { code: 'goal_range', min: 0, max: 7 }],
    [{ duration_enabled: true, duration_minutes: '' }, 'duration_minutes', { code: 'duration_range' }],
    [{ duration_enabled: true, duration_minutes: '1441' }, 'duration_minutes', { code: 'duration_range' }],
    [{ score_enabled: true, score_threshold: '0' }, 'score_threshold', { code: 'threshold_range', min: 1, max: 100 }],
    [{ score_enabled: true, score_threshold: '101' }, 'score_threshold', { code: 'threshold_range', min: 1, max: 100 }],
    [{ score_enabled: true, reward: 'x'.repeat(141) }, 'reward', { code: 'too_long', max: 140 }],
    [{ score_enabled: true, punishment: 'a\nb' }, 'punishment', { code: 'invalid_chars' }],
    [{ cost_enabled: true, cost_cents: '' }, 'cost_cents', { code: 'required' }],
    [{ cost_enabled: true, cost_cents: '12,50' }, 'cost_cents', { code: 'invalid_money' }],
    [{ cost_enabled: true, cost_level: 'day', cost_cents: '1' }, 'cost_level', { code: 'required' }],
    [
      { cost_enabled: true, cost_cents: '1', cost_limit_period: 'week', cost_limit_cents: '' },
      'cost_limit_cents',
      { code: 'required' },
    ],
    [
      { cost_enabled: true, cost_cents: '1', cost_limit_period: 'day', cost_limit_cents: '5' },
      'cost_limit_period',
      { code: 'required' },
    ],
  ])('refuses %j in %s', (overrides, field, error) => {
    const { values, errors } = habitPayload(form(overrides), 'en');

    expect(errors).toEqual({ [field]: error });
    expect(values).not.toHaveProperty(field);
  });

  it('accepts N = 0 in the max type and the ceiling of each period', () => {
    expect(habitPayload(form({ goal_type: 'max', goal_count: '0' }), 'en').errors).toEqual({});
    expect(habitPayload(form({ goal_count: '7' }), 'en').errors).toEqual({});
    expect(habitPayload(form({ goal_count: '365', goal_period: 'year' }), 'en').errors).toEqual({});
    expect(habitPayload(form({ goal_count: '6993', multi_mark: true }), 'en').errors).toEqual({});
  });

  it('does not check the hidden fields', () => {
    const { errors, values } = habitPayload(
      form({ duration_minutes: 'x', score_threshold: '0', reward: 'x'.repeat(200), cost_cents: 'x' }),
      'en',
    );

    expect(errors).toEqual({});
    expect(values).not.toHaveProperty('duration_minutes');
    expect(values).not.toHaveProperty('reward');
  });
});

describe('habitPayload: editing', () => {
  const habit = habitFixture({
    description: 'Mornings',
    duration_enabled: true,
    duration_minutes: 40,
    score_enabled: false,
    reward: 'Pizza',
    cost_enabled: true,
    cost_level: 'habit',
    cost_cents: 800,
    cost_limit_cents: 10000,
    cost_limit_period: 'month',
  });

  it('sends a custom color or a palette name, and never the last custom color', () => {
    const custom = { ...habitForm(habit, 'pt'), color: '#0a1b2c', custom_color: '#0a1b2c' };
    const back = { ...custom, color: 'pink' };

    expect(habitPayload(custom, 'pt', habit).values).toEqual({ color: '#0a1b2c' });
    expect(habitPayload(back, 'pt', habit).values).toEqual({ color: 'pink' });
    expect(habitPayload(custom, 'pt').values).toMatchObject({ color: '#0a1b2c' });
    expect(habitPayload(custom, 'pt').values).not.toHaveProperty('custom_color');
  });

  it('sends nothing when nothing changed', () => {
    expect(habitPayload(habitForm(habit, 'pt'), 'pt', habit)).toEqual({ values: {}, errors: {} });
  });

  it('sends only what changed, comparing values and not text', () => {
    const current = { ...habitForm(habit, 'pt'), name: 'Run', goal_count: '4', cost_cents: '8' };

    expect(habitPayload(current, 'pt', habit).values).toEqual({ name: 'Run', goal_count: 4 });
  });

  it('keeps the data of a feature turned off out of the request', () => {
    const current = { ...habitForm(habit, 'pt'), duration_enabled: false, duration_minutes: '50', cost_enabled: false };

    expect(habitPayload(current, 'pt', habit).values).toEqual({
      duration_enabled: false,
      cost_enabled: false,
    });
  });

  it('brings the saved values back when a feature is turned on again', () => {
    const current = { ...habitForm(habit, 'pt'), score_enabled: true };

    expect(current.reward).toBe('Pizza');
    expect(habitPayload(current, 'pt', habit).values).toEqual({ score_enabled: true });
  });

  it('clears the limit and its period together', () => {
    const current = { ...habitForm(habit, 'pt'), cost_limit_period: '' };

    expect(habitPayload(current, 'pt', habit).values).toEqual({
      cost_limit_cents: null,
      cost_limit_period: null,
    });
  });
});

describe('goalSummary', () => {
  it('describes the goal', () => {
    expect(goalSummary(form({ goal_count: '3' }))).toEqual({
      type: 'min',
      count: 3,
      period: 'week',
      never: false,
      totalMinutes: null,
    });
  });

  it('marks "at most 0" as never', () => {
    expect(goalSummary(form({ goal_type: 'max', goal_count: '0', goal_period: 'month' }))).toMatchObject({
      never: true,
      period: 'month',
    });
  });

  it('adds the total of minutes when the duration is on and valid', () => {
    expect(goalSummary(form({ goal_count: '3', duration_enabled: true, duration_minutes: '40' }))).toMatchObject({
      totalMinutes: 120,
    });
    expect(goalSummary(form({ duration_enabled: true, duration_minutes: '' })).totalMinutes).toBeNull();
    expect(
      goalSummary(form({ goal_type: 'max', goal_count: '0', duration_enabled: true, duration_minutes: '30' }))
        .totalMinutes,
    ).toBeNull();
  });

  it('gives null while N or the goal is invalid', () => {
    expect(goalSummary(form({ goal_count: '0' }))).toBeNull();
    expect(goalSummary(form({ goal_count: 'x' }))).toBeNull();
    expect(goalSummary(form({ goal_type: 'other' }))).toBeNull();
    expect(goalSummary(form({ goal_period: 'day' }))).toBeNull();
  });
});
