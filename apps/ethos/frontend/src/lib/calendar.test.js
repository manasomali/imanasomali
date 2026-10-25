import { describe, expect, it } from 'vitest';
import {
  CALENDAR_WEEKDAYS,
  MAX_DOTS,
  MIN_YEAR,
  WEEK_START,
  calendarMonth,
  daysInMonth,
  daysInYear,
  isLeapYear,
  isoWeekday,
  marksByDay,
  moveDay,
  overviewByDay,
  parseDay,
  parseYear,
  splitDots,
  weekColumn,
  yearMonths,
  yearOf,
  yearRange,
} from './calendar';

describe('years and months', () => {
  it.each([
    [2024, true, 366],
    [2025, false, 365],
    [1900, false, 365],
    [2000, true, 366],
  ])('%i leap=%s has %i days', (year, leap, days) => {
    expect(isLeapYear(year)).toBe(leap);
    expect(daysInYear(year)).toBe(days);
  });

  it.each([2024, 2025, 2026])('yearMonths(%i) lists every day once, in order', (year) => {
    const months = yearMonths(year);
    const days = months.flatMap((month) => month.days);

    expect(months.map((month) => month.month)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(days).toHaveLength(daysInYear(year));
    expect(new Set(days).size).toBe(days.length);
    expect(days[0]).toBe(`${year}-01-01`);
    expect(days.at(-1)).toBe(`${year}-12-31`);
    expect([...days].sort()).toEqual(days);
    for (const { month, days: monthDays } of months) {
      expect(monthDays).toHaveLength(daysInMonth(year, month));
    }
  });

  it('draws the week from Sunday to Saturday', () => {
    expect(WEEK_START).toBe(7);
    expect(CALENDAR_WEEKDAYS).toEqual([7, 1, 2, 3, 4, 5, 6]);
    expect(Object.isFrozen(CALENDAR_WEEKDAYS)).toBe(true);
    // 1º de março de 2026 foi um domingo
    expect(isoWeekday('2026-03-01')).toBe(7);
    expect(isoWeekday('2026-03-02')).toBe(1);
    expect(['01', '02', '03', '04', '05', '06', '07', '08'].map((day) => weekColumn(`2026-03-${day}`))).toEqual([
      0, 1, 2, 3, 4, 5, 6, 0,
    ]);
  });

  it('puts day 1 in its column: none empty on a Sunday, 6 on a Saturday', () => {
    const months = yearMonths(2026);

    // 1º de março de 2026: domingo; 1º de agosto: sábado; 1º de janeiro: quinta; 1º de junho: segunda
    expect(months[2].offset).toBe(0);
    expect(months[7].offset).toBe(6);
    expect(months[0].offset).toBe(4);
    expect(months[5].offset).toBe(1);
    expect(calendarMonth(2026, 8)).toEqual(months[7]);
    expect(calendarMonth(2026, 8)).toMatchObject({ year: 2026, month: 8, offset: 6 });
  });

  it.each([
    [2025, 365, 3, 3],
    [2026, 365, 4, 4],
    [2024, 366, 1, 2],
    [2028, 366, 6, 0],
  ])('%i (%i days) starts in column %i and ends in column %i, without gaps', (year, length, start, end) => {
    const months = yearMonths(year);

    expect(months.flatMap((month) => month.days)).toHaveLength(length);
    expect(months[0].offset).toBe(start);
    expect(weekColumn(`${year}-12-31`)).toBe(end);
    // Cada mês começa na coluna seguinte à do último dia do mês anterior
    for (let index = 1; index < 12; index += 1) {
      const previous = months[index - 1];
      expect(months[index].offset).toBe((previous.offset + previous.days.length) % 7);
    }
  });

  it('gives February 29 days only in leap years', () => {
    expect(daysInMonth(2024, 2)).toBe(29);
    expect(daysInMonth(2025, 2)).toBe(28);
    expect(daysInMonth(2025, 4)).toBe(30);
    expect(yearMonths(2024)[1].days.at(-1)).toBe('2024-02-29');
  });

  it('knows the year of a day', () => {
    expect(yearOf('2026-03-04')).toBe(2026);
  });
});

describe('yearRange', () => {
  it('is the local year in UTC', () => {
    const { from, to } = yearRange(2026, 'America/Sao_Paulo');

    expect(from.toISOString()).toBe('2026-01-01T03:00:00.000Z');
    expect(to.toISOString()).toBe('2027-01-01T03:00:00.000Z');
  });

  it('fits the 367-day limit of the API in every time zone', () => {
    for (const zone of ['Pacific/Kiritimati', 'Pacific/Pago_Pago', 'Europe/Lisbon', 'UTC']) {
      const { from, to } = yearRange(2024, zone);
      expect((to - from) / 86_400_000).toBeLessThanOrEqual(367);
      expect((to - from) / 86_400_000).toBeGreaterThanOrEqual(365);
    }
  });

  it('starts the first navigable year after the API minimum', () => {
    expect(yearRange(MIN_YEAR, 'Asia/Tokyo').from >= new Date('1900-01-01T00:00:00Z')).toBe(true);
  });
});

describe('URL values', () => {
  it.each([
    ['2026', 2026],
    ['1901', 1901],
    ['1900', null],
    ['2027', null],
    ['202', null],
    ['2026.5', null],
    [' 2026', null],
    ['+2026', null],
    [null, null],
  ])('parseYear(%j) is %j', (value, expected) => {
    expect(parseYear(value, { max: 2026 })).toBe(expected);
  });

  it('parses years without a maximum', () => {
    expect(parseYear('2999')).toBe(2999);
  });

  it.each([
    ['2026-03-04', '2026-03-04'],
    ['2026-02-30', null],
    ['2026-3-4', null],
    [null, null],
  ])('parseDay(%j) is %j', (value, expected) => {
    expect(parseDay(value)).toBe(expected);
  });
});

describe('marksByDay', () => {
  it('groups marks by the local day, keeping the order', () => {
    const marks = [
      { id: 1, marked_at: '2026-03-04T02:30:00Z' },
      { id: 2, marked_at: '2026-03-04T15:00:00Z' },
      { id: 3, marked_at: '2026-03-05T02:59:59Z' },
    ];

    const days = marksByDay(marks, 'America/Sao_Paulo');

    // 02:30 UTC ainda é dia 3 em São Paulo; 02:59 do dia 5 ainda é dia 4
    expect([...days.keys()]).toEqual(['2026-03-03', '2026-03-04']);
    expect(days.get('2026-03-04').map((mark) => mark.id)).toEqual([2, 3]);
    expect(marksByDay(marks, 'UTC').get('2026-03-04').map((mark) => mark.id)).toEqual([1, 2]);
  });
});

describe('dots', () => {
  it('shows up to 4 and counts the rest', () => {
    expect(MAX_DOTS).toBe(4);
    expect(splitDots([1, 2, 3])).toEqual({ shown: [1, 2, 3], extra: 0 });
    expect(splitDots([1, 2, 3, 4])).toEqual({ shown: [1, 2, 3, 4], extra: 0 });
    expect(splitDots([1, 2, 3, 4, 5, 6])).toEqual({ shown: [1, 2, 3, 4], extra: 2 });
  });

  it('builds the overview of the habits marked on each day, in the habit order', () => {
    const habits = [
      { id: 1, color: 'red', label: 'A' },
      { id: 2, color: 'blue', label: 'B' },
      { id: 3, color: 'teal', label: 'C' },
    ];
    const byHabit = new Map([
      [2, new Map([['2026-03-04', [{}]], ['2026-03-05', []]])],
      [1, new Map([['2026-03-04', [{}, {}]]])],
    ]);

    const overview = overviewByDay(habits, byHabit, 1);

    expect([...overview.keys()]).toEqual(['2026-03-04']);
    expect(overview.get('2026-03-04')).toEqual({
      habits: [
        { id: 1, color: 'red', label: 'A' },
        { id: 2, color: 'blue', label: 'B' },
      ],
      shown: [{ id: 1, color: 'red', label: 'A' }],
      extra: 1,
      labels: 'A, B',
    });
  });
});

describe('moveDay', () => {
  const first = '2026-01-01';
  const last = '2026-12-31';

  it.each([
    ['ArrowLeft', '2026-03-09'],
    ['ArrowRight', '2026-03-11'],
    ['ArrowUp', '2026-03-03'],
    ['ArrowDown', '2026-03-17'],
    ['Home', '2026-03-01'],
    ['End', '2026-03-31'],
    ['Enter', null],
    ['a', null],
  ])('%s from March 10 goes to %j', (key, expected) => {
    expect(moveDay('2026-03-10', key, first, last)).toBe(expected);
  });

  it('stays inside the year', () => {
    expect(moveDay('2026-01-03', 'ArrowUp', first, last)).toBe(first);
    expect(moveDay('2026-12-31', 'ArrowRight', first, last)).toBe(last);
  });

  it('ends February on the 29th in a leap year', () => {
    expect(moveDay('2024-02-10', 'End', '2024-01-01', '2024-12-31')).toBe('2024-02-29');
  });
});
