import { describe, expect, it } from 'vitest';
import { createTestI18n, translations } from './test/i18n';
import { readFrontendFile } from './test/files';

/** Valores do StrEnum ErrorCode de app/errors.py. */
function backendErrorCodes() {
  const source = readFrontendFile('../backend/app/errors.py');
  const block = /class ErrorCode\(StrEnum\):([\s\S]*?)\n(?=\S)/.exec(source);
  if (!block) throw new Error('ErrorCode não encontrado em app/errors.py');
  return [...block[1].matchAll(/^\s+[A-Z0-9_]+ = "([a-z0-9_]+)"/gm)].map((match) => match[1]);
}

/** Chaves "a.b.c" de todas as folhas do JSON. */
function leafKeys(value, prefix = '') {
  return Object.entries(value).flatMap(([key, child]) =>
    typeof child === 'object' && child !== null ? leafKeys(child, `${prefix}${key}.`) : [`${prefix}${key}`],
  );
}

describe('language', () => {
  it('reads the language saved by the site, reducing the region', () => {
    window.localStorage.setItem('i18nextLng', 'pt-BR');

    const i18n = createTestI18n();

    expect(i18n.resolvedLanguage).toBe('pt');
    expect(document.documentElement.lang).toBe('pt');
    expect(i18n.t('menu.habits')).toBe('Hábitos');
  });

  it('falls back to the browser language and then to English', () => {
    const i18n = createTestI18n();

    expect(i18n.resolvedLanguage).toBe('en');
  });

  it('ignores an unsupported saved language', () => {
    window.localStorage.setItem('i18nextLng', 'de');

    expect(createTestI18n().resolvedLanguage).toBe('en');
  });

  it('saves a change in the shared key, for the site to read', async () => {
    const i18n = createTestI18n();

    await i18n.changeLanguage('pt');

    expect(window.localStorage.getItem('i18nextLng')).toBe('pt');
    expect(document.documentElement.lang).toBe('pt');
  });
});

describe('translations', () => {
  it('pt and en have the same keys', () => {
    expect(leafKeys(translations.pt).sort()).toEqual(leafKeys(translations.en).sort());
  });

  it('no translation is empty', () => {
    for (const [language, values] of Object.entries(translations)) {
      for (const key of leafKeys(values)) {
        const text = key.split('.').reduce((node, part) => node[part], values);

        expect(typeof text === 'string' && text.trim() !== '', `${language}: ${key}`).toBe(true);
      }
    }
  });

  // Checagem entre áreas: todo código de app/errors.py tem tradução nos dois idiomas
  it('every error code of the backend is translated in pt and en', () => {
    const codes = backendErrorCodes();

    expect(codes.length).toBeGreaterThanOrEqual(11);
    for (const code of codes) {
      expect(translations.pt.errors[code], `pt: errors.${code}`).toBeTruthy();
      expect(translations.en.errors[code], `en: errors.${code}`).toBeTruthy();
    }
  });

  it('has the messages of the front-only codes', () => {
    for (const code of ['network_error', 'unknown']) {
      expect(translations.pt.errors[code]).toBeTruthy();
      expect(translations.en.errors[code]).toBeTruthy();
    }
  });
});
