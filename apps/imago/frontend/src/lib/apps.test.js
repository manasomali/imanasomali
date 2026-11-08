import { describe, expect, it } from 'vitest';
import { LANGUAGES } from '../i18n';
import { readFrontendFile } from '../test/files';
import { createTestI18n, translations } from '../test/i18n';
import { APP_TEXT_KEYS, accountApps, appPath, appTexts, isAppName } from './apps';

function textsIn(language, name) {
  const i18n = createTestI18n();
  i18n.changeLanguage(language);
  return appTexts(name, i18n.t, (key) => i18n.exists(key));
}

describe('app names', () => {
  it('follows the rule of infra/databases.txt', () => {
    expect(isAppName('ethos')).toBe(true);
    expect(isAppName('engrafi')).toBe(true);
    expect(isAppName('a-1')).toBe(true);
    for (const name of ['e', 'Ethos', '1ethos', 'ethos/', '../x', `a${'b'.repeat(27)}`, '', null, 3]) {
      expect(isAppName(name), String(name)).toBe(false);
    }
  });

  it('keeps the valid names of GET /me, in order and without repetition', () => {
    expect(accountApps(['ethos', 'engrafi', 'ethos', '../evil', null])).toEqual(['ethos', 'engrafi']);
    expect(accountApps(undefined)).toEqual([]);
    expect(accountApps('ethos')).toEqual([]);
  });

  it('links each application to /<name>/', () => {
    expect(appPath('ethos')).toBe('/ethos/');
    expect(() => appPath('//evil.com')).toThrow(TypeError);
  });
});

describe('app texts', () => {
  it('reads the texts of an application in the screen language', () => {
    expect(textsIn('pt', 'ethos')).toEqual({
      name: 'ethos',
      description: translations.pt.apps.ethos.description,
      deletion: translations.pt.apps.ethos.deletion,
      exportLabel: translations.pt.apps.ethos.export_label,
      exportPath: '/ethos/relatorio',
    });
    expect(textsIn('en', 'ethos').deletion).toBe(translations.en.apps.ethos.deletion);
  });

  it('falls back to the raw name for an application without texts', () => {
    expect(textsIn('en', 'engrafi')).toEqual({
      name: 'engrafi',
      description: null,
      deletion: null,
      exportLabel: null,
      exportPath: null,
    });
  });

  it('drops an export link to another origin', () => {
    const texts = { 'apps.x.export_path': 'https://evil.com/', 'apps.x.export_label': 'Export' };
    const result = appTexts('x', (key) => texts[key], (key) => key in texts);

    expect(result.exportPath).toBeNull();
    expect(result.exportLabel).toBeNull();
  });
});

// Checagem entre áreas: o .github/scripts/check-imago-apps.sh confere as chaves de cada aplicação
// do IMAGO_APPS; aqui, que as que existem estão completas e apontam para lugares de verdade
describe('app texts in translation.json', () => {
  const names = Object.keys(translations.en.apps);

  it('pt and en have the same applications, each with the 5 texts', () => {
    expect(Object.keys(translations.pt.apps).sort()).toEqual([...names].sort());
    expect(names).toContain('ethos');
    for (const language of LANGUAGES) {
      for (const name of names) {
        const texts = translations[language].apps[name];

        expect(isAppName(name), name).toBe(true);
        expect(Object.keys(texts).sort(), `${language}: ${name}`).toEqual([...APP_TEXT_KEYS].sort());
        expect(texts.export_path, `${language}: ${name}`).toMatch(new RegExp(`^/${name}/[a-z0-9/-]*$`));
        expect(texts.export_path).toBe(translations.en.apps[name].export_path);
      }
    }
  });

  it('the ethos export is the report screen, where "export everything" lives', () => {
    const paths = readFrontendFile('../../ethos/frontend/src/paths.js');
    const basename = /^export const BASENAME = '([^']+)';$/m.exec(paths)[1];
    const report = /^\s+report: '([^']+)',$/m.exec(paths)[1];
    const reportPage = readFrontendFile('../../ethos/frontend/src/pages/Report/index.jsx');

    expect(translations.en.apps.ethos.export_path).toBe(`${basename}${report}`);
    expect(reportPage).toContain('<ExportAll />');
  });
});
