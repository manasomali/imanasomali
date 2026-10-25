import { describe, expect, it } from 'vitest';
import { MIN_YEAR } from './calendar';
import {
  DEFAULT_RANGE_KIND,
  RANGE_KINDS,
  RANGE_STORAGE_KEY,
  calendarRange,
  clampAnchor,
  monthOf,
  monthParam,
  parseMonthParam,
  parseRangeKind,
  rangeNeighbors,
  resolveCalendar,
  shiftAnchor,
  switchAnchor,
  writeRangeParams,
} from './calendarRange';

// Hoje em todos os testes: terça, 10 de março de 2026
const TODAY = '2026-03-10';

/** Os meses de uma faixa como "AAAA-MM", para comparar. */
function monthsOf(range) {
  return range.months.map(monthParam);
}

/** resolveCalendar com os parâmetros que faltarem como null (a URL sem eles). */
function resolve(params, stored = null, today = TODAY) {
  return resolveCalendar({ range: null, month: null, year: null, day: null, ...params }, stored, today);
}

describe('range kinds', () => {
  it('lists the kinds and reads only those', () => {
    expect(RANGE_KINDS).toEqual(['month', '3months', 'year']);
    expect(DEFAULT_RANGE_KIND).toBe('year');
    expect(RANGE_STORAGE_KEY).toBe('ethos:calendar-range');
    for (const kind of RANGE_KINDS) expect(parseRangeKind(kind)).toBe(kind);
    for (const value of [null, undefined, '', 'Month', 'quarter', '3', ' year']) {
      expect(parseRangeKind(value)).toBeNull();
    }
  });
});

describe('months', () => {
  it('reads and writes "AAAA-MM"', () => {
    expect(monthOf('2026-03-10')).toEqual({ year: 2026, month: 3 });
    expect(monthParam({ year: 2026, month: 3 })).toBe('2026-03');
    expect(monthParam({ year: 1901, month: 12 })).toBe('1901-12');
    const max = { year: 2026, month: 3 };
    expect(parseMonthParam('2026-03', max)).toEqual({ year: 2026, month: 3 });
    expect(parseMonthParam('2025-12', max)).toEqual({ year: 2025, month: 12 });
    expect(parseMonthParam(`${MIN_YEAR}-01`, max)).toEqual({ year: MIN_YEAR, month: 1 });
  });

  it.each([
    [null],
    [''],
    ['2026-3'],
    ['2026-13'],
    ['2026-00'],
    ['2026-03-01'],
    [' 2026-03'],
    ['+2026-03'],
    ['1900-12'],
    // Depois do mês de hoje
    ['2026-04'],
    ['2027-01'],
  ])('ignores the month %j', (value) => {
    expect(parseMonthParam(value, { year: 2026, month: 3 })).toBeNull();
  });
});

describe('calendarRange', () => {
  it('shows only the anchor month', () => {
    const range = calendarRange('month', { year: 2026, month: 2 });
    expect(monthsOf(range)).toEqual(['2026-02']);
    expect(range).toMatchObject({ kind: 'month', first: '2026-02-01', last: '2026-02-28', years: [2026] });
    expect(range.months[0].days).toHaveLength(28);
  });

  it('shows the month before and after the anchor in the 3-month window', () => {
    const range = calendarRange('3months', { year: 2026, month: 3 });
    expect(monthsOf(range)).toEqual(['2026-02', '2026-03', '2026-04']);
    expect(range).toMatchObject({ first: '2026-02-01', last: '2026-04-30', years: [2026] });
  });

  it.each([
    [{ year: 2026, month: 1 }, ['2025-12', '2026-01', '2026-02'], '2025-12-01', '2026-02-28'],
    [{ year: 2025, month: 12 }, ['2025-11', '2025-12', '2026-01'], '2025-11-01', '2026-01-31'],
    [{ year: 2024, month: 1 }, ['2023-12', '2024-01', '2024-02'], '2023-12-01', '2024-02-29'],
  ])('crosses the year in the 3-month window around %j', (anchor, months, first, last) => {
    const range = calendarRange('3months', anchor);
    expect(monthsOf(range)).toEqual(months);
    expect(range.first).toBe(first);
    expect(range.last).toBe(last);
    expect(range.years).toEqual([Number(first.slice(0, 4)), Number(last.slice(0, 4))]);
  });

  it('shows the whole year of the anchor', () => {
    const range = calendarRange('year', { year: 2024, month: 7 });
    expect(range.months).toHaveLength(12);
    expect(range.months.flatMap((month) => month.days)).toHaveLength(366);
    expect(range).toMatchObject({ first: '2024-01-01', last: '2024-12-31', years: [2024] });
    expect(range.anchor).toEqual({ year: 2024, month: 7 });
  });
});

describe('moving the range', () => {
  it('steps by one month, three months or one year', () => {
    const anchor = { year: 2026, month: 1 };
    expect(shiftAnchor('month', anchor, -1)).toEqual({ year: 2025, month: 12 });
    expect(shiftAnchor('month', anchor, 1)).toEqual({ year: 2026, month: 2 });
    expect(shiftAnchor('3months', anchor, -1)).toEqual({ year: 2025, month: 10 });
    expect(shiftAnchor('3months', anchor, 1)).toEqual({ year: 2026, month: 4 });
    expect(shiftAnchor('year', anchor, -1)).toEqual({ year: 2025, month: 1 });
  });

  it('keeps the anchor between January of MIN_YEAR and the current month', () => {
    expect(clampAnchor('month', { year: 2026, month: 5 }, TODAY)).toEqual({ year: 2026, month: 3 });
    expect(clampAnchor('year', { year: 2027, month: 1 }, TODAY)).toEqual({ year: 2026, month: 3 });
    expect(clampAnchor('month', { year: 1900, month: 12 }, TODAY)).toEqual({ year: MIN_YEAR, month: 1 });
    // A janela de 3 meses não começa antes de janeiro de MIN_YEAR
    expect(clampAnchor('3months', { year: MIN_YEAR, month: 1 }, TODAY)).toEqual({
      year: MIN_YEAR,
      month: 2,
    });
    expect(clampAnchor('3months', { year: 2025, month: 12 }, TODAY)).toEqual({ year: 2025, month: 12 });
  });

  it('has no next range from the current month or year', () => {
    for (const kind of RANGE_KINDS) {
      const range = calendarRange(kind, monthOf(TODAY));
      expect(rangeNeighbors(range, TODAY).next).toBeNull();
    }
    // Ano anterior com a âncora em qualquer mês: o próximo é o ano atual
    const lastYear = calendarRange('year', { year: 2025, month: 12 });
    expect(rangeNeighbors(lastYear, TODAY).next).toEqual({ year: 2026, month: 3 });
  });

  it('gives the previous and next anchors of each kind', () => {
    expect(rangeNeighbors(calendarRange('month', { year: 2026, month: 1 }), TODAY)).toEqual({
      previous: { year: 2025, month: 12 },
      next: { year: 2026, month: 2 },
    });
    expect(rangeNeighbors(calendarRange('3months', { year: 2026, month: 3 }), TODAY)).toEqual({
      previous: { year: 2025, month: 12 },
      next: null,
    });
    // Do meio de dezembro, o próximo passaria do mês de hoje: para no mês de hoje
    expect(rangeNeighbors(calendarRange('3months', { year: 2025, month: 12 }), TODAY).next).toEqual({
      year: 2026,
      month: 3,
    });
    expect(rangeNeighbors(calendarRange('year', { year: 2026, month: 3 }), TODAY).previous).toEqual({
      year: 2025,
      month: 3,
    });
  });

  it('stops at the start of MIN_YEAR', () => {
    expect(rangeNeighbors(calendarRange('month', { year: MIN_YEAR, month: 1 }), TODAY).previous).toBeNull();
    expect(rangeNeighbors(calendarRange('year', { year: MIN_YEAR, month: 1 }), TODAY).previous).toBeNull();
    expect(rangeNeighbors(calendarRange('3months', { year: MIN_YEAR, month: 2 }), TODAY).previous).toBeNull();
    // Perto do começo, a janela anterior encosta em janeiro de MIN_YEAR
    expect(rangeNeighbors(calendarRange('3months', { year: MIN_YEAR, month: 3 }), TODAY).previous).toEqual({
      year: MIN_YEAR,
      month: 2,
    });
  });
});

describe('switchAnchor', () => {
  const year2025 = calendarRange('year', { year: 2025, month: 1 });

  it('keeps the chosen day visible', () => {
    expect(switchAnchor(year2025, 'month', '2025-12-20', TODAY)).toEqual({ year: 2025, month: 12 });
    expect(switchAnchor(year2025, '3months', '2025-12-20', TODAY)).toEqual({ year: 2025, month: 12 });
    const window = calendarRange('3months', { year: 2025, month: 12 });
    expect(switchAnchor(window, 'year', '2026-01-02', TODAY)).toEqual({ year: 2026, month: 1 });
    expect(switchAnchor(window, 'month', '2025-11-03', TODAY)).toEqual({ year: 2025, month: 11 });
  });

  it('starts at the first month on screen without a day', () => {
    expect(switchAnchor(year2025, 'month', null, TODAY)).toEqual({ year: 2025, month: 1 });
    // A janela começa em janeiro: âncora em fevereiro
    expect(switchAnchor(year2025, '3months', null, TODAY)).toEqual({ year: 2025, month: 2 });
    const window = calendarRange('3months', { year: 2026, month: 1 });
    expect(switchAnchor(window, 'year', null, TODAY)).toEqual({ year: 2025, month: 12 });
    expect(switchAnchor(window, 'month', null, TODAY)).toEqual({ year: 2025, month: 12 });
  });
});

describe('resolveCalendar', () => {
  it('shows the current year with today chosen by default', () => {
    const { range, day } = resolve({});
    expect(range.kind).toBe('year');
    expect(range.first).toBe('2026-01-01');
    expect(day).toBe(TODAY);
  });

  it('uses the kind from the URL, then the remembered one', () => {
    expect(resolve({}, 'month').range.kind).toBe('month');
    expect(resolve({ range: '3months' }, 'month').range.kind).toBe('3months');
    expect(resolve({ range: 'weeks' }, 'month').range.kind).toBe('month');
    expect(resolve({ range: 'weeks' }, 'weeks').range.kind).toBe('year');
  });

  it('centers the month ranges on today', () => {
    expect(monthsOf(resolve({ range: 'month' }).range)).toEqual(['2026-03']);
    const { range, day } = resolve({ range: '3months' });
    expect(monthsOf(range)).toEqual(['2026-02', '2026-03', '2026-04']);
    expect(day).toBe(TODAY);
  });

  it('reads the month of the month ranges', () => {
    const { range, day } = resolve({ range: '3months', month: '2026-01' });
    expect(monthsOf(range)).toEqual(['2025-12', '2026-01', '2026-02']);
    // Hoje não está na faixa e não há dia na URL
    expect(day).toBeNull();
    expect(resolve({ range: 'month', month: '2025-12', day: '2025-12-24' }).day).toBe('2025-12-24');
    // Dia fora da faixa é ignorado
    expect(resolve({ range: 'month', month: '2025-12', day: '2025-11-24' }).day).toBeNull();
  });

  it('reads the year of the year range, then the year of the month', () => {
    expect(resolve({ year: '2024' }).range.first).toBe('2024-01-01');
    expect(resolve({ month: '2024-05' }).range.first).toBe('2024-01-01');
    expect(resolve({ year: '2025', month: '2024-05' }).range.first).toBe('2025-01-01');
  });

  it('opens a month range from a year link at the day or the start of the year', () => {
    expect(monthsOf(resolve({ range: 'month', year: '2025', day: '2025-07-04' }).range)).toEqual(['2025-07']);
    expect(monthsOf(resolve({ range: 'month', year: '2025' }).range)).toEqual(['2025-01']);
    expect(monthsOf(resolve({ range: '3months', year: '2025' }).range)).toEqual([
      '2025-01',
      '2025-02',
      '2025-03',
    ]);
    expect(monthsOf(resolve({ range: 'month', year: '2026' }).range)).toEqual(['2026-03']);
    // O dia de outro ano não conta
    expect(monthsOf(resolve({ range: 'month', year: '2025', day: '2024-07-04' }).range)).toEqual(['2025-01']);
  });

  it('opens the month of the day without a position', () => {
    const { range, day } = resolve({ range: '3months', day: '2025-12-31' });
    expect(monthsOf(range)).toEqual(['2025-11', '2025-12', '2026-01']);
    expect(day).toBe('2025-12-31');
    expect(resolve({ day: '2024-02-29' }).range.first).toBe('2024-01-01');
  });

  it.each([
    [{ day: '2026-03-11' }],
    [{ day: '2026-02-30' }],
    [{ day: '1900-12-31' }],
    [{ year: '2027' }],
    [{ year: '1900' }],
    [{ month: '2026-04' }],
    [{ range: 'month', month: '2030-01' }],
  ])('ignores invalid or future values: %j', (params) => {
    const { range, day } = resolve(params);
    expect(range.months.map(monthParam)).toContain('2026-03');
    expect(day).toBe(TODAY);
  });

  it('keeps the 3-month window after January of MIN_YEAR', () => {
    const { range } = resolve({ range: '3months', month: `${MIN_YEAR}-01` });
    expect(range.first).toBe(`${MIN_YEAR}-01-01`);
  });
});

describe('writeRangeParams', () => {
  it('writes the year in the year range and the month in the others', () => {
    const params = new URLSearchParams('month=2025-12&day=2025-12-20&other=1');
    writeRangeParams(params, 'year', { year: 2025, month: 12 });
    expect(params.toString()).toBe('day=2025-12-20&other=1&range=year&year=2025');

    writeRangeParams(params, '3months', { year: 2026, month: 1 });
    expect(params.toString()).toBe('day=2025-12-20&other=1&range=3months&month=2026-01');
  });
});
