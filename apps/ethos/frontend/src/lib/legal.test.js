import { describe, expect, it } from 'vitest';
import { LANGUAGES } from '../i18n';
import { readFrontendFile } from '../test/files';
import {
  LEGAL_DOCUMENTS,
  LEGAL_FALLBACK_LANGUAGE,
  SUPPORT_EMAIL,
  TERMS_VERSION,
  loadLegalDocument,
  prepareLegalDocument,
} from './legal';

// Os JSON como estão no repo, por idioma e documento: { pt: { terms, privacy }, en: {...} }
const FILES = import.meta.glob('../legal/*/*.json', { eager: true, import: 'default' });
const RAW = {};
for (const [path, content] of Object.entries(FILES)) {
  const [, language, name] = /^\.\.\/legal\/([^/]+)\/([^/]+)\.json$/.exec(path);
  RAW[language] = { ...RAW[language], [name]: content };
}

const MARK = '{{supportEmail}}';

/** Valor de `NOME = "valor"` (Python) ou `NOME=valor` (env) no começo de uma linha. */
function assignment(source, name) {
  const match = new RegExp(`^${name}\\s*=\\s*"?([^"\\n]+?)"?\\s*$`, 'm').exec(source);
  if (!match) throw new Error(`${name} não encontrado`);
  return match[1];
}

/** Todos os textos de um documento (títulos, parágrafos e itens de lista). */
function texts(document) {
  return [
    document.title,
    ...document.sections.flatMap((section) => [section.title, ...section.paragraphs.flat()]),
  ];
}

function sectionText(document, id) {
  const section = document.sections.find((item) => item.id === id);
  return section.paragraphs.flat().join(' ');
}

function isText(value) {
  return typeof value === 'string' && value.trim() !== '' && value === value.trim();
}

describe('legal texts versus the other areas', () => {
  // Checagem entre áreas: a versão que o front mostra é a que o backend pede para aceitar
  it('the version is the TERMS_VERSION of the backend', () => {
    const backend = assignment(readFrontendFile('../backend/app/terms.py'), 'TERMS_VERSION');

    expect(TERMS_VERSION).toBe(backend);
  });

  it('the version is a real date', () => {
    expect(TERMS_VERSION).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(new Date(`${TERMS_VERSION}T00:00:00Z`).toISOString().slice(0, 10)).toBe(TERMS_VERSION);
  });

  it('the support email is the SUPPORT_EMAIL of production', () => {
    const env = readFrontendFile('../../../infra/apps/ethos/app.env');

    expect(SUPPORT_EMAIL).toBe(assignment(env, 'SUPPORT_EMAIL'));
  });

  // Os prazos da política vêm do código: mudar um deles sem mudar o texto quebra aqui
  it('the privacy policy states the retention periods of the code', () => {
    const days = (source, name) =>
      Number(new RegExp(`^${name} = timedelta\\(days=(\\d+)\\)$`, 'm').exec(source)[1]);
    const audit = readFrontendFile('../backend/app/audit.py');
    const auth = readFrontendFile('../backend/app/auth/service.py');
    const snapshotDays = Number(
      assignment(readFrontendFile('../../../infra/scripts/snapshot.sh'), 'KEEP_DAYS'),
    );
    const litestreamHours = Number(
      /^\s+retention: (\d+)h$/m.exec(readFrontendFile('../../../infra/lib/backups.sh'))[1],
    );
    // A cópia mais antiga pode ter sido feita até 1 dia antes de o prazo começar a contar
    const backupDays = Math.max(snapshotDays, litestreamHours / 24) + 1;
    const periods = {
      session: days(auth, 'SESSION_LIFETIME'),
      code: Number(assignment(auth, 'CODE_LIFETIME_MINUTES')),
      authEvents: days(audit, 'AUTH_EVENT_RETENTION'),
      ip: days(audit, 'IP_RETENTION'),
    };
    const words = {
      pt: { day: 'dias', minute: 'minutos' },
      en: { day: 'days', minute: 'minutes' },
    };

    expect(periods).toEqual({ session: 60, code: 10, authEvents: 90, ip: 90 });
    for (const language of LANGUAGES) {
      const { day, minute } = words[language];
      const retention = sectionText(RAW[language].privacy, 'retention');

      expect(retention).toContain(`${periods.session} ${day}`);
      expect(retention).toContain(`${periods.code} ${minute}`);
      expect(retention).toContain(`${periods.authEvents} ${day}`);
      expect(retention).toContain(`${periods.ip} ${day}`);
      expect(retention).toContain(`${backupDays} ${day}`);
      expect(sectionText(RAW[language].privacy, 'deletion')).toContain(`${backupDays} ${day}`);
    }
  });
});

describe('legal texts', () => {
  it('every language of the app has every document, and nothing else', () => {
    expect(Object.keys(RAW).sort()).toEqual([...LANGUAGES].sort());
    for (const language of LANGUAGES) {
      expect(Object.keys(RAW[language]).sort()).toEqual([...LEGAL_DOCUMENTS].sort());
    }
    expect(LANGUAGES).toContain(LEGAL_FALLBACK_LANGUAGE);
  });

  it('pt and en have the same sections, in the same order and with the same shape', () => {
    const shape = (document) =>
      document.sections.map((section) => ({
        id: section.id,
        blocks: section.paragraphs.map((block) => (Array.isArray(block) ? block.length : 'p')),
      }));

    for (const name of LEGAL_DOCUMENTS) {
      expect(shape(RAW.pt[name]), name).toEqual(shape(RAW.en[name]));
    }
  });

  it('each document has the expected structure', () => {
    for (const language of LANGUAGES) {
      for (const name of LEGAL_DOCUMENTS) {
        const document = RAW[language][name];
        const where = `${language}/${name}`;

        expect(Object.keys(document).sort(), where).toEqual(['sections', 'title']);
        expect(isText(document.title), where).toBe(true);
        expect(document.sections.length, where).toBeGreaterThan(0);
        for (const section of document.sections) {
          const at = `${where}#${section.id}`;

          expect(Object.keys(section).sort(), at).toEqual(['id', 'paragraphs', 'title']);
          expect(section.id, at).toMatch(/^[a-z]+(-[a-z]+)*$/);
          expect(isText(section.title), at).toBe(true);
          expect(section.paragraphs.length, at).toBeGreaterThan(0);
          for (const block of section.paragraphs) {
            const items = Array.isArray(block) ? block : [block];

            expect(items.length, at).toBeGreaterThan(0);
            expect(items.every(isText), at).toBe(true);
          }
        }
        const ids = document.sections.map((section) => section.id);

        expect(new Set(ids).size, where).toBe(ids.length);
      }
    }
  });

  it('is plain text, with no markup and no placeholder but the support email', () => {
    for (const language of LANGUAGES) {
      for (const name of LEGAL_DOCUMENTS) {
        for (const text of texts(RAW[language][name])) {
          const rest = text.replaceAll(MARK, '');

          expect(rest, `${language}/${name}: ${text}`).not.toMatch(/[<>{}*`[\]]|https?:/);
        }
      }
    }
  });

  it('both documents end with the support contact', () => {
    for (const language of LANGUAGES) {
      for (const name of LEGAL_DOCUMENTS) {
        const { sections } = RAW[language][name];

        expect(sections.at(-1).id).toBe('contact');
        expect(sectionText(RAW[language][name], 'contact')).toContain(MARK);
      }
    }
  });
});

describe('loadLegalDocument', () => {
  it('loads the document in the language, with the support email filled in', async () => {
    const document = await loadLegalDocument('privacy', 'pt');

    expect(document.name).toBe('privacy');
    expect(document.language).toBe('pt');
    expect(document.version).toBe(TERMS_VERSION);
    expect(document.title).toBe(RAW.pt.privacy.title);
    expect(document.sections.map((section) => section.id)).toEqual(
      RAW.pt.privacy.sections.map((section) => section.id),
    );
    const all = texts(document).join('\n');

    expect(all).toContain(SUPPORT_EMAIL);
    expect(all).not.toContain(MARK);
  });

  it('fills the email inside lists too', async () => {
    const document = prepareLegalDocument({
      title: 'T',
      sections: [{ id: 'a', title: 'A', paragraphs: [`x ${MARK}`, [`y ${MARK} ${MARK}`, 'z']] }],
    });

    expect(document.sections[0].paragraphs).toEqual([
      `x ${SUPPORT_EMAIL}`,
      [`y ${SUPPORT_EMAIL} ${SUPPORT_EMAIL}`, 'z'],
    ]);
  });

  it('does not change the bundled texts', async () => {
    const before = JSON.stringify(RAW.en.terms);

    await loadLegalDocument('terms', 'en');

    expect(JSON.stringify(RAW.en.terms)).toBe(before);
    expect(before).toContain(MARK);
  });

  it('drops the region of the language', async () => {
    expect((await loadLegalDocument('terms', 'pt-BR')).language).toBe('pt');
    expect((await loadLegalDocument('terms', 'EN-us')).language).toBe('en');
  });

  it('falls back to English without a text in the language', async () => {
    for (const language of ['de', '', undefined, null, '../pt', 'pt/../en']) {
      const document = await loadLegalDocument('terms', language);

      expect(document.language, String(language)).toBe('en');
      expect(document.title).toBe(RAW.en.terms.title);
    }
  });

  it('refuses an unknown document', async () => {
    for (const name of ['cookies', '', undefined, '../pt/terms', 'constructor']) {
      await expect(loadLegalDocument(name, 'pt'), String(name)).rejects.toThrow(RangeError);
    }
  });
});
