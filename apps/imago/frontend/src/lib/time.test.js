import { describe, expect, it } from 'vitest';
import { browserTimezone, isValidTimezone, sameTimezone } from './time';

describe('time zones', () => {
  it('reads the browser time zone', () => {
    expect(isValidTimezone(browserTimezone())).toBe(true);
  });

  it('knows valid names, twice in a row (the second from the cache)', () => {
    expect(isValidTimezone('America/Sao_Paulo')).toBe(true);
    expect(isValidTimezone('America/Sao_Paulo')).toBe(true);
    expect(isValidTimezone('Nowhere/City')).toBe(false);
    expect(isValidTimezone('')).toBe(false);
    expect(isValidTimezone(null)).toBe(false);
  });

  it('compares spellings of the same zone', () => {
    expect(sameTimezone('utc', 'UTC')).toBe(true);
    expect(sameTimezone('Europe/Lisbon', 'America/Sao_Paulo')).toBe(false);
    expect(sameTimezone('Nowhere/City', 'Nowhere/City')).toBe(true);
  });
});
