import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { HttpResponse, http } from 'msw';
import { readFrontendFile } from '../test/files';
import { habitFixture, markFixture, mockHabitsApi } from '../test/habits';
import { jsonBlock, validateSchema } from '../test/jsonSchema';
import { fullHabit, fullMark, mockProgressApi, progressItem, readFileText, translator } from '../test/report';
import { api, server } from '../test/server';
import { afterMarksChanged, markKeys } from './marks';
import { MAX_PROGRESS_IDS, fetchProgress, reportKeys } from './progress';
import { exportAllFile, fetchAllReportData, fetchReportData } from './report';

const TZ = 'America/Sao_Paulo';
const NOW = new Date('2026-03-20T15:00:00Z');

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
}

function item(habit, range, extra = {}) {
  const value = progressItem(habit, {
    marks_range: range ? { first_day: range[0], last_day: range[1] } : null,
    ...extra,
  });
  // A API não manda marcações no progresso
  delete value.marks;
  return value;
}

function markRequests(requests) {
  return requests.filter((request) => request.path.endsWith('/marks'));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('fetchProgress', () => {
  it('asks for every habit without ids', async () => {
    const queries = mockProgressApi({ items: [item(habitFixture(), null)] });

    const body = await fetchProgress({ from: '2026-03-01', to: '2026-03-31' });

    expect(queries).toEqual([{ from: '2026-03-01', to: '2026-03-31', habit_ids: [] }]);
    expect(body.habits).toHaveLength(1);
  });

  it('splits more than 100 ids in several calls', async () => {
    const habits = Array.from({ length: 150 }, (_, index) => item(habitFixture({ id: index + 1 }), null));
    const queries = mockProgressApi({ items: habits });
    const ids = habits.map((value) => value.habit.id).reverse();

    const body = await fetchProgress({ from: '2026-03-01', to: '2026-03-31', habitIds: ids });

    expect(queries.map((query) => query.habit_ids.length)).toEqual([MAX_PROGRESS_IDS, 50]);
    expect(body.habits.map((value) => value.habit.id)).toEqual(ids.slice().reverse());
    expect(body.timezone).toBe(TZ);
  });

  it('answers without calling for an empty list', async () => {
    expect(await fetchProgress({ from: '2026-03-01', to: '2026-03-31', habitIds: [] })).toEqual({
      from: '2026-03-01',
      to: '2026-03-31',
      timezone: null,
      habits: [],
    });
  });
});

describe('fetchReportData', () => {
  it('reads the marks of the period by year, following the cursor, and only where there are marks', async () => {
    const running = habitFixture({ id: 1 });
    const empty = habitFixture({ id: 2, name: 'Read' });
    const old = habitFixture({ id: 3, name: 'Old' });
    const marks = {
      1: [
        markFixture({ id: 1, marked_at: '2025-11-30T15:00:00Z' }),
        markFixture({ id: 2, marked_at: '2025-12-31T15:00:00Z' }),
        markFixture({ id: 3, marked_at: '2026-01-02T15:00:00Z' }),
        markFixture({ id: 4, marked_at: '2026-01-03T15:00:00Z' }),
        markFixture({ id: 5, marked_at: '2026-02-10T15:00:00Z' }),
      ],
      3: [markFixture({ id: 6, habit_id: 3, marked_at: '2010-05-05T15:00:00Z' })],
    };
    const { requests } = mockHabitsApi({ habits: [running, empty, old], marks, pageSize: 1 });
    mockProgressApi({
      items: [
        item(running, ['2025-11-30', '2026-02-10']),
        item(empty, null),
        item(old, ['2010-05-05', '2010-05-05']),
      ],
    });
    const queryClient = client();

    const data = await fetchReportData(queryClient, {
      from: '2025-12-01',
      to: '2026-01-31',
      habitIds: null,
      timeZone: TZ,
    });

    expect(data.from).toBe('2025-12-01');
    expect(data.timezone).toBe(TZ);
    expect(data.habits.map((value) => [value.habit.id, value.marks.map((mark) => mark.id)])).toEqual([
      [1, [2, 3, 4]],
      [2, []],
      [3, []],
    ]);
    // Só o hábito 1 tem marcação no período: 2025 (2 páginas de 1) e 2026 (3 páginas)
    const calls = markRequests(requests);
    expect(new Set(calls.map((call) => call.path))).toEqual(new Set(['/habits/1/marks']));
    expect(calls.filter((call) => call.query.from.startsWith('2025-01-01')).length).toBe(2);
    expect(queryClient.getQueryData(markKeys.year(1, 2026, TZ)).map((mark) => mark.id)).toEqual([3, 4, 5]);
  });

  it('reuses the year marks the calendars already loaded, leaving pending ones out', async () => {
    const habit = habitFixture();
    const { requests } = mockHabitsApi({ habits: [habit] });
    mockProgressApi({ items: [item(habit, ['2026-03-02', '2026-03-02'])] });
    const queryClient = client();
    queryClient.setQueryData(markKeys.year(1, 2026, TZ), [
      markFixture({ id: 1 }),
      markFixture({ id: -1, marked_at: '2026-03-03T15:00:00Z', pending: true }),
    ]);

    const data = await fetchReportData(queryClient, { from: '2026-03-01', to: '2026-03-31', habitIds: [1], timeZone: TZ });

    expect(data.habits[0].marks.map((mark) => mark.id)).toEqual([1]);
    expect(markRequests(requests)).toEqual([]);
  });

  it('merges the progress of a period longer than 5 years', async () => {
    const habit = fullHabit();
    mockHabitsApi({ habits: [habit] });
    const queries = mockProgressApi({
      respond: (query) =>
        HttpResponse.json({
          from: query.from,
          to: query.to,
          timezone: TZ,
          habits: [
            item(habit, null, {
              // A semana que cruza a divisa vem nos dois pedaços
              periods:
                query.from === '2020-01-01'
                  ? [
                      { first_day: '2024-12-23', last_day: '2024-12-29', value: 1, met: false },
                      { first_day: '2024-12-30', last_day: '2025-01-05', value: 2, met: false },
                    ]
                  : [
                      { first_day: '2024-12-30', last_day: '2025-01-05', value: 2, met: false },
                      { first_day: '2025-01-06', last_day: '2025-01-12', value: 3, met: true },
                    ],
              cost_periods:
                query.from === '2020-01-01'
                  ? undefined
                  : [{ first_day: '2025-01-01', last_day: '2025-01-31', spend_cents: 0, limit_percent: 0 }],
            }),
          ],
        }),
    });

    const data = await fetchReportData(client(), { from: '2020-01-01', to: '2025-01-12', timeZone: TZ });

    expect(queries.map((query) => [query.from, query.to])).toEqual([
      ['2020-01-01', '2024-12-31'],
      ['2025-01-01', '2025-01-12'],
    ]);
    expect(data.habits[0].periods.map((period) => period.first_day)).toEqual([
      '2024-12-23',
      '2024-12-30',
      '2025-01-06',
    ]);
    expect(data.habits[0].cost_periods).toHaveLength(1);
  });

  it('stops at the first error', async () => {
    const habits = [1, 2, 3, 4, 5, 6].map((id) => habitFixture({ id }));
    mockProgressApi({ items: habits.map((habit) => item(habit, ['2026-03-02', '2026-03-02'])) });
    let calls = 0;
    server.use(
      http.get(api('/habits/:id/marks'), () => {
        calls += 1;
        return HttpResponse.json({ error: 'forbidden', field: null }, { status: 403 });
      }),
    );

    await expect(
      fetchReportData(client(), { from: '2026-03-01', to: '2026-03-31', timeZone: TZ }),
    ).rejects.toMatchObject({ code: 'forbidden' });
    expect(calls).toBeLessThanOrEqual(4);
  });

  it('starts no request after being canceled', async () => {
    const habit = habitFixture();
    const { requests } = mockHabitsApi({ habits: [habit] });
    mockProgressApi({ items: [item(habit, ['2026-03-02', '2026-03-02'])] });
    const controller = new AbortController();
    controller.abort();

    await expect(
      fetchReportData(client(), { from: '2026-03-01', to: '2026-03-31', timeZone: TZ, signal: controller.signal }),
    ).rejects.toThrow();
    expect(markRequests(requests)).toEqual([]);
  });
});

describe('export everything', () => {
  it('covers every habit from the first mark or creation until today', async () => {
    const habits = [
      // Marcação de 1950, registrada depois da criação
      habitFixture({ id: 1, created_at: '2025-06-01T12:00:00Z' }),
      // Criado antes de tudo, sem marcação
      habitFixture({ id: 2, created_at: '2024-02-10T12:00:00Z', status: 'archived' }),
    ];
    const marks = { 1: [markFixture({ id: 1, marked_at: '1950-06-01T15:00:00Z' }), markFixture({ id: 2 })] };
    const { requests } = mockHabitsApi({ habits, marks });
    const queries = mockProgressApi({
      items: [item(habits[0], ['1950-06-01', '2026-03-02']), item(habits[1], null)],
    });

    const data = await fetchAllReportData(client(), { timeZone: TZ });

    expect(queries[0]).toEqual({ from: '2026-03-20', to: '2026-03-20', habit_ids: [] });
    expect(data.from).toBe('1950-06-01');
    expect(data.to).toBe('2026-03-20');
    expect(queries.slice(1).every((query) => query.habit_ids.length === 0)).toBe(true);
    expect(queries.at(-1)).toMatchObject({ from: '2025-01-01', to: '2026-03-20' });
    expect(data.habits.map((value) => value.marks.map((mark) => mark.id))).toEqual([[1, 2], []]);
    // Um ano por chamada, de 1950 a 2026
    expect(markRequests(requests)).toHaveLength(2026 - 1950 + 1);
  });

  it('keeps a mark of 1 January 1900 UTC that is still 1899 west of UTC', async () => {
    const habit = habitFixture({ created_at: '2026-01-05T12:00:00Z' });
    const mark = markFixture({ id: 1, marked_at: '1900-01-01T02:00:00Z' });
    const { requests } = mockHabitsApi({ habits: [habit], marks: { 1: [mark] } });
    const queries = mockProgressApi({
      timezone: 'America/Los_Angeles',
      items: [item(habit, ['1899-12-31', '1899-12-31'])],
    });

    const data = await fetchAllReportData(client(), { timeZone: 'America/Los_Angeles' });

    expect(data.from).toBe('1899-12-31');
    expect(data.habits[0].marks.map((value) => value.id)).toEqual([1]);
    // O progresso começa no primeiro dia que a API aceita, e as marcações, no primeiro instante
    expect(queries[1].from).toBe('1900-01-01');
    expect(markRequests(requests)[0].query.from).toBe('1900-01-01T00:00:00.000Z');
  });

  it('exports an empty account', async () => {
    mockProgressApi({ items: [] });

    const data = await fetchAllReportData(client(), { timeZone: TZ });

    expect(data).toEqual({ from: '2026-03-20', to: '2026-03-20', timezone: TZ, habits: [] });
  });

  it('builds the JSON with every field and the CSV with every column', async () => {
    const habit = fullHabit();
    mockHabitsApi({ habits: [habit], marks: { 1: [fullMark()] } });
    mockProgressApi({ items: [item(habit, ['2026-03-02', '2026-03-02'])] });
    const t = await translator('en');

    const json = await exportAllFile(client(), { timeZone: TZ, format: 'json', t, now: NOW });
    const value = JSON.parse(await readFileText(json));
    expect(json.name).toBe('ethos-2026-01-05_2026-03-20.json');
    expect(validateSchema(jsonBlock(readFrontendFile('src/lib/export/schema.md')), value)).toEqual([]);
    expect(Object.values(value.options).every(Boolean)).toBe(true);
    expect(value.habits[0].marks[0]).toHaveProperty('note', 'Good run');

    const csv = await exportAllFile(client(), { timeZone: TZ, format: 'csv', t, now: NOW });
    expect((await readFileText(csv)).split('\r\n')[0]).toBe(
      '﻿Habit,Date,Time,Author,Duration (min),Cost,Note',
    );

    await expect(exportAllFile(client(), { timeZone: TZ, format: 'xml', t })).rejects.toThrow(RangeError);
  });
});

describe('cache', () => {
  it('rebuilds the report when marks change, even without score', async () => {
    const queryClient = client();
    queryClient.setQueryData(reportKeys.data({ from: 'a' }), { habits: [] });

    afterMarksChanged(queryClient, habitFixture({ score_enabled: false }));

    expect(queryClient.getQueryState(reportKeys.data({ from: 'a' })).isInvalidated).toBe(true);
  });

  it('lives under the habits keys, so a configuration change also rebuilds it', () => {
    expect(reportKeys.all.slice(0, 1)).toEqual(['habits']);
  });
});
