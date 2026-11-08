// Aplicações da conta: os nomes vêm do GET /me (`apps`, o IMAGO_APPS do backend, na ordem dele) e
// cada uma fica em /<nome>/. Os textos de cada uma ficam nos translation.json do imago, em
// apps.<nome>.{name, description, deletion, export_label, export_path}; o CI confere que toda
// aplicação do IMAGO_APPS tem as 5 chaves em pt e en (.github/scripts/check-imago-apps.sh)

import { sameOriginPath } from './next';

// A mesma regra dos nomes do infra/databases.txt
const APP_NAME_RE = /^[a-z][a-z0-9-]{1,26}$/;

export const APP_TEXT_KEYS = Object.freeze(['name', 'description', 'deletion', 'export_label', 'export_path']);

export function isAppName(name) {
  return typeof name === 'string' && APP_NAME_RE.test(name);
}

/** Os nomes válidos de `apps`, sem repetição e na ordem recebida. Lista ausente ou inválida: []. */
export function accountApps(apps) {
  if (!Array.isArray(apps)) return [];
  return [...new Set(apps.filter(isAppName))];
}

/** Endereço da aplicação: "/ethos/". */
export function appPath(name) {
  if (!isAppName(name)) throw new TypeError(`nome de aplicação inválido: ${name}`);
  return `/${name}/`;
}

/**
 * Textos da aplicação `name`, com o `t` e o `exists` do i18n: `{name, description, deletion,
 * exportLabel, exportPath}`. Sem tradução (aplicação nova antes de o front ser atualizado), o
 * nome cru e o resto null. `exportPath` só vale se for um caminho da mesma origem.
 */
export function appTexts(name, t, exists) {
  const text = (key) => (exists(`apps.${name}.${key}`) ? t(`apps.${name}.${key}`) : null);
  const exportPath = sameOriginPath(text('export_path'));
  const exportLabel = text('export_label');
  return {
    name: text('name') ?? name,
    description: text('description'),
    deletion: text('deletion'),
    exportLabel: exportPath && exportLabel ? exportLabel : null,
    exportPath: exportPath && exportLabel ? exportPath : null,
  };
}
