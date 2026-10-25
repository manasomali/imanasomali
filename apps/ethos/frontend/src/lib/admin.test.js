import { describe, expect, it } from 'vitest';
import { EMPTY_ACCOUNT_FILTERS, accountQuery, confirmsEmail, parseUserId } from './admin';

describe('account filters', () => {
  it('leaves empty fields out', () => {
    expect(accountQuery(EMPTY_ACCOUNT_FILTERS)).toEqual({});
    expect(accountQuery({ email: '   ' })).toEqual({});
  });

  it('sends the filled fields, with the email trimmed', () => {
    expect(
      accountQuery({
        email: '  bia@ ',
        status: 'blocked',
        created_from: '2026-01-01',
        created_to: '2026-01-31',
        last_login_from: '2026-02-01',
        last_login_to: '2026-02-28',
      }),
    ).toEqual({
      email: 'bia@',
      status: 'blocked',
      created_from: '2026-01-01',
      created_to: '2026-01-31',
      last_login_from: '2026-02-01',
      last_login_to: '2026-02-28',
    });
  });

  it('ignores an unknown status', () => {
    expect(accountQuery({ ...EMPTY_ACCOUNT_FILTERS, status: 'deleted' })).toEqual({});
  });
});

describe('confirmation by email', () => {
  it('accepts the account email, ignoring case and outer spaces', () => {
    expect(confirmsEmail('bia@example.com', 'bia@example.com')).toBe(true);
    expect(confirmsEmail('  BIA@Example.com ', 'bia@example.com')).toBe(true);
  });

  it('refuses anything else', () => {
    expect(confirmsEmail('', 'bia@example.com')).toBe(false);
    expect(confirmsEmail('bia@example', 'bia@example.com')).toBe(false);
    expect(confirmsEmail('bia@example.com.br', 'bia@example.com')).toBe(false);
    expect(confirmsEmail('ana@example.com', 'bia@example.com')).toBe(false);
    expect(confirmsEmail(undefined, 'bia@example.com')).toBe(false);
    expect(confirmsEmail('', '')).toBe(false);
    expect(confirmsEmail('x', null)).toBe(false);
  });
});

describe('user id from the URL', () => {
  it('reads positive integers', () => {
    expect(parseUserId('1')).toBe(1);
    expect(parseUserId('123456789012345')).toBe(123456789012345);
  });

  it('refuses anything else', () => {
    for (const value of ['0', '-1', '01', '1.5', '1e3', 'abc', '', ' 1', '1234567890123456', undefined]) {
      expect(parseUserId(value), String(value)).toBeNull();
    }
  });
});
