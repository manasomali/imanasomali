import { describe, expect, it } from 'vitest';
import {
  ACCOUNT_STATUSES,
  EMPTY_ACCOUNT_FILTERS,
  accountApiPath,
  accountQuery,
  accountStatus,
  confirmsEmail,
} from './admin';

describe('account filters', () => {
  it('leaves empty fields out', () => {
    expect(accountQuery(EMPTY_ACCOUNT_FILTERS)).toEqual({});
    expect(accountQuery({ email: '   ' })).toEqual({});
    expect(accountQuery(undefined)).toEqual({});
  });

  it('sends the filled fields, with the email trimmed', () => {
    expect(accountQuery({ email: '  bia@ ', status: 'blocked' })).toEqual({ email: 'bia@', status: 'blocked' });
  });

  it('knows the statuses of the API and ignores the rest', () => {
    expect(ACCOUNT_STATUSES).toEqual(['active', 'blocked', 'deleting']);
    expect(accountQuery({ status: 'deleting' })).toEqual({ status: 'deleting' });
    expect(accountQuery({ status: 'deleted' })).toEqual({});
    expect(accountQuery({ email: 3 })).toEqual({});
  });
});

describe('account status', () => {
  it('shows a deletion in progress first, then whether the account is blocked', () => {
    expect(accountStatus({ status: 'active', is_active: true })).toBe('active');
    expect(accountStatus({ status: 'active', is_active: false })).toBe('blocked');
    expect(accountStatus({ status: 'deleting', is_active: true })).toBe('deleting');
    expect(accountStatus({ status: 'deleting', is_active: false })).toBe('deleting');
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

describe('account API path', () => {
  it('builds the path of an account id, from 1 to 2^53 - 1', () => {
    expect(accountApiPath(102)).toBe('/admin/users/102');
    expect(accountApiPath(Number.MAX_SAFE_INTEGER, '/email')).toBe(`/admin/users/${Number.MAX_SAFE_INTEGER}/email`);
  });

  it('refuses anything that is not an id', () => {
    for (const id of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, '102', null, NaN]) {
      expect(() => accountApiPath(id), String(id)).toThrow(TypeError);
    }
  });
});
