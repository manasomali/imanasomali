// Formulário de configuração do hábito (criar e editar): o estado da tela, a validação igual à da
// API (app/habits/schemas.py e service.check_config) e o corpo do POST /habits ou do
// PATCH /habits/{id}. A API continua sendo a fonte da verdade: o que passar daqui e ela recusar
// volta como 422 com o `field`, mostrado no campo.
//
// Recursos opcionais (duração, pontuação, custo) têm campos que só aparecem com o recurso ligado.
// Campo escondido não é validado nem enviado: desligar um recurso guarda os valores na API, que
// voltam ao religar (ethos-plan.md, "mudar a configuração não apaga dados")

import { parseDuration } from './duration';
import { formatMoney, parseMoney } from './money';
import { isCustomColor, isValidColor } from './palette';

/** Tamanhos máximos dos textos (HABIT_*_MAX_LENGTH em app/models.py). */
export const TEXT_LIMITS = Object.freeze({
  name: 60,
  code: 4,
  description: 500,
  reward: 140,
  punishment: 140,
});

/** Limite padrão da pontuação (DEFAULT_SCORE_THRESHOLD em app/models.py). */
export const DEFAULT_SCORE_THRESHOLD = 70;

/**
 * Padrão de `MAX_MARKS_PER_DAY` (app/config.py). O valor é configurável no servidor e a API não o
 * expõe: um teto diferente do padrão volta como 422 em `goal_count`.
 */
export const MAX_MARKS_PER_DAY = 999;

/** Dias de cada período no teto de N (PERIOD_DAYS em app/habits/service.py). */
export const PERIOD_DAYS = Object.freeze({ week: 7, month: 28, year: 365 });

export const GOAL_TYPES = Object.freeze(['min', 'max', 'exact']);
export const PERIODS = Object.freeze(['week', 'month', 'year']);
export const COST_LEVELS = Object.freeze(['habit', 'mark']);

/** Cor de um hábito novo. */
export const DEFAULT_COLOR = 'teal';

// Recursos que se ligam por chave e os campos que só existem com ele ligado. `multi_mark` não
// esconde campos, mas também guarda dados (as marcações extras de um dia) ao voltar para toggle
export const FEATURES = Object.freeze({
  multi_mark: [],
  duration_enabled: ['duration_minutes'],
  notes_enabled: [],
  score_enabled: ['score_threshold', 'reward', 'punishment'],
  cost_enabled: ['cost_level', 'cost_cents', 'cost_limit_cents', 'cost_limit_period'],
});

// Campos sempre visíveis, na ordem da tela
const BASE_FIELDS = ['name', 'code', 'description', 'color', 'goal_type', 'goal_count', 'goal_period'];

/** Todos os campos do formulário, que são também os campos da API (o `field` do 422). */
export const FORM_FIELDS = Object.freeze([
  ...BASE_FIELDS,
  ...Object.entries(FEATURES).flatMap(([flag, fields]) => [flag, ...fields]),
]);

// Caracteres de controle (categoria Cc) e os que invertem a direção do texto (U+202A a U+202E e
// U+2066 a U+2069), recusados pela API (check_controls em app/habits/schemas.py)
const BIDI_CONTROLS = /[‪-‮⁦-⁩]/u;
const CONTROLS = /\p{Cc}/u;
const MULTILINE_CONTROLS = /[\n\t]/g;
const CODE_RE = /^[A-Za-z0-9]{1,4}$/;
const INTEGER_RE = /^\d{1,10}$/;

/** Tamanho de um texto como a API conta: sem os espaços das pontas, por caractere Unicode. */
export function textLength(value) {
  return [...value.trim()].length;
}

/** Se o texto tem caractere que a API recusa (com `multiline`, quebra de linha e tab passam). */
export function hasForbiddenControls(value, { multiline = false } = {}) {
  const text = multiline ? value.replace(MULTILINE_CONTROLS, '') : value;
  return CONTROLS.test(text) || BIDI_CONTROLS.test(text);
}

/** Menor N da meta: 0 só no tipo máximo (hábito de "não fazer"). */
export function minGoalCount(goalType) {
  return goalType === 'max' ? 0 : 1;
}

/** Maior N: dias do período no toggle; MAX_MARKS_PER_DAY x dias com várias marcações por dia. */
export function maxGoalCount(goalPeriod, multiMark) {
  const days = PERIOD_DAYS[goalPeriod] ?? PERIOD_DAYS.week;
  return multiMark ? days * MAX_MARKS_PER_DAY : days;
}

function moneyText(cents, locale) {
  return cents === null || cents === undefined ? '' : formatMoney(cents, locale);
}

function numberText(value) {
  return value === null || value === undefined ? '' : String(value);
}

/**
 * Estado inicial do formulário: textos como a tela mostra (números e dinheiro em texto, no idioma
 * `locale`). Sem `habit`, os padrões de um hábito novo: meta "pelo menos 1 vez por semana",
 * toggle e todos os recursos desligados. `custom_color` não vai para a API: é a última cor própria
 * escolhida ("#rrggbb" ou ''), que volta ao marcar "personalizada" depois de passar pela paleta.
 */
export function habitForm(habit, locale) {
  if (!habit) {
    return {
      name: '',
      code: '',
      description: '',
      color: DEFAULT_COLOR,
      custom_color: '',
      goal_type: 'min',
      goal_count: '1',
      goal_period: 'week',
      multi_mark: false,
      duration_enabled: false,
      duration_minutes: '',
      notes_enabled: false,
      score_enabled: false,
      score_threshold: String(DEFAULT_SCORE_THRESHOLD),
      reward: '',
      punishment: '',
      cost_enabled: false,
      cost_level: 'habit',
      cost_cents: '',
      cost_limit_cents: '',
      cost_limit_period: '',
    };
  }
  return {
    name: habit.name,
    code: habit.code ?? '',
    description: habit.description ?? '',
    color: isValidColor(habit.color) ? habit.color : DEFAULT_COLOR,
    custom_color: isCustomColor(habit.color) ? habit.color : '',
    goal_type: habit.goal_type,
    goal_count: String(habit.goal_count),
    goal_period: habit.goal_period,
    multi_mark: habit.multi_mark,
    duration_enabled: habit.duration_enabled,
    duration_minutes: numberText(habit.duration_minutes),
    notes_enabled: habit.notes_enabled,
    score_enabled: habit.score_enabled,
    score_threshold: String(habit.score_threshold),
    reward: habit.reward ?? '',
    punishment: habit.punishment ?? '',
    cost_enabled: habit.cost_enabled,
    cost_level: habit.cost_level,
    cost_cents: moneyText(habit.cost_cents, locale),
    cost_limit_cents: moneyText(habit.cost_limit_cents, locale),
    cost_limit_period: habit.cost_limit_period ?? '',
  };
}

/** Campos visíveis (validados e enviados) com os recursos ligados no formulário. */
export function visibleFields(form) {
  return FORM_FIELDS.filter((name) => {
    const flag = Object.keys(FEATURES).find((key) => FEATURES[key].includes(name));
    return flag === undefined || form[flag];
  });
}

/** Recursos ligados no hábito salvo e desligados no formulário (os dados deles ficam guardados). */
export function turnedOff(form, habit) {
  if (!habit) return [];
  return Object.keys(FEATURES).filter((flag) => habit[flag] && !form[flag]);
}

// Validação de um texto: erro ou o valor da API (texto opcional vazio vira null)
function text(value, name, { required = false, multiline = false } = {}) {
  const trimmed = value.trim();
  if (!trimmed) return required ? { error: { code: 'required' } } : { value: null };
  if (textLength(trimmed) > TEXT_LIMITS[name]) {
    return { error: { code: 'too_long', max: TEXT_LIMITS[name] } };
  }
  if (hasForbiddenControls(trimmed, { multiline })) return { error: { code: 'invalid_chars' } };
  return { value: trimmed };
}

function integer(value, min, max, code) {
  const trimmed = value.trim();
  const number = INTEGER_RE.test(trimmed) ? Number(trimmed) : null;
  if (number === null || number < min || number > max) return { error: { code, min, max } };
  return { value: number };
}

function money(value, locale, { required = false } = {}) {
  const trimmed = value.trim();
  if (!trimmed) return required ? { error: { code: 'required' } } : { value: null };
  const cents = parseMoney(trimmed, locale);
  return cents === null ? { error: { code: 'invalid_money' } } : { value: cents };
}

function choice(value, options) {
  return options.includes(value) ? { value } : { error: { code: 'required' } };
}

// Regras de cada campo visível: `{value}` (valor da API) ou `{error: {code, ...parâmetros}}`
function checkField(name, form, locale) {
  switch (name) {
    case 'name':
      return text(form.name, 'name', { required: true });
    case 'code': {
      const trimmed = form.code.trim();
      if (!trimmed) return { value: null };
      return CODE_RE.test(trimmed) ? { value: trimmed.toUpperCase() } : { error: { code: 'invalid_code' } };
    }
    case 'description':
      return text(form.description, 'description', { multiline: true });
    case 'reward':
    case 'punishment':
      return text(form[name], name);
    case 'color':
      // Um nome da paleta ou uma cor própria (#rrggbb)
      return isValidColor(form.color) ? { value: form.color } : { error: { code: 'required' } };
    case 'goal_type':
      return choice(form.goal_type, GOAL_TYPES);
    case 'goal_period':
      return choice(form.goal_period, PERIODS);
    case 'goal_count':
      return integer(
        form.goal_count,
        minGoalCount(form.goal_type),
        maxGoalCount(form.goal_period, form.multi_mark),
        'goal_range',
      );
    case 'duration_minutes': {
      const minutes = parseDuration(form.duration_minutes);
      return minutes === null ? { error: { code: 'duration_range' } } : { value: minutes };
    }
    case 'score_threshold':
      return integer(form.score_threshold, 1, 100, 'threshold_range');
    case 'cost_level':
      return choice(form.cost_level, COST_LEVELS);
    case 'cost_cents':
      // Nível hábito: todo mundo que marca gera o custo fixo, então ele é obrigatório
      return money(form.cost_cents, locale, { required: form.cost_level === 'habit' });
    case 'cost_limit_cents':
      // Limite e período vêm juntos: sem período ("sem limite"), o valor fica escondido e vai null
      if (form.cost_limit_period === '') return { value: null };
      return money(form.cost_limit_cents, locale, { required: true });
    case 'cost_limit_period':
      return form.cost_limit_period === '' ? { value: null } : choice(form.cost_limit_period, PERIODS);
    default:
      // Chaves dos recursos (booleanos)
      return { value: Boolean(form[name]) };
  }
}

/**
 * Corpo da API a partir do formulário e os erros por campo (`{campo: {code, ...}}`; códigos:
 * required, too_long, invalid_chars, invalid_code, goal_range, duration_range, threshold_range,
 * invalid_money). Sem `habit`, o corpo do POST /habits (campos escondidos ficam com o padrão da
 * API). Com `habit`, o do PATCH: só os campos visíveis que mudaram (nada mudou: objeto vazio).
 */
export function habitPayload(form, locale, habit = null) {
  const values = {};
  const errors = {};
  for (const name of visibleFields(form)) {
    const result = checkField(name, form, locale);
    if (result.error) errors[name] = result.error;
    else if (!habit || habit[name] !== result.value) values[name] = result.value;
  }
  return { values, errors };
}

/**
 * Resumo da meta para a prévia em texto, ou null enquanto N é inválido: `{type, count, period,
 * never}` (`never`: "no máximo 0", que a tela mostra como "nenhuma vez") e, com a duração ligada
 * e válida, `totalMinutes` (a soma de minutos do período que a meta compara).
 */
export function goalSummary(form) {
  const count = checkField('goal_count', form);
  if (count.error || !GOAL_TYPES.includes(form.goal_type) || !PERIODS.includes(form.goal_period)) {
    return null;
  }
  const summary = {
    type: form.goal_type,
    count: count.value,
    period: form.goal_period,
    never: form.goal_type === 'max' && count.value === 0,
    totalMinutes: null,
  };
  if (form.duration_enabled && !summary.never) {
    const minutes = parseDuration(form.duration_minutes);
    if (minutes !== null) summary.totalMinutes = minutes * count.value;
  }
  return summary;
}
