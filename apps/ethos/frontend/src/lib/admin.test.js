import { describe, expect, it } from 'vitest';
import { EMPTY_USER_FILTERS, parseUserId, userQuery } from './admin';

describe('user filters', () => {
  it('leaves empty fields out', () => {
    expect(userQuery(EMPTY_USER_FILTERS)).toEqual({});
    expect(userQuery({ email: '   ' })).toEqual({});
  });

  it('sends the filled fields, with the email trimmed', () => {
    expect(
      userQuery({ email: '  bia@ ', first_seen_from: '2026-01-01', first_seen_to: '2026-01-31' }),
    ).toEqual({ email: 'bia@', first_seen_from: '2026-01-01', first_seen_to: '2026-01-31' });
  });

  it('ignores fields that are not filters', () => {
    expect(userQuery({ ...EMPTY_USER_FILTERS, status: 'blocked', last_login_from: '2026-01-01' })).toEqual({});
  });
});

describe('user id from the URL', () => {
  it('reads the imago ids, up to 2^53 - 1', () => {
    expect(parseUserId('1')).toBe(1);
    expect(parseUserId('123456789012345')).toBe(123456789012345);
    expect(parseUserId(String(Number.MAX_SAFE_INTEGER))).toBe(Number.MAX_SAFE_INTEGER);
  });

  it('refuses anything else', () => {
    for (const value of ['0', '-1', '01', '1.5', '1e3', 'abc', '', ' 1', '9007199254740992', '12345678901234567', undefined]) {
      expect(parseUserId(value), String(value)).toBeNull();
    }
  });
});
