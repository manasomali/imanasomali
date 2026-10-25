// Ajuda do app (ETH-40). Os textos ficam em src/help/<idioma>.json, no mesmo formato dos textos
// legais (src/lib/legal.js): texto puro, nunca HTML nem Markdown (o React escapa tudo),
//   { "title": "...", "sections": [{ "id": "...", "title": "...", "paragraphs": [...] }] }
// com cada item de `paragraphs` um parágrafo (string) ou uma lista (array de strings). O único
// marcador é {{supportEmail}}. Cada idioma vira um chunk com hash, baixado só quando a tela pede.
//
// A ajuda descreve o que o app faz HOJE: as regras vêm do backend (app/score.py,
// app/alerts/service.py, app/marks/service.py, app/sharing/service.py, app/auth/deletion.py).
// Os números que ela cita são conferidos contra o código em src/lib/help.test.js; mudar uma
// regra pede mudar o texto nos dois idiomas.

import { prepareLegalDocument } from './legal';

/**
 * As seções, na ordem da página. O `id` é a âncora (`/ajuda#alerts`), igual nos dois idiomas:
 * as telas apontam para elas pelo `helpPath` (src/paths.js) e o teste confere que os JSON têm
 * exatamente estas seções.
 */
export const HELP_SECTIONS = Object.freeze([
  'about',
  'marks',
  'goal',
  'not-doing',
  'score',
  'pause-archive',
  'sharing',
  'time-zone',
  'alerts',
  'cost',
  'report',
  'history',
  'account',
  'contact',
]);

// Idioma usado quando não há texto no pedido (o mesmo fallbackLng do i18n)
export const HELP_FALLBACK_LANGUAGE = 'en';

// Um import() por arquivo; o Vite gera um chunk para cada
const SOURCES = import.meta.glob('../help/*.json', { import: 'default' });

function sourcePath(language) {
  return `../help/${language}.json`;
}

/**
 * Carrega a ajuda no idioma pedido ('pt', 'en'; a região é ignorada, "pt-BR" vira "pt"). Sem texto
 * no idioma, cai no inglês; o `language` da resposta diz qual veio, para o `lang` do conteúdo.
 *
 * Devolve `{language, title, sections: [{id, title, paragraphs}]}`, com o email de suporte.
 */
export async function loadHelp(language) {
  const base = String(language ?? '').split('-')[0].toLowerCase();
  const resolved = Object.hasOwn(SOURCES, sourcePath(base)) ? base : HELP_FALLBACK_LANGUAGE;
  const raw = await SOURCES[sourcePath(resolved)]();
  return { language: resolved, ...prepareLegalDocument(raw) };
}
