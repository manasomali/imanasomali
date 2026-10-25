// Calendário anual: meses, dias, intervalo do ano em UTC e agrupamento das marcações por dia local.
// Dias são strings "AAAA-MM-DD" (como em time.js), que comparam certo como texto. No desenho, a
// semana começa no domingo (WEEK_START); os períodos da meta continuam na semana ISO, de segunda a
// domingo (periodFirstDay em alerts.js e score.py no backend).

import { addDays, localDate, parseDate, zonedTimeToUtc } from './time';

// Primeiro ano navegável. A API recusa instantes antes de 1900-01-01 UTC (MIN_INSTANT em
// app/marks/schemas.py), e o 1º de janeiro de 1900 num fuso a leste de UTC começa em 1899
export const MIN_YEAR = 1901;

// Pontos coloridos por dia na aba principal; o resto vira "+N"
export const MAX_DOTS = 4;

export function isLeapYear(year) {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

export function daysInYear(year) {
  return isLeapYear(year) ? 366 : 365;
}

/** Dia da semana ISO de "AAAA-MM-DD": 1 (segunda) a 7 (domingo). */
export function isoWeekday(value) {
  const { year, month, day } = parseDate(value);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  return date.getUTCDay() || 7;
}

// Dia da semana ISO da primeira coluna do calendário: 7 = domingo. Só muda o desenho
export const WEEK_START = 7;

/** Os dias da semana ISO (1 = segunda ... 7 = domingo) na ordem das colunas do calendário. */
export const CALENDAR_WEEKDAYS = Object.freeze(
  Array.from({ length: 7 }, (_, column) => ((WEEK_START - 1 + column) % 7) + 1),
);

/** Coluna de "AAAA-MM-DD" no calendário: 0 (WEEK_START, domingo) a 6 (sábado). */
export function weekColumn(value) {
  return (isoWeekday(value) - WEEK_START + 7) % 7;
}

function pad(value) {
  return String(value).padStart(2, '0');
}

/** O ano como texto de 4 dígitos, para montar "AAAA-MM-DD". */
function yearText(year) {
  return String(year).padStart(4, '0');
}

/**
 * Um mês do calendário: `{year, month, days, offset}`, com `month` de 1 a 12, `days` os dias
 * "AAAA-MM-DD" em ordem e `offset` as casas vazias antes do dia 1 (a coluna dele, de 0 a 6, numa
 * semana que começa em WEEK_START).
 */
export function calendarMonth(year, month) {
  const prefix = `${yearText(year)}-${pad(month)}-`;
  const days = Array.from(
    { length: daysInMonth(year, month) },
    (_, index) => `${prefix}${pad(index + 1)}`,
  );
  return { year, month, days, offset: weekColumn(days[0]) };
}

/** Os 12 meses do ano, como em calendarMonth. */
export function yearMonths(year) {
  return Array.from({ length: 12 }, (_, index) => calendarMonth(year, index + 1));
}

/**
 * Intervalo do ano no fuso dado, em UTC: `from` é a meia-noite local de 1º de janeiro e `to` a do
 * ano seguinte (exclusivo). É o `from`/`to` do GET /habits/{id}/marks (até 367 dias).
 */
export function yearRange(year, timeZone) {
  return {
    from: zonedTimeToUtc(`${yearText(year)}-01-01`, timeZone),
    to: zonedTimeToUtc(`${yearText(year + 1)}-01-01`, timeZone),
  };
}

/** Ano de um dia "AAAA-MM-DD". */
export function yearOf(value) {
  return parseDate(value).year;
}

/**
 * Lê um ano da URL: inteiro entre `min` e `max`, ou null. Recusa "2026.5", " 2026", "+2026" etc.
 */
export function parseYear(value, { min = MIN_YEAR, max } = {}) {
  if (typeof value !== 'string' || !/^\d{4}$/.test(value)) return null;
  const year = Number(value);
  if (year < min || (max !== undefined && year > max)) return null;
  return year;
}

/** Lê um dia da URL: "AAAA-MM-DD" que existe, ou null. */
export function parseDay(value) {
  try {
    parseDate(value);
    return value;
  } catch {
    return null;
  }
}

/**
 * Agrupa marcações (`{marked_at}` em UTC) pelo dia local no fuso dado: Map de "AAAA-MM-DD" para
 * a lista, na ordem recebida.
 */
export function marksByDay(marks, timeZone) {
  const days = new Map();
  for (const mark of marks) {
    const day = localDate(mark.marked_at, timeZone);
    const list = days.get(day);
    if (list) list.push(mark);
    else days.set(day, [mark]);
  }
  return days;
}

/** Até `max` itens visíveis e quantos sobram (o "+N"). */
export function splitDots(items, max = MAX_DOTS) {
  if (items.length <= max) return { shown: items, extra: 0 };
  return { shown: items.slice(0, max), extra: items.length - max };
}

/**
 * Visão de todos os hábitos por dia (aba principal). `habits` na ordem da tela e `byHabit` o Map
 * do id para o Map dia → marcações (de marksByDay). Devolve Map "AAAA-MM-DD" → `{habits, shown,
 * extra, labels}`: os hábitos com marcação no dia (`{id, color, label}`), os pontos visíveis, o
 * "+N" e as siglas juntas (para a dica e o leitor de tela).
 */
export function overviewByDay(habits, byHabit, max = MAX_DOTS) {
  const days = new Map();
  for (const habit of habits) {
    const marked = byHabit.get(habit.id);
    if (!marked) continue;
    const item = { id: habit.id, color: habit.color, label: habit.label };
    for (const [day, marks] of marked) {
      if (marks.length === 0) continue;
      const list = days.get(day);
      if (list) list.push(item);
      else days.set(day, [item]);
    }
  }
  const result = new Map();
  for (const [day, list] of days) {
    const { shown, extra } = splitDots(list, max);
    const labels = list.map((item) => item.label).join(', ');
    result.set(day, { habits: list, shown, extra, labels });
  }
  return result;
}

// Teclas que movem o foco na grade e quantos dias cada uma anda
const STEPS = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };

// Home e End: o primeiro e o último dia do mês de `value`
function monthEdge(value, key) {
  if (key === 'Home') return `${value.slice(0, 8)}01`;
  const { year, month } = parseDate(value);
  return `${value.slice(0, 8)}${pad(daysInMonth(year, month))}`;
}

function clampDay(value, first, last) {
  if (value < first) return first;
  if (value > last) return last;
  return value;
}

/**
 * Dia que recebe o foco na grade quando a tecla `key` é apertada em `value`, dentro de
 * `[first, last]`; null se a tecla não move. Setas andam 1 dia (esquerda/direita) ou 1 semana
 * (cima/baixo); Home e End vão ao primeiro e ao último dia do mês.
 */
export function moveDay(value, key, first, last) {
  let next;
  if (key in STEPS) next = addDays(value, STEPS[key]);
  else if (key === 'Home' || key === 'End') next = monthEdge(value, key);
  else return null;
  return clampDay(next, first, last);
}

/**
 * O mesmo dia `step` meses para frente (1) ou para trás (−1); no mês mais curto, o último dia
 * dele (31 de março − 1 mês = 28 ou 29 de fevereiro).
 */
export function shiftMonthDay(value, step) {
  const { year, month, day } = parseDate(value);
  const index = year * 12 + month - 1 + step;
  const nextYear = Math.floor(index / 12);
  const nextMonth = (index % 12) + 1;
  const nextDay = Math.min(day, daysInMonth(nextYear, nextMonth));
  return `${yearText(nextYear)}-${pad(nextMonth)}-${pad(nextDay)}`;
}

// Setas na visão em colunas: cima/baixo andam 1 dia, esquerda/direita 1 mês (uma coluna)
const COLUMN_STEPS = { ArrowUp: -1, ArrowDown: 1 };
const COLUMN_MONTHS = { ArrowLeft: -1, ArrowRight: 1 };

/**
 * Como moveDay, na visão em colunas (cada mês uma coluna, os dias de cima para baixo): cima e
 * baixo andam 1 dia (do último dia de um mês para o primeiro do próximo); esquerda e direita vão
 * para o mesmo dia na coluna vizinha (shiftMonthDay); Home e End como na grade. Também fica
 * dentro de `[first, last]`.
 */
export function moveColumnDay(value, key, first, last) {
  let next;
  if (key in COLUMN_STEPS) next = addDays(value, COLUMN_STEPS[key]);
  else if (key in COLUMN_MONTHS) next = shiftMonthDay(value, COLUMN_MONTHS[key]);
  else if (key === 'Home' || key === 'End') next = monthEdge(value, key);
  else return null;
  return clampDay(next, first, last);
}

const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

export function daysInMonth(year, month) {
  return month === 2 && isLeapYear(year) ? 29 : MONTH_DAYS[month - 1];
}
