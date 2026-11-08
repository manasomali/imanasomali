import { describe, expect, it } from 'vitest';
import { apiLocale } from './locale';

describe('apiLocale', () => {
  it.each([
    ['pt', 'pt'],
    ['pt-BR', 'pt'],
    ['PT', 'pt'],
    ['en', 'en'],
    ['en-US', 'en'],
    ['de', 'en'],
    ['ptx', 'en'],
    [undefined, 'en'],
  ])('maps the screen language %s to the API locale %s', (language, locale) => {
    expect(apiLocale(language)).toBe(locale);
  });
});
