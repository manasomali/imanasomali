import { describe, expect, it } from 'vitest';
import { readFrontendFile } from '../../test/files';
import { habitFixture, markFixture } from '../../test/habits';
import { jsonBlock, validateSchema } from '../../test/jsonSchema';
import { fullHabit, fullMark, progressItem, reportData } from '../../test/report';
import { EXPORT_VERSION, toExportObject, toJson } from './json';
import { ALL_OPTIONS, normalizeOptions } from './options';
import { buildReport } from './report';

const SCHEMA = jsonBlock(readFrontendFile('src/lib/export/schema.md'));
const GENERATED_AT = new Date('2026-03-20T15:00:00Z');
const TODAY = '2026-03-20';

const PERIODS = [
  { first_day: '2026-02-23', last_day: '2026-03-01', value: 2, met: false, spend_cents: 1250 },
  { first_day: '2026-03-02', last_day: '2026-03-08', value: 90, met: true, spend_cents: 0 },
];
const COST_PERIODS = [
  { first_day: '2026-03-01', last_day: '2026-03-31', spend_cents: 1250, limit_percent: null },
];

function exported(habits, options = ALL_OPTIONS) {
  const report = buildReport(reportData({ habits }), options, { today: TODAY });
  return toExportObject(report, { generatedAt: GENERATED_AT });
}

function fullItem() {
  return progressItem(fullHabit(), {
    periods: PERIODS,
    cost_periods: COST_PERIODS,
    marks: [
      fullMark({ id: 1 }),
      fullMark({ id: 2, marked_at: '2026-03-04T15:00:00Z', author: null, note: null, cost_cents: null }),
    ],
  });
}

describe('JSON export', () => {
  it('follows the documented schema with every field', () => {
    const value = exported([
      fullItem(),
      progressItem(
        habitFixture({
          id: 2,
          code: null,
          status: 'archived',
          archived_at: '2026-03-10T12:00:00Z',
          role: 'viewer',
          score_enabled: true,
          score: { value: null, success: null },
        }),
        { marks: [markFixture({ id: 3, habit_id: 2 })], periods: [{ ...PERIODS[0], spend_cents: undefined }] },
      ),
    ]);

    expect(validateSchema(SCHEMA, value)).toEqual([]);
    expect(value).toMatchObject({
      version: EXPORT_VERSION,
      generated_at: '2026-03-20T15:00:00.000Z',
      timezone: 'America/Sao_Paulo',
      period: { from: '2026-03-01', to: '2026-03-31' },
      options: ALL_OPTIONS,
    });
    expect(value.habits[0]).toEqual({
      id: 1,
      name: 'Running',
      code: 'RUN',
      description: null,
      color: 'teal',
      status: 'active',
      role: 'owner',
      created_at: '2026-01-05T12:00:00Z',
      archived_at: null,
      goal: { type: 'min', count: 3, period: 'week', target: 90, unit: 'minutes' },
      multi_mark: true,
      duration_minutes: 30,
      score: { value: 80, success: true, threshold: 70 },
      reward: 'Pizza',
      punishment: 'Run 5 km',
      cost: { level: 'mark', cents: 500, limit_cents: 2000, limit_period: 'month', spend_cents: 1250 },
      marks: [
        {
          id: 1,
          marked_at: '2026-03-02T15:00:00Z',
          date: '2026-03-02',
          time: '12:00',
          author: { id: 1, email: 'ana@example.com' },
          duration_minutes: 30,
          cost_cents: 1250,
          note: 'Good run',
        },
        {
          id: 2,
          marked_at: '2026-03-04T15:00:00Z',
          date: '2026-03-04',
          time: '12:00',
          author: null,
          duration_minutes: 30,
          cost_cents: null,
          note: null,
        },
      ],
      periods: PERIODS,
      cost_periods: COST_PERIODS,
    });
  });

  it('follows the schema with only the required fields', () => {
    const value = exported([fullItem()], normalizeOptions({}));

    expect(validateSchema(SCHEMA, value)).toEqual([]);
    const [habit] = value.habits;
    for (const key of ['duration_minutes', 'score', 'reward', 'punishment', 'cost', 'cost_periods']) {
      expect(habit, key).not.toHaveProperty(key);
    }
    expect(habit.marks[0]).toEqual({ id: 1, marked_at: '2026-03-02T15:00:00Z', date: '2026-03-02', time: '12:00' });
    expect(habit.periods[0]).toEqual({ first_day: '2026-02-23', last_day: '2026-03-01', value: 2, met: false });
  });

  it('drops a field turned off in the report', () => {
    const value = exported([fullItem()], { ...ALL_OPTIONS, cost: false, note: false });

    expect(validateSchema(SCHEMA, value)).toEqual([]);
    expect(value.habits[0]).not.toHaveProperty('cost');
    expect(value.habits[0].marks[0]).not.toHaveProperty('cost_cents');
    expect(value.habits[0].marks[0]).not.toHaveProperty('note');
    expect(value.habits[0].periods[0]).not.toHaveProperty('spend_cents');
  });

  it('exports a custom color (ETH-49) as it is, within the schema', () => {
    const value = exported([progressItem(fullHabit({ color: '#0a1b2c' }), { marks: [] })]);

    expect(value.habits[0].color).toBe('#0a1b2c');
    expect(validateSchema(SCHEMA, value)).toEqual([]);
    for (const color of ['#0A1B2C', '#fff', 'magenta']) {
      value.habits[0].color = color;
      expect(validateSchema(SCHEMA, value), color).not.toEqual([]);
    }
  });

  it('is caught by the schema when it drifts', () => {
    const value = exported([fullItem()]);
    value.habits[0].secret = 'x';
    value.habits[0].marks[0].date = '02/03/2026';
    delete value.period.to;

    expect(validateSchema(SCHEMA, value)).toEqual([
      '$.period: falta "to"',
      '$.habits[0].marks[0].date: "02/03/2026" não casa com ^\\d{4}-\\d{2}-\\d{2}$',
      '$.habits[0]: campo extra "secret"',
    ]);
  });

  it('writes indented text ending with a line break', () => {
    const report = buildReport(reportData({ habits: [] }), ALL_OPTIONS, { today: TODAY });
    const text = toJson(report, { generatedAt: GENERATED_AT });

    expect(text.endsWith('}\n')).toBe(true);
    expect(JSON.parse(text)).toEqual(toExportObject(report, { generatedAt: GENERATED_AT }));
    expect(text).toContain('\n  "version": 1,');
  });
});

describe('schema validator', () => {
  it('checks every keyword it supports', () => {
    const schema = {
      $defs: { small: { type: 'integer', minimum: 1, maximum: 3 } },
      type: 'object',
      properties: {
        a: { $ref: '#/$defs/small' },
        b: { type: ['string', 'null'], minLength: 2 },
        c: { oneOf: [{ type: 'string' }, { type: 'null' }] },
        d: { type: 'array', items: { enum: ['x'] } },
        e: { const: 1 },
        f: { type: 'number' },
      },
    };

    expect(validateSchema(schema, { a: 2, b: null, c: 'x', d: ['x'], e: 1, f: 1.5 })).toEqual([]);
    expect(validateSchema(schema, { a: 0, b: 'x', c: 1, d: ['y'], e: 2, f: 'n' })).toEqual([
      '$.a: < 1',
      '$.b: menor que 2',
      '$.c: casa com 0 opções do oneOf',
      '$.d[0]: y fora do enum',
      '$.e: esperava 1',
      '$.f: esperava number, veio string',
    ]);
    expect(validateSchema(schema, { a: 4 })).toEqual(['$.a: > 3']);
    expect(() => validateSchema({ format: 'date' }, 'x')).toThrow('format');
    expect(() => validateSchema({ $ref: '#/$defs/none' }, 'x')).toThrow('$ref');
    expect(() => jsonBlock('no block')).toThrow();
  });
});
