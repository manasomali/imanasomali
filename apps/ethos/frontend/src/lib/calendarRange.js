// Faixa de meses do calendário: só um mês, 3 meses (os dois anteriores e o da âncora) ou o ano
// inteiro. A faixa é um conceito separado do desenho: calendarRange dá os meses e os limites, e
// quem desenha (components/Calendar) só percorre `range.months`. O estado vem da URL
// (`?range=month|3months|year`, `?month=AAAA-MM` nas faixas de mês, `?year=AAAA` na do ano e
// `?day=AAAA-MM-DD`) e do tipo lembrado no navegador (RANGE_STORAGE_KEY).

import { MIN_YEAR, calendarMonth, parseDay, parseYear, yearMonths, yearOf } from './calendar';
import { parseDate } from './time';

export const RANGE_KINDS = Object.freeze(['month', '3months', 'year']);

// Quem nunca escolheu vê o ano inteiro: é o calendário anual do plano e o que a tela sempre mostrou
export const DEFAULT_RANGE_KIND = 'year';

// Chave do localStorage com o último tipo escolhido, o mesmo nas duas abas
export const RANGE_STORAGE_KEY = 'ethos:calendar-range';

// Quantos meses cada tipo anda no anterior/próximo
const STEP_MONTHS = Object.freeze({ month: 1, '3months': 3, year: 12 });

/** Lê um tipo de faixa (da URL ou do navegador): um de RANGE_KINDS, ou null. */
export function parseRangeKind(value) {
  return RANGE_KINDS.includes(value) ? value : null;
}

// Meses como um número só (ano × 12 + mês − 1), para somar e comparar
function toIndex({ year, month }) {
  return year * 12 + month - 1;
}

function fromIndex(index) {
  return { year: Math.floor(index / 12), month: (index % 12) + 1 };
}

/** Mês `{year, month}` de um dia "AAAA-MM-DD". */
export function monthOf(value) {
  const { year, month } = parseDate(value);
  return { year, month };
}

/** "AAAA-MM" de um mês `{year, month}` (o `?month=` da URL). */
export function monthParam({ year, month }) {
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}`;
}

/** Lê um mês "AAAA-MM" da URL: `{year, month}` entre MIN_YEAR e `max` (um mês), ou null. */
export function parseMonthParam(value, max) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}$/.test(value)) return null;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5));
  if (month < 1 || month > 12 || year < MIN_YEAR) return null;
  const result = { year, month };
  return toIndex(result) > toIndex(max) ? null : result;
}

/**
 * A faixa do tipo `kind` em volta do mês `anchor` (`{year, month}`): `{kind, anchor, first, last,
 * months, years}`. `months` são os meses de calendarMonth em ordem, `first` e `last` o primeiro e o
 * último dia ("AAAA-MM-DD") e `years` os anos que ela toca, em ordem (2 quando a janela de 3 meses
 * cruza o ano). Mês: só a âncora; 3 meses: os dois anteriores e a âncora; ano: o ano da âncora.
 */
export function calendarRange(kind, anchor) {
  let months;
  if (kind === 'year') {
    months = yearMonths(anchor.year);
  } else {
    const last = toIndex(anchor);
    const before = kind === '3months' ? 2 : 0;
    months = [];
    for (let index = last - before; index <= last; index += 1) {
      const { year, month } = fromIndex(index);
      months.push(calendarMonth(year, month));
    }
  }
  const years = [...new Set(months.map((month) => month.year))];
  return {
    kind,
    anchor,
    first: months[0].days[0],
    last: months.at(-1).days.at(-1),
    months,
    years,
  };
}

/**
 * A âncora dentro dos limites: a faixa não começa antes de janeiro de MIN_YEAR (a janela de 3 meses
 * ancora no mínimo em março) e a âncora não passa do mês de hoje (`today`, "AAAA-MM-DD"). A janela
 * de 3 meses termina na âncora, então nunca mostra mês depois do de hoje.
 */
export function clampAnchor(kind, anchor, today) {
  const min = MIN_YEAR * 12 + (kind === '3months' ? 2 : 0);
  const max = toIndex(monthOf(today));
  return fromIndex(Math.min(Math.max(toIndex(anchor), min), max));
}

// Âncora da faixa `kind` que começa no mês `index` (a de 3 meses ancora no último mês)
function anchorStartingAt(kind, index) {
  return fromIndex(kind === '3months' ? index + 2 : index);
}

/**
 * Âncora `step` faixas para frente (1) ou para trás (−1), sem os limites: um mês, 3 meses ou um
 * ano. Use clampAnchor para navegar; sem ela, serve para dar nome ao botão desabilitado.
 */
export function shiftAnchor(kind, anchor, step) {
  return fromIndex(toIndex(anchor) + step * STEP_MONTHS[kind]);
}

/**
 * Âncoras do anterior e do próximo de `range`, já nos limites: null quando a faixa não muda (no
 * começo de MIN_YEAR ou com a faixa já no mês de hoje).
 */
export function rangeNeighbors(range, today) {
  const neighbor = (step) => {
    const anchor = clampAnchor(range.kind, shiftAnchor(range.kind, range.anchor, step), today);
    return calendarRange(range.kind, anchor).first === range.first ? null : anchor;
  };
  return { previous: neighbor(-1), next: neighbor(1) };
}

/**
 * Âncora ao trocar a faixa `range` pelo tipo `kind`: com um dia escolhido (`day`), o mês dele, para
 * o dia continuar visível (no fim da janela de 3 meses); sem dia, a nova faixa começa no primeiro
 * mês da atual. Já nos limites.
 */
export function switchAnchor(range, kind, day, today) {
  const anchor = day ? monthOf(day) : anchorStartingAt(kind, toIndex(range.months[0]));
  return clampAnchor(kind, anchor, today);
}

/**
 * Estado do calendário a partir dos parâmetros da URL (`{range, month, year, day}`, textos ou
 * null), do tipo lembrado no navegador (`storedKind`) e de hoje no fuso da conta (`today`).
 * Valor inválido, dia no futuro, mês ou ano depois do atual são ignorados. Devolve `{range, day}`:
 * - o tipo: o da URL, senão o lembrado, senão DEFAULT_RANGE_KIND;
 * - a posição: na faixa do ano, o `year` (senão o ano do `month`); nas de mês, o `month` (senão o
 *   começo do `year`); sem elas, o mês do dia, senão o de hoje;
 * - `day`: o da URL se estiver na faixa; senão hoje, se estiver na faixa; senão null.
 */
export function resolveCalendar(params, storedKind, today) {
  const kind = parseRangeKind(params.range) ?? parseRangeKind(storedKind) ?? DEFAULT_RANGE_KIND;
  const current = monthOf(today);
  const parsedDay = parseDay(params.day);
  const validDay =
    parsedDay !== null && parsedDay <= today && yearOf(parsedDay) >= MIN_YEAR ? parsedDay : null;
  const month = parseMonthParam(params.month, current);
  const year = parseYear(params.year, { max: current.year });

  // Ano sem mês: o mês do dia, se for desse ano; o de hoje no ano atual; senão, o começo do ano
  const fromYear = () => {
    if (validDay !== null && yearOf(validDay) === year) return monthOf(validDay);
    if (year === current.year) return current;
    return anchorStartingAt(kind, year * 12);
  };
  let anchor;
  if (kind === 'year' && year !== null) anchor = fromYear();
  else if (month !== null) anchor = month;
  else if (year !== null) anchor = fromYear();
  else if (validDay !== null) anchor = monthOf(validDay);
  else anchor = current;

  const range = calendarRange(kind, clampAnchor(kind, anchor, today));
  const inRange = (value) => value !== null && value >= range.first && value <= range.last;
  let day = null;
  if (inRange(validDay)) day = validDay;
  else if (inRange(today)) day = today;
  return { range, day };
}

/**
 * Escreve a faixa (`kind` e a posição de `anchor`) em `params` (URLSearchParams, mudado no lugar):
 * `range`, mais `year` na faixa do ano ou `month` nas de mês (o outro sai).
 */
export function writeRangeParams(params, kind, anchor) {
  params.set('range', kind);
  if (kind === 'year') {
    params.set('year', String(anchor.year));
    params.delete('month');
  } else {
    params.set('month', monthParam(anchor));
    params.delete('year');
  }
  return params;
}
