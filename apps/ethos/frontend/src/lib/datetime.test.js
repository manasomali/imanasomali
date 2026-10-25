import { describe, expect, it } from 'vitest';
import { formatDateTime, fromDateTimeLocal, toDateTimeLocal } from './datetime';

const SAO_PAULO = 'America/Sao_Paulo';
const NEW_YORK = 'America/New_York';

describe('datetime-local values', () => {
  it('shows an instant in the given time zone', () => {
    expect(toDateTimeLocal('2026-11-01T12:00:00Z', SAO_PAULO)).toBe('2026-11-01T09:00');
    expect(toDateTimeLocal('2026-11-01T03:00:00Z', SAO_PAULO)).toBe('2026-11-01T00:00');
    expect(toDateTimeLocal(Date.parse('2026-11-01T02:59:59Z'), SAO_PAULO)).toBe('2026-10-31T23:59');
    expect(toDateTimeLocal(new Date('2026-07-01T16:05:00Z'), NEW_YORK)).toBe('2026-07-01T12:05');
  });

  it('reads a value back as an instant in the given time zone', () => {
    expect(fromDateTimeLocal('2026-11-01T09:00', SAO_PAULO).toISOString()).toBe('2026-11-01T12:00:00.000Z');
    expect(fromDateTimeLocal('2026-11-01T00:00:00', SAO_PAULO).toISOString()).toBe('2026-11-01T03:00:00.000Z');
    expect(fromDateTimeLocal('2026-11-01T00:00:00.000', SAO_PAULO).toISOString()).toBe(
      '2026-11-01T03:00:00.000Z',
    );
  });

  it('round-trips', () => {
    const value = '2026-12-31T23:45';

    expect(toDateTimeLocal(fromDateTimeLocal(value, NEW_YORK), NEW_YORK)).toBe(value);
  });

  it('follows the backend on daylight saving gaps', () => {
    // 2:30 não existe em Nova York em 8/3/2026: vale o offset de antes da mudança (-5)
    expect(fromDateTimeLocal('2026-03-08T02:30', NEW_YORK).toISOString()).toBe('2026-03-08T07:30:00.000Z');
  });

  it('refuses values that are not a date and time', () => {
    for (const value of [
      '',
      null,
      undefined,
      20261101,
      '2026-11-01',
      '2026-11-01 09:00',
      '2026-02-30T10:00',
      '2026-01-01T24:00',
      '2026-01-01T10:60',
      '2026-01-01T10:00:30',
      '0000-01-01T10:00',
    ]) {
      expect(fromDateTimeLocal(value, SAO_PAULO), String(value)).toBeNull();
    }
  });
});

describe('formatDateTime', () => {
  it('formats in the language and time zone given', () => {
    const pt = formatDateTime('2026-11-01T12:00:00Z', SAO_PAULO, 'pt');
    const en = formatDateTime('2026-11-01T12:00:00Z', SAO_PAULO, 'en');

    expect(pt).toContain('01/11/2026');
    expect(pt).toContain('09:00');
    expect(en).toContain('11/1/26');
    expect(en).toContain('9:00');
  });

  it('reuses the formatter for the same language and time zone', () => {
    expect(formatDateTime(0, 'UTC', 'en')).toBe(formatDateTime(new Date(0), 'UTC', 'en'));
  });
});
