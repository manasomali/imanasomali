// Fuso e dias locais. A API guarda e devolve tudo em UTC; a tela mostra no fuso de quem vê.
// Um dia local é uma string "AAAA-MM-DD" (o mesmo formato do from/to da API de progresso).
// As conversões seguem o backend (zoneinfo com fold=0, ver day_bounds em app/marks/service.py):
// - hora local que não existe (começo do horário de verão) usa o offset de antes da mudança,
//   então a meia-noite que não existe vira o instante da mudança;
// - hora local repetida (fim do horário de verão) fica com a primeira ocorrência.

const DAY_MS = 24 * 60 * 60 * 1000;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

const formatters = new Map();

function partsFormatter(timeZone) {
  let formatter = formatters.get(timeZone);
  if (!formatter) {
    // Lança RangeError para fuso desconhecido
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone,
      hourCycle: 'h23',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
    });
    formatters.set(timeZone, formatter);
  }
  return formatter;
}

// Date.UTC trata os anos 0 a 99 como 1900 a 1999; setUTCFullYear não
function utcMs(year, month, day, hour = 0, minute = 0, second = 0) {
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, 0);
  return date.getTime();
}

function wallClock(timeZone, ms) {
  const values = {};
  for (const { type, value } of partsFormatter(timeZone).formatToParts(new Date(ms))) {
    if (type !== 'literal') values[type] = Number(value);
  }
  return {
    year: values.year,
    month: values.month,
    day: values.day,
    // Motores antigos escrevem meia-noite como 24 mesmo com h23
    hour: values.hour % 24,
    minute: values.minute,
    second: values.second,
  };
}

// Diferença entre a hora local e o UTC em `ms`, em milissegundos (ex.: -3 h em São Paulo)
function offsetAt(timeZone, ms) {
  const wall = wallClock(timeZone, ms);
  const asUtc = utcMs(wall.year, wall.month, wall.day, wall.hour, wall.minute, wall.second);
  return asUtc - Math.floor(ms / 1000) * 1000;
}

function pad(value, length = 2) {
  return String(value).padStart(length, '0');
}

function formatDate(year, month, day) {
  return `${pad(year, 4)}-${pad(month)}-${pad(day)}`;
}

/** Converte "AAAA-MM-DD" em {year, month, day}; lança RangeError se a data não existe. */
export function parseDate(value) {
  const match = typeof value === 'string' ? DATE_RE.exec(value) : null;
  if (!match) throw new RangeError(`data inválida: ${value}`);
  const [year, month, day] = match.slice(1).map(Number);
  const check = new Date(utcMs(year, month, day));
  if (
    year < 1
    || check.getUTCFullYear() !== year
    || check.getUTCMonth() + 1 !== month
    || check.getUTCDate() !== day
  ) {
    throw new RangeError(`data inválida: ${value}`);
  }
  return { year, month, day };
}

/** Soma `days` (pode ser negativo) a um dia "AAAA-MM-DD". */
export function addDays(value, days) {
  const { year, month, day } = parseDate(value);
  const date = new Date(utcMs(year, month, day) + days * DAY_MS);
  return formatDate(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
}

/** Fuso IANA do navegador; "UTC" se o navegador não informar. */
export function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function isValidTimezone(timeZone) {
  if (typeof timeZone !== 'string' || timeZone === '') return false;
  try {
    partsFormatter(timeZone);
    return true;
  } catch {
    return false;
  }
}

function canonicalTimezone(timeZone) {
  try {
    return new Intl.DateTimeFormat('en-US', { timeZone }).resolvedOptions().timeZone;
  } catch {
    return timeZone;
  }
}

/** Mesmo fuso, aceitando grafias diferentes do mesmo nome (ex.: "utc" e "UTC"). */
export function sameTimezone(a, b) {
  return canonicalTimezone(a) === canonicalTimezone(b);
}

/** Dia local "AAAA-MM-DD" de um instante (Date, ms ou ISO) no fuso dado. */
export function localDate(instant, timeZone) {
  const wall = wallClock(timeZone, new Date(instant).getTime());
  return formatDate(wall.year, wall.month, wall.day);
}

/** Hoje, no fuso dado. */
export function today(timeZone, now = new Date()) {
  return localDate(now, timeZone);
}

/** Instante (Date) da hora local `hour:minute` do dia "AAAA-MM-DD" no fuso dado. */
export function zonedTimeToUtc(value, timeZone, hour = 0, minute = 0) {
  const { year, month, day } = parseDate(value);
  const wall = utcMs(year, month, day, hour, minute);
  // Offsets um dia antes e um dia depois: o instante procurado fica entre os dois (nenhum fuso
  // muda duas vezes em 48 h)
  const before = offsetAt(timeZone, wall - DAY_MS);
  const after = offsetAt(timeZone, wall + DAY_MS);
  const first = wall - before;
  if (offsetAt(timeZone, first) === before) return new Date(first);
  const second = wall - after;
  if (offsetAt(timeZone, second) === after) return new Date(second);
  // Hora que não existe: offset de antes da mudança (fold=0)
  return new Date(first);
}

/** Início e fim (exclusivo) do dia local, em UTC: o que o POST /habits/{id}/toggle espera. */
export function dayBounds(value, timeZone) {
  return {
    start: zonedTimeToUtc(value, timeZone),
    end: zonedTimeToUtc(addDays(value, 1), timeZone),
  };
}

/** 12:00 do dia local, em UTC: o instante gravado ao marcar um dia passado. */
export function pastDayNoon(value, timeZone) {
  return zonedTimeToUtc(value, timeZone, 12);
}

/**
 * Instante de uma marcação no dia `value`: hoje grava o instante atual, dia passado grava 12:00
 * local. Dia futuro lança RangeError (o backend também recusa).
 */
export function markedAtFor(value, timeZone, now = new Date()) {
  parseDate(value);
  const current = today(timeZone, now);
  if (value === current) return new Date(now.getTime());
  if (value < current) return pastDayNoon(value, timeZone);
  throw new RangeError(`dia no futuro: ${value}`);
}
