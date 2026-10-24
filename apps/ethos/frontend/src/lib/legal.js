// Termos de uso e política de privacidade (ETH-30). Os textos ficam em src/legal/<idioma>/<doc>.json
// e entram no build como chunks separados, com hash no nome: só são baixados quando uma tela os
// pede, e uma aba aberta antes de um deploy continua lendo a versão que ela conhece (o deploy não
// apaga os assets antigos na hora), igual ao TERMS_VERSION do bundle dela.
//
// Formato de cada arquivo (texto puro, nunca HTML nem Markdown; o React escapa tudo):
//   { "title": "...", "sections": [{ "id": "...", "title": "...", "paragraphs": [...] }] }
// Cada item de `paragraphs` é um parágrafo (string) ou uma lista (array de strings, um item cada).
// `id` é igual em pt e en (serve de âncora). O único marcador é {{supportEmail}}, trocado aqui
// pelo SUPPORT_EMAIL. Os testes (src/lib/legal.test.js) conferem tudo isso.

/**
 * Versão atual dos textos, igual ao TERMS_VERSION de apps/ethos/backend/app/terms.py (o teste
 * falha se forem diferentes). É uma data (AAAA-MM-DD): para publicar uma versão nova, mude os
 * textos e as duas constantes no mesmo PR; quem aceitou a anterior aceita de novo no próximo acesso.
 */
export const TERMS_VERSION = '2026-10-24';

/**
 * Email de suporte mostrado nos textos (troca de email, exclusão de conta bloqueada, contato).
 * Fixo no build, igual ao SUPPORT_EMAIL de produção em infra/apps/ethos/app.env (o teste falha
 * se forem diferentes). O backend não expõe esse valor, e as páginas legais abrem sem login.
 */
export const SUPPORT_EMAIL = 'suporte@manasomali.com';

export const LEGAL_DOCUMENTS = Object.freeze(['terms', 'privacy']);

// Idioma usado quando não há texto no pedido (o mesmo fallbackLng do i18n)
export const LEGAL_FALLBACK_LANGUAGE = 'en';

const SUPPORT_EMAIL_MARK = '{{supportEmail}}';

// Um import() por arquivo; o Vite gera um chunk para cada
const SOURCES = import.meta.glob('../legal/*/*.json', { import: 'default' });

function sourcePath(language, name) {
  return `../legal/${language}/${name}.json`;
}

function fill(text) {
  return text.replaceAll(SUPPORT_EMAIL_MARK, SUPPORT_EMAIL);
}

/** Troca o marcador dos textos de um documento, sem alterar o objeto recebido. */
export function prepareLegalDocument(raw) {
  return {
    title: raw.title,
    sections: raw.sections.map((section) => ({
      id: section.id,
      title: section.title,
      paragraphs: section.paragraphs.map((block) =>
        Array.isArray(block) ? block.map(fill) : fill(block),
      ),
    })),
  };
}

/**
 * Carrega um documento ('terms' ou 'privacy') no idioma pedido ('pt', 'en'; a região é ignorada,
 * "pt-BR" vira "pt"). Sem texto no idioma, cai no inglês; o `language` da resposta diz qual veio,
 * para o `lang` do conteúdo. Documento desconhecido: RangeError.
 *
 * Devolve `{name, language, version, title, sections: [{id, title, paragraphs}]}`.
 */
export async function loadLegalDocument(name, language) {
  if (!LEGAL_DOCUMENTS.includes(name)) {
    throw new RangeError(`documento legal desconhecido: ${name}`);
  }
  const base = String(language ?? '').split('-')[0].toLowerCase();
  const resolved = Object.hasOwn(SOURCES, sourcePath(base, name)) ? base : LEGAL_FALLBACK_LANGUAGE;
  const raw = await SOURCES[sourcePath(resolved, name)]();
  return { name, language: resolved, version: TERMS_VERSION, ...prepareLegalDocument(raw) };
}
