import { describe, expect, it } from 'vitest';
import { DISMISSED_KEY, dismissTimezoneNotice, shouldSuggestTimezone } from './timezoneNotice';

describe('timezone notice', () => {
  it('suggests a change when the browser is in another time zone', () => {
    expect(shouldSuggestTimezone('America/Sao_Paulo', 'Europe/Lisbon')).toBe(true);
  });

  it('stays quiet when the time zones match', () => {
    expect(shouldSuggestTimezone('America/Sao_Paulo', 'America/Sao_Paulo')).toBe(false);
  });

  it('stays quiet without both time zones', () => {
    expect(shouldSuggestTimezone('', 'Europe/Lisbon')).toBe(false);
    expect(shouldSuggestTimezone('America/Sao_Paulo', undefined)).toBe(false);
  });

  it('"not now" holds for that pair only', () => {
    dismissTimezoneNotice('America/Sao_Paulo', 'Europe/Lisbon');

    expect(window.localStorage.getItem(DISMISSED_KEY)).toBe('America/Sao_Paulo|Europe/Lisbon');
    expect(shouldSuggestTimezone('America/Sao_Paulo', 'Europe/Lisbon')).toBe(false);
    expect(shouldSuggestTimezone('America/Sao_Paulo', 'Asia/Tokyo')).toBe(true);
  });
});
