// Data e hora no fuso de quem vê, para mostrar instantes da API e editar com
// <input type="datetime-local">. Nunca usa os métodos locais de Date (seguem o fuso do sistema)

import { localDate, parseDate, zonedTimeToUtc } from './time';

// "AAAA-MM-DDTHH:mm", com ":00" opcional (o navegador manda os segundos só com `step` menor)
const DATETIME_LOCAL_RE = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::00(?:\.0{1,3})?)?$/;

const clockFormatters = new Map();
const displayFormatters = new Map();

function clockFormatter(timeZone) {
  let formatter = clockFormatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone,
      hourCycle: 'h23',
      hour: 'numeric',
      minute: 'numeric',
    });
    clockFormatters.set(timeZone, formatter);
  }
  return formatter;
}

function pad(value) {
  return String(value).padStart(2, '0');
}

/** Valor de um datetime-local ("AAAA-MM-DDTHH:mm") para o instante no fuso dado. */
export function toDateTimeLocal(instant, timeZone) {
  const date = new Date(instant);
  const values = {};
  for (const { type, value } of clockFormatter(timeZone).formatToParts(date)) {
    if (type === 'hour' || type === 'minute') values[type] = Number(value);
  }
  // Motores antigos escrevem meia-noite como 24 mesmo com h23
  return `${localDate(date, timeZone)}T${pad(values.hour % 24)}:${pad(values.minute)}`;
}

/**
 * Instante (Date) de um valor de datetime-local, lido no fuso dado; null se o valor não é uma data
 * e hora válidas. Hora que não existe ou se repete (horário de verão) segue zonedTimeToUtc.
 */
export function fromDateTimeLocal(value, timeZone) {
  const match = typeof value === 'string' ? DATETIME_LOCAL_RE.exec(value) : null;
  if (!match) return null;
  const hour = Number(match[2]);
  const minute = Number(match[3]);
  if (hour > 23 || minute > 59) return null;
  try {
    parseDate(match[1]);
  } catch {
    return null;
  }
  return zonedTimeToUtc(match[1], timeZone, hour, minute);
}

/** Data e hora curtas de um instante (ISO, Date ou ms), no idioma e no fuso dados. */
export function formatDateTime(instant, timeZone, language) {
  const key = `${language}|${timeZone}`;
  let formatter = displayFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(language, {
      timeZone,
      dateStyle: 'short',
      timeStyle: 'short',
    });
    displayFormatters.set(key, formatter);
  }
  return formatter.format(new Date(instant));
}
