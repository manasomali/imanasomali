import { describe, expect, it, vi } from 'vitest';
import { configure, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { BASENAME, PATHS } from '../../paths';
import { axe } from '../../test/axe';
import { habitFixture, mockHabitsApi } from '../../test/habits';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

// A aba do hábito desenha o ano inteiro do calendário (teste do atalho): folga para o CI
vi.setConfig({ testTimeout: 15_000 });
configure({ asyncUtilTimeout: 5_000 });

const ANA = { id: 1, email: 'ana@example.com' };
const BIA = { id: 2, email: 'bia@example.com' };
const RUN = habitFixture();
const READ = habitFixture({ id: 2, name: 'Reading', code: null, color: 'violet', status: 'archived' });

function signedIn(overrides = {}) {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture(overrides))));
}

/** Um evento como no GET /history (por padrão, ana criou uma marcação no RUN). */
function eventFixture(overrides = {}) {
  return {
    id: 10,
    event: 'mark_created',
    created_at: '2026-03-02T15:00:00Z',
    habit: { id: RUN.id, label: RUN.label },
    author: ANA,
    details: {
      mark_id: 100,
      author_id: ANA.id,
      marked_at: '2026-03-02T15:00:00Z',
      duration_minutes: null,
      cost_cents: null,
      has_note: false,
    },
    ...overrides,
  };
}

/**
 * GET /history respondendo `respond(params)` (por padrão, nenhum evento), e os hábitos (RUN ativo,
 * READ arquivado) com os membros. Devolve a query de cada chamada do histórico, como texto.
 */
function historyApi(respond = () => ({ events: [], next_cursor: null })) {
  const calls = [];
  mockHabitsApi({ habits: [RUN], archived: [READ] });
  server.use(
    http.get(api('/history'), ({ request }) => {
      const params = new URL(request.url).searchParams;
      calls.push(params.toString());
      return HttpResponse.json(respond(params));
    }),
    http.get(api('/habits/:id/members'), ({ params }) =>
      HttpResponse.json({
        members:
          Number(params.id) === RUN.id
            ? [
                { user: ANA, role: 'owner', joined_at: '2026-01-05T12:00:00Z' },
                { user: BIA, role: 'editor', joined_at: '2026-01-06T12:00:00Z' },
              ]
            : [{ user: ANA, role: 'owner', joined_at: '2026-01-05T12:00:00Z' }],
      }),
    ),
  );
  return calls;
}

async function openHistory(path = PATHS.history, respond = undefined) {
  signedIn();
  const calls = historyApi(respond);
  const user = userEvent.setup();
  const result = renderApp(path);
  await screen.findByRole('heading', { level: 1, name: 'History' });
  // Os hábitos do filtro chegaram
  await screen.findByRole('option', { name: 'RUN (Running)' });
  return { ...result, calls, user };
}

function items() {
  return within(screen.getByRole('list', { name: 'Events' })).getAllByRole('listitem').filter(
    (item) => item.parentElement.tagName === 'OL',
  );
}

describe('history: events', () => {
  it('shows each event with the time, the habit, the description and the author', async () => {
    const events = [
      eventFixture(),
      eventFixture({
        id: 9,
        event: 'habit_updated',
        created_at: '2026-03-01T12:30:00Z',
        author: null,
        details: { changes: [{ field: 'goal_count', old: 3, new: 4 }, { field: 'description' }] },
      }),
      eventFixture({
        id: 8,
        event: 'member_removed',
        habit: { id: READ.id, label: READ.label },
        details: { member_id: BIA.id, role: 'viewer' },
      }),
    ];
    const { container } = await openHistory(PATHS.history, () => ({ events, next_cursor: null }));

    const [created, updated, removed] = await waitFor(() => {
      expect(items()).toHaveLength(3);
      return items();
    });

    // 15:00 UTC em São Paulo (UTC-3)
    const time = within(created).getByText(/^3\/2\/26, 12:00\sPM$/);
    expect(time.tagName).toBe('TIME');
    expect(time.getAttribute('datetime')).toBe('2026-03-02T15:00:00Z');
    expect(created.textContent).toMatch(/Mark added for 3\/2\/26, 12:00\sPM/);
    expect(within(created).getByText('By ana@example.com')).toBeDefined();
    expect(within(created).getByRole('link', { name: 'RUN' }).getAttribute('href')).toBe(`${BASENAME}/habits/1`);

    expect(within(updated).getByText('Habit settings changed')).toBeDefined();
    expect(within(updated).getByText('Goal: 3 → 4')).toBeDefined();
    expect(within(updated).getByText('Changed: Description')).toBeDefined();
    expect(within(updated).getByText('By removed user')).toBeDefined();

    expect(within(removed).getByText('Removed person #2 from the habit (role: viewer)')).toBeDefined();
    expect(within(removed).getByRole('link', { name: 'Reading' })).toBeDefined();

    expect(screen.getByText('3 events shown.').getAttribute('role')).toBe('status');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('converts the time to the time zone of the account', async () => {
    signedIn({ timezone: 'Asia/Tokyo' });
    historyApi(() => ({ events: [eventFixture()], next_cursor: null }));
    renderApp(PATHS.history);

    // 15:00 UTC é meia-noite do dia seguinte em Tóquio (UTC+9)
    const time = await screen.findByText(/^3\/3\/26, 12:00\sAM$/);
    expect(time.getAttribute('datetime')).toBe('2026-03-02T15:00:00Z');
    expect(screen.getByText(/Dates in your time zone \(Asia\/Tokyo\)/)).toBeDefined();
  });

  it('shows the empty list', async () => {
    const { container } = await openHistory();

    expect(await screen.findByText('No events found.')).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows the error of the API and tries again', async () => {
    let fail = true;
    const { user } = await openHistory(PATHS.history, () => {
      if (fail) throw HttpResponse.json({ error: 'internal_error', field: null }, { status: 500 });
      return { events: [eventFixture()], next_cursor: null };
    });

    const alert = await screen.findByRole('alert', {}, { timeout: 10_000 });
    expect(alert.textContent).toContain('Something went wrong on our side.');

    fail = false;
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));

    expect(await screen.findByText('By ana@example.com')).toBeDefined();
  });
});

describe('history: filters', () => {
  const FILTERS = [
    ['habit', async (user) => user.selectOptions(screen.getByLabelText('Habit'), 'RUN (Running)'), 'habit_id=1'],
    [
      'archived habit',
      async (user) => user.selectOptions(screen.getByLabelText('Habit'), 'Reading'),
      'habit_id=2',
    ],
    ['person', async (user) => user.selectOptions(screen.getByLabelText('Person'), 'ana@example.com (you)'), 'user_id=1'],
    ['event', async (user) => user.selectOptions(screen.getByLabelText('Event'), 'Mark deleted'), 'event=mark_deleted'],
    [
      'group of events',
      async (user) => user.selectOptions(screen.getByLabelText('Event'), 'All sharing events'),
      'event=invite_created&event=invite_canceled&event=invite_accepted&event=invite_declined'
        + '&event=member_left&event=member_removed&event=member_role_changed',
    ],
    [
      'start date',
      async () => fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-03-01' } }),
      'from=2026-03-01',
    ],
    [
      'end date',
      async () => fireEvent.change(screen.getByLabelText('Until'), { target: { value: '2026-03-31' } }),
      'to=2026-03-31',
    ],
  ];

  it.each(FILTERS)('sends the %s filter to the API and to the URL', async (_name, choose, expected) => {
    const { calls, user, router } = await openHistory();
    await waitFor(() => expect(calls).toEqual(['']));

    await choose(user);
    // Nada muda antes do "Filtrar"
    expect(calls).toEqual(['']);
    await user.click(screen.getByRole('button', { name: 'Filter' }));

    await waitFor(() => expect(calls.at(-1)).toBe(expected));
    expect(router.state.location.search).toBe(`?${expected}`);
    // O formulário continua o mesmo: o foco fica no botão
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Filter' }));
  });

  it('combines the filters and lists the members of the chosen habit', async () => {
    const { calls, user, container } = await openHistory();
    const person = screen.getByLabelText('Person');
    expect(within(person).queryByRole('option', { name: 'bia@example.com' })).toBeNull();

    await user.selectOptions(screen.getByLabelText('Habit'), 'RUN (Running)');
    await user.selectOptions(person, await within(person).findByRole('option', { name: 'bia@example.com' }));
    await user.selectOptions(screen.getByLabelText('Event'), 'All mark events');
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-03-01' } });
    fireEvent.change(screen.getByLabelText('Until'), { target: { value: '2026-03-31' } });
    await user.click(screen.getByRole('button', { name: 'Filter' }));

    await waitFor(() =>
      expect(calls.at(-1)).toBe(
        'habit_id=1&user_id=2&event=mark_created&event=mark_updated&event=mark_deleted&from=2026-03-01&to=2026-03-31',
      ),
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('opens a shared link with its filters and goes back to the previous ones', async () => {
    const shared = 'habit_id=1&user_id=2&event=habit_paused&event=mark_created&from=2026-03-01&to=2026-03-31';
    const { calls, user, router } = await openHistory(`${PATHS.history}?${shared}`);

    await waitFor(() => expect(calls).toEqual([shared]));
    expect(screen.getByLabelText('Habit').value).toBe('1');
    expect(await screen.findByRole('option', { name: 'bia@example.com', selected: true })).toBeDefined();
    // Combinação que não é um grupo: o seletor mostra a escolha do link
    expect(screen.getByRole('option', { name: '2 events chosen in the link', selected: true })).toBeDefined();
    expect(screen.getByLabelText('From').value).toBe('2026-03-01');
    expect(screen.getByLabelText('Until').value).toBe('2026-03-31');

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(calls.at(-1)).toBe(''));
    expect(router.state.location.search).toBe('');
    expect(screen.getByLabelText('Habit').value).toBe('');
    expect(screen.getByLabelText('Event').value).toBe('');

    // Voltar no navegador devolve os filtros do link, na tela e na lista (do cache, ainda recente)
    await router.navigate(-1);

    await waitFor(() => expect(screen.getByLabelText('Habit').value).toBe('1'));
    expect(screen.getByLabelText('From').value).toBe('2026-03-01');
    expect(router.state.location.search).toBe(`?${shared}`);
    expect(calls).toEqual([shared, '']);
  });

  it('ignores invalid values in the link', async () => {
    const { calls } = await openHistory(`${PATHS.history}?habit_id=abc&event=login&from=2026-02-30&to=2026-03-31`);

    await waitFor(() => expect(calls).toEqual(['to=2026-03-31']));
  });

  it('refuses an end date before the start date without calling the API', async () => {
    const { calls, user, router } = await openHistory();
    await waitFor(() => expect(calls).toHaveLength(1));

    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-03-10' } });
    fireEvent.change(screen.getByLabelText('Until'), { target: { value: '2026-03-01' } });
    await user.click(screen.getByRole('button', { name: 'Filter' }));

    const until = screen.getByLabelText('Until');
    expect(until.getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(until);
    expect(screen.getByText('The end date must be the same as or after the start date.')).toBeDefined();
    expect(calls).toHaveLength(1);
    expect(router.state.location.search).toBe('');
  });

  it('does not call the API for an inverted period in the link', async () => {
    const { calls, container } = await openHistory(`${PATHS.history}?from=2026-03-10&to=2026-03-01`);

    expect(screen.getByLabelText('Until').getAttribute('aria-invalid')).toBe('true');
    expect(screen.getAllByText('The end date must be the same as or after the start date.')).toHaveLength(2);
    expect(calls).toEqual([]);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('history: pages', () => {
  it('loads more with the cursor and the same filters, without repeating events', async () => {
    const first = [eventFixture({ id: 30 }), eventFixture({ id: 20, event: 'habit_paused', details: {} })];
    // A segunda página repete o 20 (ex.: resposta de um cursor velho): aparece uma vez só
    const second = [
      eventFixture({ id: 20, event: 'habit_paused', details: {} }),
      eventFixture({ id: 10, event: 'habit_created', details: {} }),
    ];
    const { calls, user, container } = await openHistory(`${PATHS.history}?habit_id=1`, (params) =>
      params.get('cursor') === 'page-2'
        ? { events: second, next_cursor: null }
        : { events: first, next_cursor: 'page-2' },
    );
    await waitFor(() => expect(items()).toHaveLength(2));
    expect(screen.getByText('2 events shown.')).toBeDefined();

    await user.click(screen.getByRole('button', { name: 'Load more' }));

    await waitFor(() => expect(items()).toHaveLength(3));
    expect(calls).toEqual(['habit_id=1', 'habit_id=1&cursor=page-2']);
    const texts = items().map((item) => item.querySelector('p').textContent);
    expect(texts[0]).toMatch(/^Mark added for /);
    expect(texts.slice(1)).toEqual(['Habit paused', 'Habit created']);
    expect(screen.getByText('3 events shown.')).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
    // O foco vai para o primeiro evento novo
    expect(document.activeElement).toBe(items()[2]);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows the error of the next page and tries again', async () => {
    let fail = true;
    const { user } = await openHistory(PATHS.history, (params) => {
      if (params.get('cursor') !== 'page-2') return { events: [eventFixture({ id: 30 })], next_cursor: 'page-2' };
      if (fail) throw HttpResponse.json({ error: 'not_found', field: null }, { status: 404 });
      return { events: [eventFixture({ id: 10, event: 'habit_created', details: {} })], next_cursor: null };
    });
    await waitFor(() => expect(items()).toHaveLength(1));

    await user.click(screen.getByRole('button', { name: 'Load more' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Not found.');
    expect(items()).toHaveLength(1);

    fail = false;
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));

    await waitFor(() => expect(items()).toHaveLength(2));
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('history: links', () => {
  it('is in the main menu', async () => {
    await openHistory();

    const menu = screen.getByRole('navigation', { name: 'Main navigation' });
    const link = within(menu).getByRole('link', { name: 'History' });
    expect(link.getAttribute('href')).toBe(`${BASENAME}${PATHS.history}`);
    expect(link.getAttribute('aria-current')).toBe('page');
  });

  it('opens from the habit tab already filtered by the habit', async () => {
    signedIn();
    const calls = historyApi();
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1');

    const sections = await screen.findByRole('navigation', { name: 'Habit sections' });
    const link = within(sections).getByRole('link', { name: 'History' });
    expect(link.getAttribute('href')).toBe(`${BASENAME}/historico?habit_id=1`);

    await user.click(link);

    expect(await screen.findByRole('heading', { level: 1, name: 'History' })).toBeDefined();
    expect(router.state.location.search).toBe('?habit_id=1');
    await waitFor(() => expect(calls).toEqual(['habit_id=1']));
    expect(screen.getByLabelText('Habit').value).toBe('1');
  });
});
