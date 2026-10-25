import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  addDays,
  browserTimezone,
  dayBounds,
  isValidTimezone,
  localDate,
  localTime,
  markedAtFor,
  parseDate,
  pastDayNoon,
  sameTimezone,
  today,
  zonedTimeToUtc,
} from './time';

const HOUR = 60 * 60 * 1000;

function iso(date) {
  return date.toISOString();
}

function hours({ start, end }) {
  return (end.getTime() - start.getTime()) / HOUR;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('parseDate', () => {
  it('reads a calendar date', () => {
    expect(parseDate('2024-02-29')).toEqual({ year: 2024, month: 2, day: 29 });
  });

  it.each(['2023-02-29', '2026-13-01', '2026-04-31', '0000-01-01', '2026-1-01', '', null, 20260101])(
    'rejects %s',
    (value) => {
      expect(() => parseDate(value)).toThrow(RangeError);
    },
  );

  it('keeps years below 100 as written', () => {
    expect(addDays('0099-12-31', 1)).toBe('0100-01-01');
  });
});

describe('addDays', () => {
  it('crosses months, leap days and years', () => {
    expect(addDays('2024-02-28', 1)).toBe('2024-02-29');
    expect(addDays('2024-03-01', -1)).toBe('2024-02-29');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(addDays('2026-10-24', 0)).toBe('2026-10-24');
  });
});

describe('dayBounds', () => {
  it('is 24 h on a normal day', () => {
    const bounds = dayBounds('2026-10-24', 'UTC');

    expect(iso(bounds.start)).toBe('2026-10-24T00:00:00.000Z');
    expect(iso(bounds.end)).toBe('2026-10-25T00:00:00.000Z');
  });

  it('handles half-hour offsets', () => {
    const bounds = dayBounds('2026-06-15', 'Asia/Kolkata');

    expect(iso(bounds.start)).toBe('2026-06-14T18:30:00.000Z');
    expect(hours(bounds)).toBe(24);
  });

  it('starts at the change when DST begins at midnight (23 h day)', () => {
    // São Paulo, 2018-11-04: 00:00 virou 01:00, então a meia-noite não existiu
    const bounds = dayBounds('2018-11-04', 'America/Sao_Paulo');

    expect(iso(bounds.start)).toBe('2018-11-04T03:00:00.000Z');
    expect(iso(bounds.end)).toBe('2018-11-05T02:00:00.000Z');
    expect(hours(bounds)).toBe(23);
  });

  it('includes the repeated hour when DST ends at midnight (25 h day)', () => {
    // São Paulo, 2019-02-17 00:00 (-02) voltou para 2019-02-16 23:00 (-03)
    const bounds = dayBounds('2019-02-16', 'America/Sao_Paulo');

    expect(iso(bounds.start)).toBe('2019-02-16T02:00:00.000Z');
    expect(iso(bounds.end)).toBe('2019-02-17T03:00:00.000Z');
    expect(hours(bounds)).toBe(25);
  });

  it('handles DST changes in the middle of the night', () => {
    expect(hours(dayBounds('2026-03-08', 'America/New_York'))).toBe(23);
    expect(iso(dayBounds('2026-03-08', 'America/New_York').start)).toBe('2026-03-08T05:00:00.000Z');
    expect(hours(dayBounds('2026-11-01', 'America/New_York'))).toBe(25);
    expect(iso(dayBounds('2026-11-01', 'America/New_York').end)).toBe('2026-11-02T05:00:00.000Z');
  });

  it('agrees with localDate at both ends', () => {
    for (const day of ['2018-11-04', '2019-02-16', '2026-01-01']) {
      const { start, end } = dayBounds(day, 'America/Sao_Paulo');

      expect(localDate(start, 'America/Sao_Paulo')).toBe(day);
      expect(localDate(end.getTime() - 1, 'America/Sao_Paulo')).toBe(day);
      expect(localDate(end, 'America/Sao_Paulo')).toBe(addDays(day, 1));
    }
  });
});

describe('zonedTimeToUtc', () => {
  it('keeps the first occurrence of a repeated hour', () => {
    // Nova York, 2026-11-01: 01:30 acontece em -04 e depois em -05
    expect(iso(zonedTimeToUtc('2026-11-01', 'America/New_York', 1, 30))).toBe(
      '2026-11-01T05:30:00.000Z',
    );
  });

  it('uses the offset before the change for a skipped hour', () => {
    // Nova York, 2026-03-08: 02:30 não existe; com o offset de antes (-05) vira 07:30Z
    expect(iso(zonedTimeToUtc('2026-03-08', 'America/New_York', 2, 30))).toBe(
      '2026-03-08T07:30:00.000Z',
    );
  });

  it('rejects an unknown time zone', () => {
    expect(() => zonedTimeToUtc('2026-10-24', 'Mars/Olympus')).toThrow(RangeError);
  });
});

describe('pastDayNoon', () => {
  it('is 12:00 local converted to UTC', () => {
    expect(iso(pastDayNoon('2026-03-01', 'America/Sao_Paulo'))).toBe('2026-03-01T15:00:00.000Z');
    expect(iso(pastDayNoon('2026-10-24', 'Asia/Tokyo'))).toBe('2026-10-24T03:00:00.000Z');
  });

  it('follows DST on the day of the change', () => {
    expect(iso(pastDayNoon('2026-03-08', 'America/New_York'))).toBe('2026-03-08T16:00:00.000Z');
    expect(iso(pastDayNoon('2026-03-07', 'America/New_York'))).toBe('2026-03-07T17:00:00.000Z');
  });
});

describe('markedAtFor', () => {
  const now = new Date('2026-10-24T20:00:00Z');

  it('uses the current instant for today', () => {
    const marked = markedAtFor('2026-10-24', 'America/Sao_Paulo', now);

    expect(marked.getTime()).toBe(now.getTime());
    expect(marked).not.toBe(now);
  });

  it('uses 12:00 local for a past day', () => {
    expect(iso(markedAtFor('2026-10-20', 'America/Sao_Paulo', now))).toBe(
      '2026-10-20T15:00:00.000Z',
    );
  });

  it('decides today in the given time zone', () => {
    // 20:00Z já é 25/10 em Tóquio: 24/10 é passado lá
    expect(today('Asia/Tokyo', now)).toBe('2026-10-25');
    expect(iso(markedAtFor('2026-10-24', 'Asia/Tokyo', now))).toBe('2026-10-24T03:00:00.000Z');
  });

  it('refuses a future day', () => {
    expect(() => markedAtFor('2026-10-25', 'America/Sao_Paulo', now)).toThrow(RangeError);
  });

  it('defaults to the current time', () => {
    const day = today('UTC');

    expect(Math.abs(markedAtFor(day, 'UTC').getTime() - Date.now())).toBeLessThan(5000);
  });
});

describe('time zones', () => {
  it('validates IANA names', () => {
    expect(isValidTimezone('America/Sao_Paulo')).toBe(true);
    expect(isValidTimezone('Mars/Olympus')).toBe(false);
    expect(isValidTimezone('')).toBe(false);
    expect(isValidTimezone(undefined)).toBe(false);
  });

  it('compares names after canonicalization', () => {
    expect(sameTimezone('America/Sao_Paulo', 'America/Sao_Paulo')).toBe(true);
    expect(sameTimezone('america/sao_paulo', 'America/Sao_Paulo')).toBe(true);
    expect(sameTimezone('America/Sao_Paulo', 'Europe/Lisbon')).toBe(false);
    expect(sameTimezone('Mars/Olympus', 'Mars/Olympus')).toBe(true);
    expect(sameTimezone('Mars/Olympus', 'UTC')).toBe(false);
  });

  it('reads the browser time zone', () => {
    expect(isValidTimezone(browserTimezone())).toBe(true);
  });

  it('falls back to UTC when the browser has no time zone', () => {
    vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(() => ({
      resolvedOptions: () => ({}),
    }));

    expect(browserTimezone()).toBe('UTC');
  });

  it('falls back to UTC when Intl fails', () => {
    vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(() => {
      throw new Error('broken');
    });

    expect(browserTimezone()).toBe('UTC');
  });
});

describe('localTime', () => {
  it('gives the 24-hour local time of an instant', () => {
    expect(localTime('2026-03-04T15:05:00Z', 'America/Sao_Paulo')).toBe('12:05');
    expect(localTime('2026-03-04T02:30:00Z', 'America/Sao_Paulo')).toBe('23:30');
    expect(localTime(Date.parse('2026-03-04T00:00:00Z'), 'UTC')).toBe('00:00');
  });
});
