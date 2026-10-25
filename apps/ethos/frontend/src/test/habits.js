import { HttpResponse, http } from 'msw';
import { api, server } from './server';

/** Um HabitOut da API (toggle, recursos desligados, dono). `label` segue a sigla, ou o nome. */
export function habitFixture(overrides = {}) {
  const habit = {
    id: 1,
    role: 'owner',
    name: 'Running',
    code: 'RUN',
    description: null,
    color: 'teal',
    goal_type: 'min',
    goal_count: 3,
    goal_period: 'week',
    multi_mark: false,
    duration_enabled: false,
    duration_minutes: null,
    notes_enabled: false,
    score_enabled: false,
    score_threshold: 70,
    reward: null,
    punishment: null,
    cost_enabled: false,
    cost_level: 'habit',
    cost_cents: null,
    cost_limit_cents: null,
    cost_limit_period: null,
    status: 'active',
    archived_at: null,
    created_at: '2026-01-05T12:00:00Z',
    updated_at: '2026-01-05T12:00:00Z',
    ...overrides,
  };
  return { ...habit, label: overrides.label ?? (habit.code || habit.name) };
}

/** Um MarkOut da API, criado por ana@example.com (id 1). */
export function markFixture(overrides = {}) {
  return {
    id: 100,
    habit_id: 1,
    author: { id: 1, email: 'ana@example.com' },
    marked_at: '2026-03-02T15:00:00Z',
    duration_minutes: null,
    cost_cents: null,
    note: null,
    created_at: '2026-03-02T15:00:00Z',
    updated_at: '2026-03-02T15:00:00Z',
    ...overrides,
  };
}

/**
 * API falsa dos hábitos e das marcações: GET /habits (com `?archived=true`, os arquivados),
 * GET /habits/{id} e GET /habits/{id}/marks (filtra por `from`/`to` e pagina por `pageSize`, com
 * cursor). `marks` é um objeto id → lista, que os testes podem mudar. Devolve `requests`, com
 * cada chamada (`{method, path, query}`), e `marks`.
 */
export function mockHabitsApi({ habits = [], archived = [], marks = {}, pageSize = 1000 } = {}) {
  const requests = [];
  const record = (request) => {
    const url = new URL(request.url);
    requests.push({
      method: request.method,
      path: url.pathname.replace(/^\/api\/ethos/, ''),
      query: Object.fromEntries(url.searchParams),
    });
    return url;
  };
  const find = (id) => [...habits, ...archived].find((habit) => habit.id === Number(id));
  server.use(
    http.get(api('/habits'), ({ request }) => {
      const url = record(request);
      return HttpResponse.json({ habits: url.searchParams.get('archived') ? archived : habits });
    }),
    http.get(api('/habits/:id'), ({ request, params }) => {
      record(request);
      const habit = find(params.id);
      if (!habit) return HttpResponse.json({ error: 'not_found', field: null }, { status: 404 });
      return HttpResponse.json(habit);
    }),
    http.get(api('/habits/:id/marks'), ({ request, params }) => {
      const url = record(request);
      const from = Date.parse(url.searchParams.get('from'));
      const to = Date.parse(url.searchParams.get('to'));
      const start = Number(url.searchParams.get('cursor') ?? 0);
      const inRange = (marks[params.id] ?? []).filter((mark) => {
        const at = Date.parse(mark.marked_at);
        return at >= from && at < to;
      });
      const page = inRange.slice(start, start + pageSize);
      const next = start + pageSize < inRange.length ? String(start + pageSize) : null;
      return HttpResponse.json({ marks: page, next_cursor: next });
    }),
  );
  return { requests, marks };
}

/** Promessa que o teste resolve na hora certa (para segurar uma resposta da API). */
export function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
