import { describe, expect, it } from 'vitest';
import { formatDateTime } from './datetime';

const INSTANT = '2026-10-20T15:30:00Z';

// O ICU separa a hora do "PM" com um espaço estreito (U+202F)
function plain(text) {
  return text.replace(/\s/g, ' ');
}

describe('formatDateTime', () => {
  it('shows the instant in the time zone and language given', () => {
    expect(plain(formatDateTime(INSTANT, 'America/Sao_Paulo', 'pt'))).toBe('20/10/2026, 12:30');
    expect(plain(formatDateTime(INSTANT, 'UTC', 'en'))).toBe('10/20/26, 3:30 PM');
    expect(plain(formatDateTime(Date.parse(INSTANT), 'UTC', 'en'))).toBe('10/20/26, 3:30 PM');
  });

  it('falls back to UTC, saying so, for an unknown time zone', () => {
    expect(plain(formatDateTime(INSTANT, 'Nowhere/City', 'pt'))).toBe('20/10/2026, 15:30 UTC');
  });

  it('falls back to ISO 8601 for an invalid language', () => {
    expect(formatDateTime(INSTANT, 'Nowhere/City', '!!')).toBe('2026-10-20T15:30:00.000Z');
  });

  it('is empty for a missing or invalid instant', () => {
    expect(formatDateTime(null, 'UTC', 'en')).toBe('');
    expect(formatDateTime(undefined, 'UTC', 'en')).toBe('');
    expect(formatDateTime('not a date', 'UTC', 'en')).toBe('');
  });
});
