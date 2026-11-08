import { describe, expect, it } from 'vitest';
import { CODE_LENGTH, RESEND_SECONDS, isCompleteCode, onlyDigits } from './code';

describe('code', () => {
  it('keeps only ASCII digits, up to 6', () => {
    expect(onlyDigits('123 456')).toBe('123456');
    expect(onlyDigits('12-34-56-78')).toBe('123456');
    // Dígitos arábicos não são ASCII
    expect(onlyDigits('١٢٣abc')).toBe('');
    expect(onlyDigits(undefined)).toBe('');
    expect(onlyDigits(42)).toBe('42');
  });

  it('knows a complete code', () => {
    expect(isCompleteCode('012345')).toBe(true);
    expect(isCompleteCode('12345')).toBe(false);
    expect(isCompleteCode('1234567')).toBe(false);
    expect(isCompleteCode(123456)).toBe(false);
  });

  it('matches the API rules: 6 digits, one code per minute', () => {
    expect(CODE_LENGTH).toBe(6);
    expect(RESEND_SECONDS).toBe(60);
  });
});
