import { describe, expect, it } from 'vitest';
import { MAX_DURATION_MINUTES, parseDuration } from './duration';

describe('parseDuration', () => {
  it.each([
    ['1', 1],
    [' 45 ', 45],
    ['1440', 1440],
    ['0', null],
    ['1441', null],
    ['1.5', null],
    ['1e2', null],
    ['-3', null],
    ['', null],
    ['999999', null],
    [undefined, null],
  ])('reads %j as %j', (text, expected) => {
    expect(parseDuration(text)).toBe(expected);
  });

  it('matches the API maximum (one day)', () => {
    expect(MAX_DURATION_MINUTES).toBe(1440);
  });
});
