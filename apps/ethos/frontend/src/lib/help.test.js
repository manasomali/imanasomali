import { describe, expect, it } from 'vitest';
import { LANGUAGES } from '../i18n';
import { PATHS, helpPath } from '../paths';
import { readFrontendFile } from '../test/files';
import { translations } from '../test/i18n';
import { COST_WARNING_PERCENT, DEFAULT_HOUR, formatHour, weeklyPaceStart } from './alerts';
import { MIN_COLOR_CONTRAST } from './customColor';
import { weekdayNames } from './format';
import { DEFAULT_SCORE_THRESHOLD, MAX_MARKS_PER_DAY, PERIOD_DAYS } from './habitForm';
import { HELP_FALLBACK_LANGUAGE, HELP_LINKS, HELP_SECTIONS, loadHelp } from './help';
import { SUPPORT_EMAIL } from './legal';
import { HABIT_COLORS } from './palette';

// Os JSON como estão no repo, por idioma: { pt: {...}, en: {...} }
const FILES = import.meta.glob('../help/*.json', { eager: true, import: 'default' });
const RAW = {};
for (const [path, content] of Object.entries(FILES)) {
  const [, language] = /^\.\.\/help\/([^/]+)\.json$/.exec(path);
  RAW[language] = content;
}

const MARK = '{{supportEmail}}';
const WEEK_SECONDS = 7 * 24 * 60 * 60;

/** O texto de um bloco: o parágrafo, os itens da lista ou o rótulo do link. */
function blockTexts(block) {
  if (Array.isArray(block)) return block;
  return typeof block === 'object' ? [block.label] : [block];
}

/** Todos os textos (títulos, parágrafos, itens de lista e rótulos de link). */
function texts(document) {
  return [
    document.title,
    ...document.sections.flatMap((section) => [section.title, ...section.paragraphs.flatMap(blockTexts)]),
  ];
}

/** O texto de uma seção, num espaço só entre as palavras (o Intl usa espaços especiais). */
function sectionText(language, id) {
  const section = RAW[language].sections.find((item) => item.id === id);
  return normalize(section.paragraphs.flatMap(blockTexts).join(' '));
}

function normalize(text) {
  return text.replace(/\s+/gu, ' ');
}

/** Se o texto cita o número `n` sozinho (não como parte de 140 nem de 8,00). */
function citesNumber(text, n) {
  return new RegExp(`(?<![\\d.,])${n}(?!\\d|[.,]\\d)`).test(text);
}

function isText(value) {
  return typeof value === 'string' && value.trim() !== '' && value === value.trim();
}

/** Valor de `NOME=valor` no começo de uma linha do app.env. */
function envValue(source, name) {
  const match = new RegExp(`^${name}=(\\d+)$`, 'm').exec(source);
  if (!match) throw new Error(`${name} não encontrado`);
  return Number(match[1]);
}

/** Horário em que o ritmo semanal de `target` pede `count` marcações: {weekday, time} no idioma. */
function paceMoment(target, count, language) {
  const minutes = Math.floor(Math.ceil((count * WEEK_SECONDS) / target) / 60);
  return {
    weekday: weekdayNames(language)[Math.floor(minutes / (24 * 60))].long,
    time: normalize(formatHour(Math.floor(minutes / 60) % 24, language, minutes % 60)),
  };
}

describe('help texts', () => {
  it('every language of the app has the help, and nothing else', () => {
    expect(Object.keys(RAW).sort()).toEqual([...LANGUAGES].sort());
    expect(LANGUAGES).toContain(HELP_FALLBACK_LANGUAGE);
  });

  it('pt and en have the same sections as HELP_SECTIONS, in order and with the same shape', () => {
    const shape = (document) =>
      document.sections.map((section) => ({
        id: section.id,
        blocks: section.paragraphs.map((block) => {
          if (Array.isArray(block)) return block.length;
          return typeof block === 'object' ? `link ${block.href}` : 'p';
        }),
      }));

    expect(RAW.pt.sections.map((section) => section.id)).toEqual([...HELP_SECTIONS]);
    expect(RAW.en.sections.map((section) => section.id)).toEqual([...HELP_SECTIONS]);
    expect(shape(RAW.pt)).toEqual(shape(RAW.en));
    expect(new Set(HELP_SECTIONS).size).toBe(HELP_SECTIONS.length);
  });

  it('each language has the expected structure', () => {
    for (const language of LANGUAGES) {
      const document = RAW[language];

      expect(Object.keys(document).sort(), language).toEqual(['sections', 'title']);
      expect(isText(document.title), language).toBe(true);
      for (const section of document.sections) {
        const at = `${language}#${section.id}`;

        expect(Object.keys(section).sort(), at).toEqual(['id', 'paragraphs', 'title']);
        expect(section.id, at).toMatch(/^[a-z]+(-[a-z]+)*$/);
        expect(isText(section.title), at).toBe(true);
        expect(section.paragraphs.length, at).toBeGreaterThan(0);
        for (const block of section.paragraphs) {
          if (block !== null && typeof block === 'object' && !Array.isArray(block)) {
            // Link externo: só os da lista, sempre https, com um rótulo de texto
            expect(Object.keys(block).sort(), at).toEqual(['href', 'label']);
            expect(HELP_LINKS, at).toContain(block.href);
            expect(isText(block.label), at).toBe(true);
            continue;
          }
          const items = Array.isArray(block) ? block : [block];

          expect(items.length, at).toBeGreaterThan(0);
          expect(items.every(isText), at).toBe(true);
        }
      }
    }
  });

  it('links only to https addresses of the list, each one used', () => {
    for (const href of HELP_LINKS) {
      expect(new URL(href).protocol).toBe('https:');
      for (const language of LANGUAGES) {
        const used = RAW[language].sections.some((section) =>
          section.paragraphs.some((block) => block?.href === href),
        );
        expect(used, `${language}: ${href}`).toBe(true);
      }
    }
  });

  it('credits the inspiration by name', () => {
    for (const language of LANGUAGES) {
      const inspiration = sectionText(language, 'inspiration');
      expect(inspiration).toContain('Every Day Goal Calendar');
      expect(inspiration).toContain('Simone Giertz');
    }
  });

  it('is plain text, with no markup and no placeholder but the support email', () => {
    for (const language of LANGUAGES) {
      for (const text of texts(RAW[language])) {
        expect(text.replaceAll(MARK, ''), `${language}: ${text}`).not.toMatch(/[<>{}*`[\]]|https?:/);
      }
    }
  });

  it('the page title is the one of the menu and of the browser tab', () => {
    for (const language of LANGUAGES) {
      expect(RAW[language].title).toBe(translations[language].pages.help.title);
      expect(RAW[language].title).toBe(translations[language].menu.help);
    }
  });

  it('ends with the support contact', () => {
    for (const language of LANGUAGES) {
      expect(RAW[language].sections.at(-1).id).toBe('contact');
      expect(sectionText(language, 'contact')).toContain(MARK);
      expect(sectionText(language, 'account')).toContain(MARK);
    }
  });
});

// A ajuda cita números e horários das regras: vêm do código (que os testes de src/lib conferem
// com o backend) e de infra/apps/ethos/app.env. Mudar a regra sem mudar o texto quebra aqui
describe('help texts versus the code', () => {
  const env = readFrontendFile('../../../infra/apps/ethos/app.env');

  it('the score: default threshold, rounding and "no data" as the screen says it', () => {
    for (const language of LANGUAGES) {
      const score = sectionText(language, 'score');

      expect(score).toContain(`${DEFAULT_SCORE_THRESHOLD}`);
      // 2 de 3 = 66,7 arredonda meio para cima: 67
      expect(score).toContain(`${Math.floor((200 / 3) + 0.5)}`);
      expect(score).toContain(`“${translations[language].habit.score.no_data}”`);
    }
  });

  // ETH-53: o período atual conta, na pontuação e no resumo do relatório (src/lib/export/report.js)
  it('the report summary: the label of the screen and the current period', () => {
    for (const language of LANGUAGES) {
      const report = sectionText(language, 'report');

      expect(report).toContain(`“${translations[language].report.periods}”`);
    }
  });

  it('the pace example of "3 times per week" uses the real moments of the pace', () => {
    for (const language of LANGUAGES) {
      const alerts = sectionText(language, 'alerts');
      const first = weeklyPaceStart(3);
      const one = paceMoment(3, 1, language);
      const two = paceMoment(3, 2, language);
      const alertTime = normalize(formatHour(DEFAULT_HOUR, language));

      // O helper do teste concorda com o da tela
      expect(one.weekday).toBe(weekdayNames(language)[first.weekday].long);
      expect(one.time).toBe(normalize(formatHour(first.hour, language, first.minute)));
      expect(alerts).toContain(`${one.weekday}`);
      expect(alerts).toContain(one.time);
      expect(alerts).toContain(two.weekday);
      expect(alerts).toContain(two.time);
      expect(alerts).toContain(alertTime);
      // 3 × 56 h ÷ 168 h = 1: a quarta às 08:00 é a 56ª hora da semana
      expect(Math.ceil(WEEK_SECONDS / 3) / 3600).toBe(56);
      expect(alerts).toContain('3 × 56 h ÷ 168 h = 1');
      expect(alerts).toContain(`${COST_WARNING_PERCENT}%`);
    }
  });

  it('the pace in minutes: 120 min per week asks for 14 min on Monday at the alert hour', () => {
    const target = 3 * 40;
    const expected = Math.floor((target * DEFAULT_HOUR * 3600) / WEEK_SECONDS);

    expect(expected).toBe(14);
    for (const language of LANGUAGES) {
      const alerts = sectionText(language, 'alerts');

      expect(alerts).toContain(`${target} min`);
      expect(alerts).toContain(`${expected} min`);
    }
  });

  it('the goal caps and the limits of the service', () => {
    const habits = envValue(env, 'MAX_HABITS_PER_USER');
    const guests = envValue(env, 'MAX_GUESTS_PER_HABIT');
    const invites = envValue(env, 'MAX_INVITES_PER_DAY');
    const shared = envValue(env, 'MAX_SHARED_HABITS_PER_USER');
    const note = envValue(env, 'MAX_NOTE_LENGTH');

    expect(envValue(env, 'MAX_MARKS_PER_DAY')).toBe(MAX_MARKS_PER_DAY);
    for (const language of LANGUAGES) {
      const goal = sectionText(language, 'goal');
      const sharing = sectionText(language, 'sharing');
      const marks = sectionText(language, 'marks');

      for (const days of Object.values(PERIOD_DAYS)) expect(citesNumber(goal, days), `${days}`).toBe(true);
      expect(citesNumber(sectionText(language, 'about'), habits)).toBe(true);
      expect(citesNumber(marks, MAX_MARKS_PER_DAY)).toBe(true);
      expect(citesNumber(marks, note)).toBe(true);
      expect(citesNumber(sharing, guests)).toBe(true);
      expect(citesNumber(sharing, invites)).toBe(true);
      expect(citesNumber(sharing, shared)).toBe(true);
    }
  });

  it('the colours: the size of the palette and the minimum contrast (ETH-49)', () => {
    for (const language of LANGUAGES) {
      const goal = sectionText(language, 'goal');

      expect(citesNumber(goal, HABIT_COLORS.length)).toBe(true);
      expect(goal).toContain(`${MIN_COLOR_CONTRAST}:1`);
    }
  });

  // Os mesmos prazos que src/lib/legal.test.js confere na política de privacidade
  it('the account: code, session and backups as in the code', () => {
    const days = { pt: 'dias', en: 'days' };
    const minutes = { pt: 'minutos', en: 'minutes' };
    const snapshotDays = Number(
      /^KEEP_DAYS=(\d+)$/m.exec(readFrontendFile('../../../infra/scripts/snapshot.sh'))[1],
    );
    const litestreamHours = Number(
      /^\s+retention: (\d+)h$/m.exec(readFrontendFile('../../../infra/lib/backups.sh'))[1],
    );
    // A cópia mais antiga pode ter sido feita até 1 dia antes de o prazo começar a contar
    const backup = Math.max(snapshotDays, litestreamHours / 24) + 1;
    for (const language of LANGUAGES) {
      const account = sectionText(language, 'account');

      expect(account).toContain(`${backup} ${days[language]}`);
      expect(account).toContain(`60 ${days[language]}`);
      expect(account).toContain(`10 ${minutes[language]}`);
    }
  });
});

describe('loadHelp', () => {
  it('loads the language, with the support email filled in', async () => {
    const help = await loadHelp('pt');

    expect(help.language).toBe('pt');
    expect(help.title).toBe(RAW.pt.title);
    expect(help.sections.map((section) => section.id)).toEqual([...HELP_SECTIONS]);
    const all = texts(help).join('\n');

    expect(all).toContain(SUPPORT_EMAIL);
    expect(all).not.toContain(MARK);
    // Não muda o JSON do bundle
    expect(JSON.stringify(RAW.pt)).toContain(MARK);
  });

  it('drops the region of the language', async () => {
    expect((await loadHelp('pt-BR')).language).toBe('pt');
    expect((await loadHelp('EN-us')).language).toBe('en');
  });

  it('falls back to English without a text in the language', async () => {
    for (const language of ['de', '', undefined, null, '../pt', 'pt/../en', '../legal/pt/terms']) {
      const help = await loadHelp(language);

      expect(help.language, String(language)).toBe('en');
      expect(help.title).toBe(RAW.en.title);
    }
  });
});

describe('helpPath', () => {
  it('points to a section of the help', () => {
    expect(helpPath()).toBe(PATHS.help);
    expect(helpPath('alerts')).toBe(`${PATHS.help}#alerts`);
    for (const section of HELP_SECTIONS) expect(helpPath(section)).toBe(`${PATHS.help}#${section}`);
  });

  it('refuses a section that does not exist', () => {
    for (const section of ['nope', '', 'constructor', 'alerts#x', 'Alerts']) {
      expect(() => helpPath(section), String(section)).toThrow(RangeError);
    }
  });
});
