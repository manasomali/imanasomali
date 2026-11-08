import { describe, expect, it } from 'vitest';
import { isValidTimezone } from './time';
import {
  FALLBACK_TIMEZONES,
  availableTimezones,
  filterTimezones,
  timezoneLabel,
  timezoneOffset,
  timezoneOptions,
} from './timezones';

// Inverno no hemisfério norte: Lisboa em UTC+0, Nova York em UTC-5
const JANUARY = new Date('2026-01-15T12:00:00Z');

const values = (options) => options.map((option) => option.value);

describe('available time zones', () => {
  it('uses the browser list when there is one', () => {
    expect(availableTimezones(() => ['Europe/Lisbon', 'America/Sao_Paulo'])).toEqual([
      'Europe/Lisbon',
      'America/Sao_Paulo',
    ]);
    expect(availableTimezones()).toContain('America/Sao_Paulo');
  });

  it.each([
    ['missing', undefined],
    ['not a function', 'nope'],
    ['throwing', () => {
      throw new RangeError('timeZone');
    }],
    ['empty', () => []],
    ['not a list', () => 'Europe/Lisbon'],
  ])('falls back to the fixed list when supportedValuesOf is %s', (_, source) => {
    expect(availableTimezones(source ?? null)).toBe(FALLBACK_TIMEZONES);
  });

  it('has only valid names in the fixed list, sorted and without repetition', () => {
    expect(FALLBACK_TIMEZONES.every((name) => isValidTimezone(name))).toBe(true);
    expect([...FALLBACK_TIMEZONES].sort()).toEqual([...FALLBACK_TIMEZONES]);
    expect(new Set(FALLBACK_TIMEZONES).size).toBe(FALLBACK_TIMEZONES.length);
    expect(FALLBACK_TIMEZONES).toContain('America/Sao_Paulo');
  });
});

describe('time zone offset', () => {
  it.each([
    ['America/Sao_Paulo', 'UTC-03:00'],
    ['America/New_York', 'UTC-05:00'],
    ['Asia/Kathmandu', 'UTC+05:45'],
    ['Europe/Lisbon', 'UTC+00:00'],
    ['UTC', 'UTC+00:00'],
  ])('%s is %s in January', (timeZone, offset) => {
    expect(timezoneOffset(timeZone, JANUARY)).toBe(offset);
  });

  it('follows daylight saving time', () => {
    expect(timezoneOffset('America/New_York', new Date('2026-07-15T12:00:00Z'))).toBe('UTC-04:00');
  });

  it('is empty for an unknown time zone', () => {
    expect(timezoneOffset('Nowhere/City', JANUARY)).toBe('');
  });
});

describe('time zone options', () => {
  it('shows underscores as spaces', () => {
    expect(timezoneLabel('America/Argentina/Buenos_Aires')).toBe('America/Argentina/Buenos Aires');
  });

  it('adds UTC and the extra names, sorted, without repetition or unknown names', () => {
    const options = timezoneOptions({
      extra: ['Asia/Kolkata', 'Europe/Lisbon', 'Nowhere/City'],
      now: JANUARY,
      supportedValuesOf: () => ['Europe/Lisbon', 'America/Sao_Paulo'],
    });

    expect(values(options)).toEqual(['America/Sao_Paulo', 'Asia/Kolkata', 'Europe/Lisbon', 'UTC']);
    expect(options[0]).toEqual({
      value: 'America/Sao_Paulo',
      label: 'America/Sao Paulo',
      offset: 'UTC-03:00',
      search: 'america/sao paulo utc-03:00',
    });
  });

  it('lists the browser time zones by default', () => {
    const options = timezoneOptions({ now: JANUARY });

    expect(options.length).toBeGreaterThan(300);
    expect(values(options)).toContain('UTC');
    expect(values(options)).toContain('Pacific/Chatham');
  });
});

describe('time zone search', () => {
  const options = timezoneOptions({
    now: JANUARY,
    supportedValuesOf: () => [
      'America/Sao_Paulo',
      'America/Argentina/Buenos_Aires',
      'Asia/Kathmandu',
      'Europe/Lisbon',
      'Europe/Paris',
    ],
  });

  it.each([
    ['', ['America/Argentina/Buenos_Aires', 'America/Sao_Paulo', 'Asia/Kathmandu', 'Europe/Lisbon', 'Europe/Paris', 'UTC']],
    ['   ', ['America/Argentina/Buenos_Aires', 'America/Sao_Paulo', 'Asia/Kathmandu', 'Europe/Lisbon', 'Europe/Paris', 'UTC']],
    ['São Paulo', ['America/Sao_Paulo']],
    ['sao_paulo', ['America/Sao_Paulo']],
    ['LISBON', ['Europe/Lisbon']],
    ['europe', ['Europe/Lisbon', 'Europe/Paris']],
    ['america/buenos', ['America/Argentina/Buenos_Aires']],
    ['aires argentina', ['America/Argentina/Buenos_Aires']],
    ['utc-03', ['America/Argentina/Buenos_Aires', 'America/Sao_Paulo']],
    ['+05:45', ['Asia/Kathmandu']],
    ['utc+00', ['Europe/Lisbon', 'UTC']],
    ['tokyo', []],
  ])('"%s" finds %j', (query, expected) => {
    expect(values(filterTimezones(options, query))).toEqual(expected);
  });

  it('treats a missing query as empty', () => {
    expect(filterTimezones(options, undefined)).toBe(options);
  });
});
