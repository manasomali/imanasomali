// Lista de fusos IANA do seletor da tela de conta, com o offset atual e a busca. A lista vem do
// navegador (Intl.supportedValuesOf); sem ele, uma lista fixa dos fusos mais usados. O backend
// confere o nome contra a base de fusos dele (422 invalid_timezone), então a lista é só ajuda

import { isValidTimezone } from './time';

/** Usada quando o navegador não lista os fusos (sem Intl.supportedValuesOf). */
export const FALLBACK_TIMEZONES = Object.freeze([
  'Africa/Cairo',
  'Africa/Johannesburg',
  'Africa/Lagos',
  'Africa/Luanda',
  'Africa/Maputo',
  'Africa/Nairobi',
  'America/Anchorage',
  'America/Argentina/Buenos_Aires',
  'America/Bahia',
  'America/Belem',
  'America/Bogota',
  'America/Chicago',
  'America/Cuiaba',
  'America/Denver',
  'America/Fortaleza',
  'America/Halifax',
  'America/Lima',
  'America/Los_Angeles',
  'America/Manaus',
  'America/Mexico_City',
  'America/New_York',
  'America/Noronha',
  'America/Phoenix',
  'America/Porto_Velho',
  'America/Recife',
  'America/Rio_Branco',
  'America/Santiago',
  'America/Sao_Paulo',
  'America/Toronto',
  'America/Vancouver',
  'Asia/Bangkok',
  'Asia/Dubai',
  'Asia/Hong_Kong',
  'Asia/Jakarta',
  'Asia/Jerusalem',
  'Asia/Kolkata',
  'Asia/Seoul',
  'Asia/Shanghai',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Atlantic/Azores',
  'Atlantic/Cape_Verde',
  'Atlantic/Madeira',
  'Australia/Melbourne',
  'Australia/Perth',
  'Australia/Sydney',
  'Europe/Amsterdam',
  'Europe/Berlin',
  'Europe/Dublin',
  'Europe/Istanbul',
  'Europe/Lisbon',
  'Europe/London',
  'Europe/Madrid',
  'Europe/Moscow',
  'Europe/Paris',
  'Europe/Rome',
  'Europe/Warsaw',
  'Europe/Zurich',
  'Pacific/Auckland',
  'Pacific/Honolulu',
  'UTC',
]);

/**
 * Fusos que o navegador conhece. `supportedValuesOf` é o Intl.supportedValuesOf (os testes
 * trocam); ausente, lançando ou devolvendo lista vazia: FALLBACK_TIMEZONES.
 */
export function availableTimezones(supportedValuesOf = Intl.supportedValuesOf) {
  if (typeof supportedValuesOf === 'function') {
    try {
      const list = supportedValuesOf.call(Intl, 'timeZone');
      if (Array.isArray(list) && list.length > 0) return list;
    } catch {
      // Navegador antigo ou implementação incompleta: a lista fixa
    }
  }
  return FALLBACK_TIMEZONES;
}

/**
 * Offset do fuso no instante `now`, como "UTC-03:00" ("UTC+00:00" no próprio UTC); "" se o
 * navegador não souber calcular.
 */
export function timezoneOffset(timeZone, now = new Date()) {
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone, timeZoneName: 'longOffset' })
      .formatToParts(now);
    const name = parts.find((part) => part.type === 'timeZoneName')?.value ?? '';
    // "GMT-03:00", "GMT+05:45" ou só "GMT" no offset zero; alguns motores usam o sinal U+2212
    const match = /^GMT(?:([+−-])(\d{2}):(\d{2}))?$/.exec(name);
    if (!match) return '';
    if (!match[1]) return 'UTC+00:00';
    return `UTC${match[1] === '+' ? '+' : '-'}${match[2]}:${match[3]}`;
  } catch {
    return '';
  }
}

/** Nome para a tela: "America/Sao_Paulo" vira "America/Sao Paulo". */
export function timezoneLabel(timeZone) {
  return timeZone.replaceAll('_', ' ');
}

// Minúsculas, sem acento e com "_" como espaço, para "são paulo" achar "America/Sao_Paulo"
function normalize(text) {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').replaceAll('_', ' ').toLowerCase();
}

/**
 * Opções do seletor: os fusos do navegador mais `extra` (o fuso da conta e o sugerido, que podem
 * ter grafia que a lista não traz, ex.: "Asia/Kolkata" e "Asia/Calcutta") e o UTC, sem repetição
 * e em ordem alfabética. Nome que o navegador não reconhece fica de fora. Cada uma traz
 * `{value, label, offset, search}`; `search` é o texto normalizado da busca.
 */
export function timezoneOptions({ extra = [], now = new Date(), supportedValuesOf } = {}) {
  const names = new Set(availableTimezones(supportedValuesOf));
  for (const name of ['UTC', ...extra]) names.add(name);
  return [...names]
    .filter((name) => isValidTimezone(name))
    .sort()
    .map((value) => {
      const label = timezoneLabel(value);
      const offset = timezoneOffset(value, now);
      return { value, label, offset, search: normalize(`${value} ${offset}`) };
    });
}

/**
 * As opções que batem com a busca: cada palavra de `query` (separadas por espaço ou "/") precisa
 * aparecer no nome ou no offset, sem diferenciar maiúsculas nem acentos. Busca vazia: todas.
 */
export function filterTimezones(options, query) {
  const words = normalize(String(query ?? '')).split(/[\s/]+/).filter(Boolean);
  if (words.length === 0) return options;
  return options.filter((option) => words.every((word) => option.search.includes(word)));
}
