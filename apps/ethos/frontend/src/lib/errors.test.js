import { describe, expect, it } from 'vitest';
import { ApiError } from './api';
import { UNKNOWN_ERROR_KEY, errorKey } from './errors';

const known = new Set(['errors.rate_limited']);
const exists = (key) => known.has(key);

describe('errorKey', () => {
  it('uses the translation of the code', () => {
    expect(errorKey(new ApiError(429, 'rate_limited'), exists)).toBe('errors.rate_limited');
  });

  it('falls back to a generic message for an unknown code', () => {
    expect(errorKey(new ApiError(409, 'brand_new_code'), exists)).toBe(UNKNOWN_ERROR_KEY);
  });

  it('falls back to a generic message for errors outside the API', () => {
    expect(errorKey(new Error('bug'), exists)).toBe(UNKNOWN_ERROR_KEY);
    expect(errorKey(null, exists)).toBe(UNKNOWN_ERROR_KEY);
  });
});
