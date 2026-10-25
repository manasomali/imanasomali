// Datas formatadas para a tela, no idioma dado. Dias "AAAA-MM-DD" não têm fuso: são formatados em
// UTC, onde a meia-noite do dia é o próprio dia. Instantes da API (UTC) são mostrados no fuso de
// quem vê

import { CALENDAR_WEEKDAYS } from './calendar';
import { parseDate } from './time';

const formatters = new Map();

function formatter(locale, options) {
  const key = `${locale}|${JSON.stringify(options)}`;
  let value = formatters.get(key);
  if (!value) {
    value = new Intl.DateTimeFormat(locale, options);
    formatters.set(key, value);
  }
  return value;
}

function dayDate(value) {
  const { year, month, day } = parseDate(value);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  return date;
}

/** "quarta-feira, 4 de março de 2026" / "Wednesday, March 4, 2026". */
export function formatLongDay(value, locale) {
  return formatter(locale, { timeZone: 'UTC', dateStyle: 'full' }).format(dayDate(value));
}

/** "4 de mar. de 2026" / "Mar 4, 2026". */
export function formatShortDay(value, locale) {
  return formatter(locale, { timeZone: 'UTC', dateStyle: 'medium' }).format(dayDate(value));
}

/** Nome do mês ("março" / "March"). `month` de 1 a 12. */
export function formatMonth(month, locale) {
  const date = new Date(0);
  date.setUTCFullYear(2000, month - 1, 1);
  return formatter(locale, { timeZone: 'UTC', month: 'long' }).format(date);
}

/**
 * Iniciais dos dias da semana e os nomes completos (para leitores), de segunda a domingo: o índice
 * é o `weekday` da API (0 = segunda). Para o cabeçalho do calendário, use calendarWeekdayNames.
 */
export function weekdayNames(locale) {
  // 2024-01-01 foi uma segunda
  return Array.from({ length: 7 }, (_, index) => {
    const date = dayDate(`2024-01-0${index + 1}`);
    return {
      short: formatter(locale, { timeZone: 'UTC', weekday: 'narrow' }).format(date),
      long: formatter(locale, { timeZone: 'UTC', weekday: 'long' }).format(date),
    };
  });
}

/** Os dias de weekdayNames na ordem das colunas do calendário (começa no domingo). */
export function calendarWeekdayNames(locale) {
  const names = weekdayNames(locale);
  return CALENDAR_WEEKDAYS.map((weekday) => names[weekday - 1]);
}

/** Hora ("14:05" / "2:05 PM") de um instante (ISO, Date ou ms) no fuso dado. */
export function formatTime(instant, timeZone, locale) {
  return formatter(locale, { timeZone, timeStyle: 'short' }).format(new Date(instant));
}

/** Data de um instante no fuso dado ("4 de mar. de 2026" / "Mar 4, 2026"). */
export function formatDate(instant, timeZone, locale) {
  return formatter(locale, { timeZone, dateStyle: 'medium' }).format(new Date(instant));
}

/** Data e hora curtas de um instante no fuso dado. */
export function formatDateTime(instant, timeZone, locale) {
  return formatter(locale, { timeZone, dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(instant),
  );
}
