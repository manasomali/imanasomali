// Instantes da API (ISO 8601 em UTC) mostrados no fuso e no idioma de quem vê. Nunca usa os
// métodos locais de Date (seguem o fuso do sistema)

const formatters = new Map();

function formatter(language, timeZone) {
  const key = `${language}|${timeZone}`;
  let value = formatters.get(key);
  if (!value) {
    value = new Intl.DateTimeFormat(language, { timeZone, dateStyle: 'short', timeStyle: 'short' });
    formatters.set(key, value);
  }
  return value;
}

/**
 * Data e hora curtas de um instante (ISO, Date ou ms), no idioma e no fuso dados. Fuso que o
 * navegador não conhece cai no UTC (com o "UTC" escrito, para não parecer a hora local); idioma
 * inválido, no ISO 8601; instante inválido dá "".
 */
export function formatDateTime(instant, timeZone, language) {
  const date = new Date(instant);
  if (instant === null || instant === undefined || Number.isNaN(date.getTime())) return '';
  try {
    return formatter(language, timeZone).format(date);
  } catch {
    try {
      return `${formatter(language, 'UTC').format(date)} UTC`;
    } catch {
      return date.toISOString();
    }
  }
}
