// Configuração de alerta de um hábito (GET/PUT /habits/{id}/alerts, ETH-26), sem React: o estado
// do formulário, a validação, o corpo do PUT e as contas dos textos de quando o alerta dispara.
// As regras de disparo são do backend (app/alerts/service.py e app/score.py); aqui só se explica

import { isoWeekday } from './calendar';
import { addDays, localDate, parseDate, today } from './time';

/** Hora padrão de quem ainda não salvou (DEFAULT_HOUR em app/alerts/service.py). */
export const DEFAULT_HOUR = 20;

/** Horas cheias que a API aceita (0 a 23, no fuso do usuário). */
export const ALERT_HOURS = Object.freeze(Array.from({ length: 24 }, (_, hour) => hour));

export const FREQUENCIES = Object.freeze(['daily', 'weekly']);

/** Dias da semana como a API: 0 = segunda ... 6 = domingo (`date.weekday()` do Python). */
export const WEEKDAYS = Object.freeze([0, 1, 2, 3, 4, 5, 6]);

/** Aviso de custo em 80% do limite (COST_WARNING_PERCENT em app/score.py). */
export const COST_WARNING_PERCENT = 80;

const WEEK_SECONDS = 7 * 24 * 60 * 60;

function isWholeIn(value, min, max) {
  return Number.isInteger(value) && value >= min && value <= max;
}

/** A chave de custo só existe quando o hábito tem custo com limite (e período do limite). */
export function hasCostAlert(habit) {
  return Boolean(habit.cost_enabled) && habit.cost_limit_cents !== null && habit.cost_limit_period !== null;
}

/**
 * Estado do formulário a partir do AlertOut da API: hora e dia como texto (o valor dos
 * `<select>`), dia vazio quando não há.
 */
export function alertForm(alert) {
  const hour = isWholeIn(alert.hour, 0, 23) ? alert.hour : DEFAULT_HOUR;
  const weekday = isWholeIn(alert.weekday, 0, 6) ? String(alert.weekday) : '';
  return {
    goal_enabled: alert.goal_enabled === true,
    cost_enabled: alert.cost_enabled === true,
    hour: String(hour),
    frequency: FREQUENCIES.includes(alert.frequency) ? alert.frequency : 'daily',
    weekday,
  };
}

function parseChoice(value, min, max) {
  if (typeof value !== 'string' || !/^\d{1,2}$/.test(value)) return null;
  const number = Number(value);
  return number >= min && number <= max ? number : null;
}

/**
 * Erros do formulário, como a API valida: `{campo: 'required' | 'invalid'}` (vazio quando está
 * tudo certo). O semanal exige o dia da semana.
 */
export function alertErrors(form) {
  const errors = {};
  if (parseChoice(form.hour, 0, 23) === null) errors.hour = 'invalid';
  if (!FREQUENCIES.includes(form.frequency)) errors.frequency = 'invalid';
  if (form.frequency === 'weekly') {
    if (form.weekday === '') errors.weekday = 'required';
    else if (parseChoice(form.weekday, 0, 6) === null) errors.weekday = 'invalid';
  }
  return errors;
}

/**
 * Corpo do PUT (a configuração inteira). No diário, `weekday` vai `null` (a API recusa o dia).
 * Lança RangeError se o formulário tem erro: valide antes com `alertErrors`.
 */
export function alertPayload(form) {
  if (Object.keys(alertErrors(form)).length > 0) throw new RangeError('formulário de alerta inválido');
  const weekly = form.frequency === 'weekly';
  return {
    goal_enabled: Boolean(form.goal_enabled),
    cost_enabled: Boolean(form.cost_enabled),
    hour: Number(form.hour),
    frequency: form.frequency,
    weekday: weekly ? Number(form.weekday) : null,
  };
}

const hourFormatters = new Map();

/** Horário do dia como o idioma escreve ("20:00" / "8:00 PM"; com `minute`, "08:15"). */
export function formatHour(hour, locale, minute = 0) {
  if (!isWholeIn(hour, 0, 23)) throw new RangeError(`hora inválida: ${hour}`);
  if (!isWholeIn(minute, 0, 59)) throw new RangeError(`minuto inválido: ${minute}`);
  let format = hourFormatters.get(locale);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, { timeZone: 'UTC', timeStyle: 'short' });
    hourFormatters.set(locale, format);
  }
  return format.format(new Date(Date.UTC(2000, 0, 1, hour, minute)));
}

/**
 * Se o ritmo pode ficar atrasado dentro do período. O esperado é
 * `floor(target × segundos passados / segundos do período)`: com `target` 1 ele só chega a 1 no
 * fim do período, quando já é o período seguinte, então "atrasado" nunca acontece.
 */
export function canFallBehind(target) {
  return Number.isSafeInteger(target) && target >= 2;
}

/**
 * Num período semanal sem nenhuma marcação, quando o hábito passa a ficar atrasado no ritmo: o
 * esperado chega a 1 quando os segundos passados chegam a `ceil(semana / target)`. `target` é N
 * (ou a soma de minutos, com a duração ligada). Devolve `{weekday, hour, minute}` (weekday 0 =
 * segunda, como a API), numa semana sem mudança de horário, ou null quando o ritmo não atrasa
 * (`canFallBehind`).
 */
export function weeklyPaceStart(target) {
  if (!canFallBehind(target)) return null;
  const seconds = Math.ceil(WEEK_SECONDS / target);
  const minutes = Math.floor(seconds / 60);
  return {
    weekday: Math.floor(minutes / (24 * 60)),
    hour: Math.floor(minutes / 60) % 24,
    minute: minutes % 60,
  };
}

/** Primeiro dia ("AAAA-MM-DD") do período (week, month, year) que contém `day`; semana na segunda. */
export function periodFirstDay(day, period) {
  const { year, month } = parseDate(day);
  if (period === 'week') return addDays(day, 1 - isoWeekday(day));
  if (period === 'month') return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-01`;
  if (period === 'year') return `${String(year).padStart(4, '0')}-01-01`;
  throw new RangeError(`período inválido: ${period}`);
}

function nextPeriodFirstDay(first, period) {
  const { year, month } = parseDate(first);
  if (period === 'week') return addDays(first, 7);
  if (period === 'month') {
    const next = month === 12 ? { year: year + 1, month: 1 } : { year, month: month + 1 };
    return `${String(next.year).padStart(4, '0')}-${String(next.month).padStart(2, '0')}-01`;
  }
  return `${String(year + 1).padStart(4, '0')}-01-01`;
}

/**
 * Se agora ainda é o período (week, month, year) em que o hábito foi criado, no fuso dado, o
 * primeiro dia do período seguinte: antes dele o alerta não dispara (o backend não avalia o período
 * da criação). Senão, null.
 */
export function firstAlertDay(createdAt, period, timeZone, now = new Date()) {
  const created = periodFirstDay(localDate(createdAt, timeZone), period);
  const current = periodFirstDay(today(timeZone, now), period);
  return current <= created ? nextPeriodFirstDay(created, period) : null;
}
