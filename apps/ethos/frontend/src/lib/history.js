// Histórico (GET /history, app/history/ no backend): os filtros na URL, a query da API, as páginas
// juntas sem repetir evento, as pessoas do filtro de autor e o texto de cada evento, montado só com
// o `details` público que a API manda (PUBLIC_DETAILS em app/history/service.py)

import { parseHabitId } from '../paths';
import { parseUserId } from './admin';
import { parseDay } from './calendar';
import { formatDateTime } from './datetime';
import { formatMoney } from './money';
import { HABIT_COLORS } from './palette';

// Os eventos do histórico (HistoryEvent no backend; src/lib/history.test.js confere), em grupos
export const EVENT_GROUPS = Object.freeze({
  habit: Object.freeze([
    'habit_created',
    'habit_updated',
    'habit_paused',
    'habit_resumed',
    'habit_archived',
    'habit_unarchived',
  ]),
  marks: Object.freeze(['mark_created', 'mark_updated', 'mark_deleted']),
  sharing: Object.freeze([
    'invite_created',
    'invite_canceled',
    'invite_accepted',
    'invite_declined',
    'member_left',
    'member_removed',
    'member_role_changed',
  ]),
});

export const HISTORY_EVENTS = Object.freeze(Object.values(EVENT_GROUPS).flat());

// Datas aceitas no `from`/`to` (MIN_DAY e MAX_DAY em app/progress/schemas.py)
export const MIN_HISTORY_DAY = '1900-01-01';
export const MAX_HISTORY_DAY = '2999-12-31';

// Valor do seletor de eventos para um grupo (`group:marks`) e para uma combinação que veio pela URL
// e não é nem um evento nem um grupo
const GROUP_PREFIX = 'group:';
export const CUSTOM_SELECTION = 'custom';

export const EMPTY_HISTORY_FILTERS = Object.freeze({
  habitId: null,
  userId: null,
  events: Object.freeze([]),
  from: '',
  to: '',
});

function parseHistoryDay(value) {
  const day = parseDay(value);
  return day !== null && day >= MIN_HISTORY_DAY && day <= MAX_HISTORY_DAY ? day : '';
}

/** Só os eventos conhecidos, sem repetição, na ordem de HISTORY_EVENTS. */
function knownEvents(events) {
  return HISTORY_EVENTS.filter((event) => events.includes(event));
}

/**
 * Filtros a partir da query da URL (URLSearchParams): `habit_id`, `user_id`, `event` (repetido),
 * `from` e `to`, com os mesmos nomes da API. Valor inválido fica de fora, em vez de virar um 422.
 */
export function parseHistoryFilters(params) {
  return {
    habitId: parseHabitId(params.get('habit_id')),
    userId: parseUserId(params.get('user_id')),
    events: knownEvents(params.getAll('event')),
    from: parseHistoryDay(params.get('from')),
    to: parseHistoryDay(params.get('to')),
  };
}

/** `to` antes de `from` (a API responderia 422 em `to`). */
export function isInvertedRange(filters) {
  return Boolean(filters.from && filters.to && filters.to < filters.from);
}

/** Query da URL para os filtros (o inverso de parseHistoryFilters); filtro vazio fica de fora. */
export function historySearch(filters) {
  const params = new URLSearchParams();
  if (filters.habitId !== null) params.set('habit_id', String(filters.habitId));
  if (filters.userId !== null) params.set('user_id', String(filters.userId));
  for (const event of knownEvents(filters.events)) params.append('event', event);
  if (filters.from) params.set('from', filters.from);
  if (filters.to) params.set('to', filters.to);
  return params;
}

/** Query do GET /history (sem o cursor), para o apiFetch: lista repete a chave `event`. */
export function historyQuery(filters) {
  const query = {};
  if (filters.habitId !== null) query.habit_id = filters.habitId;
  if (filters.userId !== null) query.user_id = filters.userId;
  const events = knownEvents(filters.events);
  if (events.length > 0) query.event = events;
  if (filters.from) query.from = filters.from;
  if (filters.to) query.to = filters.to;
  return query;
}

function sameEvents(a, b) {
  return a.length === b.length && a.every((event) => b.includes(event));
}

/**
 * Valor do seletor de eventos: '' (todos), `group:<nome>`, o nome de um evento, ou CUSTOM_SELECTION
 * para outra combinação (só pela URL).
 */
export function eventSelection(events) {
  if (events.length === 0) return '';
  for (const [name, group] of Object.entries(EVENT_GROUPS)) {
    if (sameEvents(group, events)) return `${GROUP_PREFIX}${name}`;
  }
  if (events.length === 1) return events[0];
  return CUSTOM_SELECTION;
}

/** Eventos de um valor do seletor; CUSTOM_SELECTION mantém `current`. */
export function selectionEvents(value, current = []) {
  if (value === CUSTOM_SELECTION) return knownEvents(current);
  if (value.startsWith(GROUP_PREFIX)) {
    return [...(EVENT_GROUPS[value.slice(GROUP_PREFIX.length)] ?? [])];
  }
  return HISTORY_EVENTS.includes(value) ? [value] : [];
}

/** Valor do seletor para um grupo de EVENT_GROUPS. */
export function groupSelection(name) {
  return `${GROUP_PREFIX}${name}`;
}

/**
 * Eventos das páginas na ordem da API, cada id uma vez só: uma página que se repete (busca de novo,
 * resposta atrasada) não duplica a lista.
 */
export function pageEvents(pages) {
  const seen = new Set();
  const events = [];
  for (const page of pages ?? []) {
    for (const event of page.events) {
      if (!seen.has(event.id)) {
        seen.add(event.id);
        events.push(event);
      }
    }
  }
  return events;
}

/**
 * Pessoas do filtro de autor ({id, email}): `me` primeiro e as outras por email, cada id uma vez.
 * `lists`: listas de {id, email} (membros do hábito, autores já carregados); itens sem id são
 * ignorados. `selectedId`, se ainda não estiver na lista, entra no fim com `email: null` (filtro
 * que veio pela URL, de alguém que a tela ainda não conhece).
 */
export function authorOptions(me, lists = [], selectedId = null) {
  const people = new Map();
  for (const person of [me, ...lists.flat()]) {
    if (!person || !Number.isSafeInteger(person.id)) continue;
    const email = typeof person.email === 'string' ? person.email : null;
    if (!people.has(person.id) || people.get(person.id) === null) people.set(person.id, email);
  }
  const others = [...people]
    .filter(([id, email]) => id !== me?.id && email !== null)
    .sort(([, a], [, b]) => a.localeCompare(b));
  const options = [];
  if (me && people.has(me.id)) options.push({ id: me.id, email: people.get(me.id) });
  options.push(...others.map(([id, email]) => ({ id, email })));
  if (selectedId !== null && !options.some((person) => person.id === selectedId)) {
    options.push({ id: selectedId, email: null });
  }
  return options;
}

// Como mostrar o valor de cada campo de `changes`. `valueless`: a API manda só o nome do campo
// (descrição e observação, textos do usuário que não vão para a auditoria)
const FIELD_KINDS = Object.freeze({
  name: 'text',
  code: 'text',
  description: 'valueless',
  color: 'color',
  goal_type: 'goal_type',
  goal_count: 'number',
  goal_period: 'period',
  multi_mark: 'flag',
  duration_enabled: 'flag',
  duration_minutes: 'minutes',
  notes_enabled: 'flag',
  score_enabled: 'flag',
  score_threshold: 'number',
  reward: 'text',
  punishment: 'text',
  cost_enabled: 'flag',
  cost_level: 'cost_level',
  cost_cents: 'money',
  cost_limit_cents: 'money',
  cost_limit_period: 'period',
  note: 'valueless',
  role: 'role',
});

/** Campos de `changes` que a tela sabe mostrar (os outros saem com o nome cru). */
export const CHANGE_FIELDS = Object.freeze(Object.keys(FIELD_KINDS));

// Valores conhecidos dos campos de lista fechada (enums de app/models.py e HabitRole)
const ENUM_VALUES = Object.freeze({
  color: HABIT_COLORS,
  goal_type: Object.freeze(['min', 'max', 'exact']),
  period: Object.freeze(['week', 'month', 'year']),
  cost_level: Object.freeze(['habit', 'mark']),
  role: Object.freeze(['owner', 'editor', 'viewer']),
});

function formatValue(kind, value, { t, language }) {
  if (value === null || value === undefined || value === '') return t('history.values.empty');
  if (kind === 'flag' && typeof value === 'boolean') {
    return t(value ? 'history.values.on' : 'history.values.off');
  }
  if (kind === 'money' && Number.isSafeInteger(value)) return formatMoney(value, language);
  if (kind === 'minutes' && Number.isSafeInteger(value)) {
    return t('history.values.minutes', { count: value });
  }
  if (kind === 'number' && typeof value === 'number') {
    return new Intl.NumberFormat(language).format(value);
  }
  if (ENUM_VALUES[kind]?.includes(value)) return t(`history.values.${kind}.${value}`);
  return String(value);
}

/** Texto de um item de `changes` ({field, old, new}): "Meta: 3 → 4" ou "Descrição alterada". */
export function describeChange(change, context) {
  const { t } = context;
  const kind = FIELD_KINDS[change.field];
  // Campo que a tela não conhece (o backend passou a gravar outro): o nome cru
  const field = kind ? t(`history.fields.${change.field}`) : change.field;
  if (kind === 'valueless' || !('old' in change || 'new' in change)) {
    return t('history.change_valueless', { field });
  }
  return t('history.change', {
    field,
    old: formatValue(kind, change.old, context),
    new: formatValue(kind, change.new, context),
  });
}

/** Nome de alguém pelo id (`people`: Map id → email), para os eventos que citam outra pessoa. */
function personName(id, { t, people }) {
  if (!Number.isSafeInteger(id)) return t('history.someone');
  return people?.get(id) ?? t('history.person', { id });
}

function roleName(role, context) {
  return formatValue('role', role, context);
}

function markLines(entry, context) {
  const { t } = context;
  const details = entry.details;
  const lines = [];
  // A marcação é de outra pessoa (ex.: o dono apagou a marcação de um convidado)
  if (Number.isSafeInteger(details.author_id) && details.author_id !== entry.author?.id) {
    lines.push(t('history.details.mark_author', { person: personName(details.author_id, context) }));
  }
  if (Number.isSafeInteger(details.duration_minutes)) {
    lines.push(t('history.details.duration', { value: formatValue('minutes', details.duration_minutes, context) }));
  }
  if (Number.isSafeInteger(details.cost_cents)) {
    lines.push(t('history.details.cost', { value: formatValue('money', details.cost_cents, context) }));
  }
  if (details.has_note === true) lines.push(t('history.details.has_note'));
  return lines;
}

function changeLines(details, context) {
  if (!Array.isArray(details.changes)) return [];
  return details.changes
    .filter((change) => change !== null && typeof change === 'object' && typeof change.field === 'string')
    .map((change) => describeChange(change, context));
}

/**
 * Texto de um evento do histórico: `{text, lines}`, a frase do evento e as linhas de detalhe (o que
 * mudou, duração, custo...). `context`: {t, language, timeZone, people}, com `people` um Map id →
 * email para citar o membro pelo email (senão "pessoa nº 7"). Quem fez (`author`) e quando ficam
 * com a tela. Evento desconhecido (o backend passou a mandar outro) vira um texto genérico.
 */
export function describeEvent(entry, context) {
  const { t, language, timeZone } = context;
  const event = entry.event;
  const details = entry.details !== null && typeof entry.details === 'object' ? entry.details : {};
  if (!HISTORY_EVENTS.includes(event)) {
    return { text: t('history.events.unknown', { event: String(event) }), lines: [] };
  }
  const key = `history.events.${event}`;
  switch (event) {
    case 'mark_created':
    case 'mark_deleted': {
      const at = Date.parse(details.marked_at);
      const lines = markLines({ ...entry, details }, context);
      if (Number.isNaN(at)) return { text: t(`${key}_undated`), lines };
      return { text: t(key, { date: formatDateTime(at, timeZone, language) }), lines };
    }
    case 'habit_updated':
    case 'mark_updated':
      return { text: t(key), lines: changeLines(details, context) };
    case 'member_role_changed':
      return {
        text: t(key, { person: personName(details.member_id, context) }),
        lines: changeLines(details, context),
      };
    case 'member_removed':
      return {
        text: t(key, { person: personName(details.member_id, context), role: roleName(details.role, context) }),
        lines: [],
      };
    case 'invite_created':
    case 'invite_canceled':
    case 'invite_accepted':
    case 'invite_declined':
    case 'member_left':
      return { text: t(key, { role: roleName(details.role, context) }), lines: [] };
    default:
      return { text: t(key), lines: [] };
  }
}
