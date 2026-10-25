// Período do relatório: datas locais "AAAA-MM-DD", as duas inclusivas, no fuso da conta (o mesmo
// formato do from/to do GET /habits/progress). A regra dos 5 anos é a do backend
// (`check_range` em app/progress/service.py): de 1/1/2021 vai até 31/12/2025; 1/1/2026 já seria
// 5 anos e 1 dia. De 29/2, o aniversário num ano que não é bissexto é 1/3.

import { isLeapYear, weekColumn } from '../calendar';
import { addDays, parseDate } from '../time';

/** Maior período de um relatório, em anos (ethos-plan.md, "relatório e export"). */
export const MAX_REPORT_YEARS = 5;

/** Primeiro dia que a API de progresso aceita (MIN_DAY em app/progress/schemas.py). */
export const MIN_REPORT_DAY = '1900-01-01';

const DAY_MS = 24 * 60 * 60 * 1000;

function pad(value, length = 2) {
  return String(value).padStart(length, '0');
}

function day(year, month, date) {
  return `${pad(year, 4)}-${pad(month)}-${pad(date)}`;
}

/** O dia `years` anos depois de `value` (29/2 vira 1/3 num ano que não é bissexto). */
export function addYears(value, years) {
  const { year, month, day: date } = parseDate(value);
  const target = year + years;
  if (month === 2 && date === 29 && !isLeapYear(target)) return day(target, 3, 1);
  return day(target, month, date);
}

/** Primeiro dia que já passa do período máximo que começa em `from`. */
export function rangeEnd(from) {
  return addYears(from, MAX_REPORT_YEARS);
}

/**
 * Confere o período escolhido. Devolve null se ele vale, ou o motivo: 'invalid' (data que não
 * existe ou vazia), 'order' (`to` antes de `from`) ou 'too_long' (mais de 5 anos).
 */
export function checkPeriod(from, to) {
  try {
    parseDate(from);
    parseDate(to);
  } catch {
    return 'invalid';
  }
  if (to < from) return 'order';
  if (to >= rangeEnd(from)) return 'too_long';
  return null;
}

/**
 * Divide um período de qualquer tamanho em pedaços que a API aceita (até 5 anos cada), em ordem:
 * `[{from, to}]`. O primeiro pedaço vai até 31/12 do 4º ano seguinte (menos de 5 anos); os outros
 * cobrem 5 anos de calendário inteiros. Usado pelo "exportar tudo".
 */
export function periodChunks(from, to) {
  if (checkPeriod(from, from) !== null || checkPeriod(to, to) !== null || to < from) {
    throw new RangeError(`período inválido: ${from} a ${to}`);
  }
  const chunks = [];
  let start = from;
  while (start <= to) {
    const lastOfBlock = day(parseDate(start).year + MAX_REPORT_YEARS - 1, 12, 31);
    const end = lastOfBlock < to ? lastOfBlock : to;
    chunks.push({ from: start, to: end });
    start = addDays(end, 1);
  }
  return chunks;
}

function dayNumber(value) {
  const { year, month, day: date } = parseDate(value);
  const utc = new Date(0);
  utc.setUTCFullYear(year, month - 1, date);
  return Math.round(utc.getTime() / DAY_MS);
}

/** Dias de `from` até `to` (0 no mesmo dia; negativo se `to` vem antes). */
export function daysBetween(from, to) {
  return dayNumber(to) - dayNumber(from);
}

/** Anos de calendário que o período toca, em ordem. */
export function yearsOf(from, to) {
  const first = parseDate(from).year;
  const last = parseDate(to).year;
  return Array.from({ length: Math.max(0, last - first + 1) }, (_, index) => first + index);
}

/**
 * Períodos prontos da tela, terminando hoje: 'week' (semana atual, começando no mesmo dia que as
 * semanas do calendário, WEEK_START), 'month' (mês atual), 'year' (ano atual), '12_months' (os
 * últimos 12 meses, até hoje) e '5_years' (o máximo: 5 anos até hoje).
 */
export const PERIOD_PRESETS = Object.freeze(['week', 'month', 'year', '12_months', '5_years']);

export function presetPeriod(preset, today) {
  const { year, month } = parseDate(today);
  switch (preset) {
    case 'week':
      return { from: addDays(today, -weekColumn(today)), to: today };
    case 'month':
      return { from: day(year, month, 1), to: today };
    case 'year':
      return { from: day(year, 1, 1), to: today };
    case '12_months':
      return { from: addDays(addYears(today, -1), 1), to: today };
    case '5_years':
      return { from: addDays(addYears(today, -MAX_REPORT_YEARS), 1), to: today };
    default:
      throw new RangeError(`período pronto desconhecido: ${preset}`);
  }
}
