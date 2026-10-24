import { describe, expect, it } from 'vitest';
import { MAX_MONEY_CENTS, formatMoney, parseMoney } from './money';

describe('formatMoney', () => {
  it('formats by language with 2 decimals and no currency symbol', () => {
    expect(formatMoney(123450, 'en')).toBe('1,234.50');
    expect(formatMoney(123450, 'pt')).toBe('1.234,50');
  });

  it('formats small and large values', () => {
    expect(formatMoney(0, 'pt')).toBe('0,00');
    expect(formatMoney(5, 'en')).toBe('0.05');
    expect(formatMoney(99950, 'pt')).toBe('999,50');
    expect(formatMoney(MAX_MONEY_CENTS, 'en')).toBe('10,000,000,000.00');
    expect(formatMoney(999_999_999_999, 'en')).toBe('9,999,999,999.99');
  });

  it.each([1.5, Number.NaN, '100', null, 2 ** 60])('rejects %s', (value) => {
    expect(() => formatMoney(value, 'en')).toThrow(TypeError);
  });
});

describe('parseMoney', () => {
  it.each([
    ['1234,5', 'pt', 123450],
    ['1.234,50', 'pt', 123450],
    ['1234', 'pt', 123400],
    [' 0,05 ', 'pt', 5],
    ['1,234.50', 'en', 123450],
    ['1234.5', 'en', 123450],
    ['10000000000', 'en', MAX_MONEY_CENTS],
    ['007', 'en', 700],
  ])('reads %s in %s', (text, locale, cents) => {
    expect(parseMoney(text, locale)).toBe(cents);
  });

  it.each([
    ['', 'pt'],
    ['abc', 'en'],
    ['-1', 'en'],
    ['1,234', 'pt'],
    ['1.5', 'pt'],
    ['1,5', 'en'],
    ['1.234.5', 'en'],
    ['12,34.50', 'en'],
    ['1.001', 'en'],
    ['10000000000.01', 'en'],
    ['9'.repeat(400), 'en'],
    [123, 'en'],
    [null, 'pt'],
  ])('rejects %s in %s', (text, locale) => {
    expect(parseMoney(text, locale)).toBeNull();
  });

  it('round-trips what formatMoney writes', () => {
    for (const cents of [0, 1, 99, 100, 123456789]) {
      for (const locale of ['pt', 'en']) {
        expect(parseMoney(formatMoney(cents, locale), locale)).toBe(cents);
      }
    }
  });
});
