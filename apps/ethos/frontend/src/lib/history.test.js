import { describe, expect, it } from 'vitest';
import { readFrontendFile } from '../test/files';
import { createTestI18n } from '../test/i18n';
import {
  CHANGE_FIELDS,
  CUSTOM_SELECTION,
  EMPTY_HISTORY_FILTERS,
  EVENT_GROUPS,
  HISTORY_EVENTS,
  authorOptions,
  describeChange,
  describeEvent,
  eventSelection,
  groupSelection,
  historyQuery,
  historySearch,
  isInvertedRange,
  pageEvents,
  parseHistoryFilters,
  selectionEvents,
} from './history';

const SAO_PAULO = 'America/Sao_Paulo';
const ANA = { id: 1, email: 'ana@example.com' };
const BIA = { id: 2, email: 'bia@example.com' };
const CAIO = { id: 3, email: 'caio@example.com' };

/** Nomes de uma tupla de strings do Python (`NOME = (\n "a",\n "b",\n)`). */
function pythonTuple(source, name) {
  const block = new RegExp(`^${name} = \\(([\\s\\S]*?)\\n\\)`, 'm').exec(source);
  if (!block) throw new Error(`${name} não encontrado`);
  return [...block[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
}

function context(language = 'en', overrides = {}) {
  const i18n = createTestI18n();
  return {
    t: i18n.getFixedT(language),
    language,
    timeZone: SAO_PAULO,
    people: new Map([
      [ANA.id, ANA.email],
      [BIA.id, BIA.email],
    ]),
    ...overrides,
  };
}

function entry(event, details = {}, overrides = {}) {
  return {
    id: 10,
    event,
    created_at: '2026-03-02T15:00:00Z',
    habit: { id: 1, label: 'RUN' },
    author: ANA,
    details,
    ...overrides,
  };
}

describe('events of the backend', () => {
  // Checagem entre áreas: a lista fechada de HistoryEvent em app/history/service.py
  it('are the same as HistoryEvent', () => {
    const source = readFrontendFile('../backend/app/history/service.py');
    const block = /class HistoryEvent\(StrEnum\):([\s\S]*?)\n(?=\S)/.exec(source);
    const backend = [...block[1].matchAll(/= AuditEvent\.([A-Z_]+)\.value/g)].map((match) =>
      match[1].toLowerCase(),
    );

    expect(backend.length).toBeGreaterThan(10);
    expect([...HISTORY_EVENTS].sort()).toEqual([...backend].sort());
    expect(new Set(HISTORY_EVENTS).size).toBe(HISTORY_EVENTS.length);
  });

  it('have a name and a text in pt and en', () => {
    const i18n = createTestI18n();
    for (const language of ['pt', 'en']) {
      for (const event of HISTORY_EVENTS) {
        expect(i18n.exists(`history.event_names.${event}`, { lng: language }), `${language}: ${event}`).toBe(true);
        expect(i18n.exists(`history.events.${event}`, { lng: language }), `${language}: ${event}`).toBe(true);
      }
      for (const group of Object.keys(EVENT_GROUPS)) {
        expect(i18n.exists(`history.groups.${group}`, { lng: language })).toBe(true);
      }
    }
  });

  // Todo campo que o habit_updated e o mark_updated gravam em `changes` tem rótulo
  it('label every field the backend records in changes', () => {
    const habitFields = pythonTuple(readFrontendFile('../backend/app/habits/schemas.py'), 'CONFIG_FIELDS');
    // Os campos que o update_mark compara (`for name in ("note", ...):`)
    const marks = /def update_mark\([\s\S]*?for name in \(([^)]*)\):/.exec(
      readFrontendFile('../backend/app/marks/service.py'),
    );
    const markFields = [...marks[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
    const i18n = createTestI18n();

    expect(habitFields).toContain('cost_limit_period');
    expect(markFields).toEqual(['note', 'duration_minutes', 'cost_cents']);
    for (const field of [...habitFields, ...markFields, 'role']) {
      expect(CHANGE_FIELDS, field).toContain(field);
      expect(i18n.exists(`history.fields.${field}`, { lng: 'pt' }), field).toBe(true);
      expect(i18n.exists(`history.fields.${field}`, { lng: 'en' }), field).toBe(true);
    }
  });
});

describe('filters in the URL', () => {
  it('reads every filter', () => {
    const params = new URLSearchParams(
      'habit_id=3&user_id=2&event=mark_deleted&event=mark_created&from=2026-03-01&to=2026-03-31',
    );

    expect(parseHistoryFilters(params)).toEqual({
      habitId: 3,
      userId: 2,
      events: ['mark_created', 'mark_deleted'],
      from: '2026-03-01',
      to: '2026-03-31',
    });
  });

  it('drops invalid values instead of sending them to the API', () => {
    const params = new URLSearchParams(
      'habit_id=0&user_id=abc&event=login&event=mark_created&event=mark_created&from=2026-02-30&to=3000-01-01',
    );

    expect(parseHistoryFilters(params)).toEqual({ ...EMPTY_HISTORY_FILTERS, events: ['mark_created'] });
    expect(parseHistoryFilters(new URLSearchParams('from=1899-12-31&to=2999-12-31'))).toEqual({
      ...EMPTY_HISTORY_FILTERS,
      to: '2999-12-31',
    });
    expect(parseHistoryFilters(new URLSearchParams())).toEqual(EMPTY_HISTORY_FILTERS);
  });

  it('writes the filters back, leaving the empty ones out', () => {
    const filters = {
      habitId: 3,
      userId: 2,
      events: ['mark_deleted', 'login', 'mark_created'],
      from: '2026-03-01',
      to: '',
    };

    expect(historySearch(filters).toString()).toBe(
      'habit_id=3&user_id=2&event=mark_created&event=mark_deleted&from=2026-03-01',
    );
    expect(historySearch(EMPTY_HISTORY_FILTERS).toString()).toBe('');
    expect(parseHistoryFilters(historySearch(filters))).toEqual({
      ...filters,
      events: ['mark_created', 'mark_deleted'],
    });
  });

  it('builds the API query, with the event repeated', () => {
    expect(historyQuery(EMPTY_HISTORY_FILTERS)).toEqual({});
    expect(
      historyQuery({ habitId: 3, userId: 2, events: ['mark_created'], from: '2026-03-01', to: '2026-03-31' }),
    ).toEqual({ habit_id: 3, user_id: 2, event: ['mark_created'], from: '2026-03-01', to: '2026-03-31' });
  });

  it('finds an inverted period', () => {
    expect(isInvertedRange({ from: '2026-03-02', to: '2026-03-01' })).toBe(true);
    expect(isInvertedRange({ from: '2026-03-01', to: '2026-03-01' })).toBe(false);
    expect(isInvertedRange({ from: '2026-03-02', to: '' })).toBe(false);
    expect(isInvertedRange({ from: '', to: '2026-03-01' })).toBe(false);
  });
});

describe('event selector', () => {
  it('maps events to the selector value', () => {
    expect(eventSelection([])).toBe('');
    expect(eventSelection(['mark_deleted', 'mark_created', 'mark_updated'])).toBe(groupSelection('marks'));
    expect(eventSelection(['habit_paused'])).toBe('habit_paused');
    expect(eventSelection(['habit_paused', 'mark_created'])).toBe(CUSTOM_SELECTION);
  });

  it('maps the selector value back to events', () => {
    expect(selectionEvents('')).toEqual([]);
    expect(selectionEvents(groupSelection('sharing'))).toEqual(EVENT_GROUPS.sharing);
    expect(selectionEvents(groupSelection('nothing'))).toEqual([]);
    expect(selectionEvents('mark_updated')).toEqual(['mark_updated']);
    expect(selectionEvents('login')).toEqual([]);
    expect(selectionEvents(CUSTOM_SELECTION, ['mark_created', 'habit_paused'])).toEqual([
      'habit_paused',
      'mark_created',
    ]);
  });
});

describe('pages', () => {
  it('joins the pages in order without repeating an event', () => {
    const pages = [
      { events: [{ id: 5 }, { id: 4 }], next_cursor: 'a' },
      { events: [{ id: 4 }, { id: 3 }], next_cursor: 'b' },
      { events: [{ id: 2 }, { id: 5 }], next_cursor: null },
    ];

    expect(pageEvents(pages).map((event) => event.id)).toEqual([5, 4, 3, 2]);
    expect(pageEvents(undefined)).toEqual([]);
  });
});

describe('people of the author filter', () => {
  it('lists me first and the others by email, once each', () => {
    const options = authorOptions(ANA, [[CAIO, ANA], [BIA, { ...CAIO }]]);

    expect(options).toEqual([ANA, BIA, CAIO]);
  });

  it('ignores invalid items and adds the person of the URL at the end', () => {
    const options = authorOptions(ANA, [[null, { id: 'x', email: 'x@example.com' }, { id: 4 }, BIA]], 9);

    expect(options).toEqual([ANA, BIA, { id: 9, email: null }]);
    expect(authorOptions(ANA, [[{ id: 4, email: null }, { id: 4, email: 'dani@example.com' }]], 4)).toEqual([
      ANA,
      { id: 4, email: 'dani@example.com' },
    ]);
    expect(authorOptions(ANA, [], ANA.id)).toEqual([ANA]);
    expect(authorOptions(null, [[BIA]])).toEqual([BIA]);
  });
});

describe('event texts', () => {
  it('describes a mark with its date in the time zone of the viewer', () => {
    const details = {
      mark_id: 100,
      author_id: 2,
      marked_at: '2026-03-02T15:00:00Z',
      duration_minutes: 30,
      cost_cents: 123450,
      has_note: true,
    };

    const created = describeEvent(entry('mark_created', details), context());
    // O espaço antes do PM depende da versão do ICU (comum ou estreito)
    expect(created.text).toMatch(/^Mark added for 3\/2\/26, 12:00\sPM$/);
    expect(created.lines).toEqual([
      'Mark made by bia@example.com',
      'Duration: 30 min',
      'Cost: 1,234.50',
      'With a note',
    ]);
    const deleted = describeEvent(entry('mark_deleted', details), context('pt', { timeZone: 'Asia/Tokyo' }));
    expect(deleted.text).toMatch(/^Marcação de 03\/03\/2026,?\s00:00 apagada$/);
    expect(deleted.lines).toEqual([
      'Marcação feita por bia@example.com',
      'Duração: 30 min',
      'Custo: 1.234,50',
      'Com observação',
    ]);
  });

  it('describes a mark of the author itself, without the optional details', () => {
    const details = { mark_id: 100, author_id: 1, marked_at: 'not a date', duration_minutes: null, has_note: false };

    expect(describeEvent(entry('mark_created', details), context())).toEqual({ text: 'Mark added', lines: [] });
    expect(describeEvent(entry('mark_deleted', {}), context())).toEqual({ text: 'Mark deleted', lines: [] });
    // Autor da marcação que já não tem conta: o id, sem email
    expect(
      describeEvent(entry('mark_deleted', { author_id: 7 }, { author: null }), context()).lines,
    ).toEqual(['Mark made by person #7']);
  });

  it('lists what changed in the settings', () => {
    const changes = [
      { field: 'name', old: 'Run', new: 'Running' },
      { field: 'code', old: null, new: 'RUN' },
      { field: 'description' },
      { field: 'color', old: 'teal', new: 'violet' },
      { field: 'goal_type', old: 'min', new: 'exact' },
      { field: 'goal_count', old: 3, new: 1200 },
      { field: 'goal_period', old: 'week', new: 'month' },
      { field: 'score_enabled', old: false, new: true },
      { field: 'duration_minutes', old: 15, new: 1 },
      { field: 'cost_level', old: 'habit', new: 'mark' },
      { field: 'cost_limit_cents', old: 5000, new: null },
      { field: 'color', old: 'teal', new: 'silver' },
      { field: 'brand_new', old: 1, new: 2 },
      { field: 'brand_new' },
      { field: 'score_enabled', old: 'yes', new: 0 },
      'not a change',
      { old: 1 },
    ];

    expect(describeEvent(entry('habit_updated', { changes }), context())).toEqual({
      text: 'Habit settings changed',
      lines: [
        'Name: Run → Running',
        'Code: (empty) → RUN',
        'Changed: Description',
        'Color: teal → violet',
        'Goal type: at least → exactly',
        'Goal: 3 → 1,200',
        'Goal period: week → month',
        'Score: off → on',
        'Duration: 15 min → 1 min',
        'Where the cost is set: on the habit → on each mark',
        'Cost limit: 50.00 → (empty)',
        'Color: teal → silver',
        'brand_new: 1 → 2',
        'Changed: brand_new',
        'Score: yes → 0',
      ],
    });
    expect(describeEvent(entry('habit_updated', { changes: 'none' }), context()).lines).toEqual([]);
  });

  it('lists what changed in a mark', () => {
    const changes = [{ field: 'note' }, { field: 'cost_cents', old: 100, new: 250 }];

    expect(describeEvent(entry('mark_updated', { mark_id: 100, changes }), context('pt'))).toEqual({
      text: 'Marcação editada',
      lines: ['Alterado: Observação', 'Custo: 1,00 → 2,50'],
    });
  });

  it('describes the sharing events with the role and the person', () => {
    const ctx = context();

    expect(describeEvent(entry('invite_created', { invite_id: 4, role: 'editor' }), ctx).text).toBe(
      'Invite sent with the editor role',
    );
    expect(describeEvent(entry('invite_accepted', { invite_id: 4, role: 'viewer' }), ctx).text).toBe(
      'Invite accepted: joined with the viewer role',
    );
    expect(describeEvent(entry('member_left', {}), ctx).text).toBe('Left the habit (role: (empty))');
    expect(describeEvent(entry('member_removed', { member_id: 2, role: 'viewer' }), ctx).text).toBe(
      'Removed bia@example.com from the habit (role: viewer)',
    );
    expect(describeEvent(entry('member_removed', { member_id: 8, role: 'editor' }), ctx).text).toBe(
      'Removed person #8 from the habit (role: editor)',
    );
    expect(
      describeEvent(
        entry('member_role_changed', { changes: [{ field: 'role', old: 'viewer', new: 'editor' }] }),
        ctx,
      ),
    ).toEqual({ text: 'Changed the role of someone', lines: ['Role: viewer → editor'] });
    expect(
      describeEvent(entry('member_role_changed', { member_id: 2, changes: [] }), context('pt')).text,
    ).toBe('Mudou o papel de bia@example.com');
  });

  it('describes the habit events and an unknown event', () => {
    const ctx = context('pt');

    expect(describeEvent(entry('habit_created', null), ctx)).toEqual({ text: 'Hábito criado', lines: [] });
    expect(describeEvent(entry('habit_archived'), ctx).text).toBe('Hábito arquivado');
    expect(describeEvent(entry('login'), ctx)).toEqual({ text: 'Evento login', lines: [] });
  });

  it('describes one change on its own', () => {
    expect(describeChange({ field: 'multi_mark', old: true, new: false }, context('pt'))).toBe(
      'Várias marcações por dia: ligado → desligado',
    );
    expect(describeChange({ field: 'goal_count', old: 1000, new: 2 }, context('pt'))).toBe('Meta: 1.000 → 2');
  });
});
