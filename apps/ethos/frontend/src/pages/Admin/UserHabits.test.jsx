import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { accountFixture, adminRequests, signedIn, trackRequests } from '../../test/admin';
import { axe } from '../../test/axe';
import { renderApp } from '../../test/render';
import { api, server } from '../../test/server';

const NOTICE = /Every access to this content is recorded in the audit log/;

function habit(overrides = {}) {
  return {
    id: 10,
    role: 'owner',
    name: 'Read',
    code: 'RD',
    label: 'RD',
    description: 'Twenty pages a day',
    color: 'teal',
    goal_type: 'min',
    goal_count: 3,
    goal_period: 'week',
    multi_mark: false,
    duration_enabled: true,
    duration_minutes: 30,
    notes_enabled: true,
    score_enabled: true,
    score_threshold: 70,
    reward: 'A coffee',
    punishment: null,
    cost_enabled: true,
    cost_level: 'habit',
    cost_cents: 1250,
    cost_limit_cents: 10000,
    cost_limit_period: 'month',
    status: 'active',
    archived_at: null,
    created_at: '2026-09-01T12:00:00Z',
    updated_at: '2026-09-01T12:00:00Z',
    ...overrides,
  };
}

const HABITS = [
  habit(),
  habit({
    id: 11,
    name: 'No sugar',
    code: null,
    label: 'No sugar',
    description: null,
    color: 'red',
    goal_type: 'max',
    goal_count: 0,
    goal_period: 'month',
    duration_enabled: false,
    score_enabled: false,
    reward: null,
    punishment: 'No dessert',
    cost_enabled: false,
    cost_cents: null,
    cost_limit_cents: null,
    cost_limit_period: null,
    status: 'archived',
  }),
];

function mark(overrides = {}) {
  return {
    id: 100,
    habit_id: 10,
    author: { id: 2, email: 'bia@example.com' },
    marked_at: '2026-10-20T15:00:00Z',
    duration_minutes: 45,
    cost_cents: 1250,
    note: 'Chapter <i>three</i>',
    created_at: '2026-10-20T15:00:00Z',
    updated_at: '2026-10-20T15:00:00Z',
    ...overrides,
  };
}

/** GET /admin/users/2/habits: duas páginas de marcações, filtradas por habit_id. */
function content() {
  const marks = [mark(), mark({ id: 99, habit_id: 11, author: null, duration_minutes: null, cost_cents: null, note: null })];
  server.use(
    http.get(api('/admin/users/2/habits'), ({ request }) => {
      const params = new URL(request.url).searchParams;
      const habitId = params.get('habit_id');
      const page = marks.filter((item) => habitId === null || item.habit_id === Number(habitId));
      const first = params.get('cursor') === null;
      return HttpResponse.json({
        user: accountFixture(),
        habits: HABITS,
        marks: first ? page.slice(0, 1) : page.slice(1),
        next_cursor: first && page.length > 1 ? 'next' : null,
      });
    }),
  );
}

describe('habit content of an account', () => {
  it('warns that access is recorded and only loads after the click', async () => {
    signedIn();
    content();
    const requests = trackRequests();
    const user = userEvent.setup();
    const { container } = renderApp('/admin/contas/2');

    const notice = await screen.findByRole('note');
    expect(notice.textContent).toMatch(NOTICE);
    expect(await axe(container)).toHaveNoViolations();
    expect(adminRequests(requests)).toEqual([]);

    await user.click(screen.getByRole('button', { name: 'Show the content' }));

    expect(await screen.findByRole('heading', { level: 2, name: 'bia@example.com' })).toBeDefined();
    // O aviso continua na tela
    expect(screen.getByRole('note').textContent).toMatch(NOTICE);
    expect(adminRequests(requests)).toEqual([{ method: 'GET', path: '/admin/users/2/habits', query: {} }]);

    const read = screen.getByRole('heading', { level: 3, name: /Read/ }).closest('li');
    expect(read.textContent).toContain('At least 3 per week');
    expect(read.textContent).toContain('On, success from 70');
    expect(read.textContent).toContain('30 min');
    expect(read.textContent).toContain('12.50');
    expect(read.textContent).toContain('100.00 per month');
    expect(read.textContent).toContain('A coffee');
    expect(read.querySelector('[data-habit-color="teal"]')).not.toBeNull();

    const sugar = screen.getByRole('heading', { level: 3, name: /No sugar/ }).closest('li');
    expect(sugar.textContent).toContain('archived');
    expect(sugar.textContent).toContain('At most 0 per month');
    expect(sugar.textContent).toContain('No dessert');

    const marks = screen.getByRole('heading', { level: 2, name: 'Marks' }).closest('section');
    // 15:00 UTC em São Paulo; a observação aparece como texto
    expect(marks.textContent).toContain('12:00');
    expect(marks.textContent).toContain('Chapter <i>three</i>');
    expect(marks.querySelector('i')).toBeNull();
    expect(marks.textContent).toContain('45 min');

    await user.click(within(marks).getByRole('button', { name: 'Load more' }));

    expect(await within(marks).findByText('Removed user')).toBeDefined();
    expect(adminRequests(requests).at(-1).query).toEqual({ cursor: 'next' });
    expect(await axe(container)).toHaveNoViolations();
  });

  it('filters the marks by habit', async () => {
    signedIn();
    content();
    const requests = trackRequests();
    const user = userEvent.setup();
    renderApp('/admin/contas/2');

    await user.click(await screen.findByRole('button', { name: 'Show the content' }));
    await user.selectOptions(await screen.findByLabelText('Habit'), 'No sugar');

    await waitFor(() => expect(adminRequests(requests).at(-1).query).toEqual({ habit_id: '11' }));
    expect(await screen.findByText('Removed user')).toBeDefined();
  });

  it('asks again for another account', async () => {
    signedIn();
    content();
    const requests = trackRequests();
    const user = userEvent.setup();
    const { router } = renderApp('/admin/contas/2');

    await user.click(await screen.findByRole('button', { name: 'Show the content' }));
    await screen.findByRole('heading', { level: 2, name: 'bia@example.com' });

    await router.navigate('/admin/contas/3');

    expect(await screen.findByRole('button', { name: 'Show the content' })).toBeDefined();
    expect(adminRequests(requests)).toHaveLength(1);
  });

  it('shows not found for an invalid id, without calling the API', async () => {
    signedIn();
    const requests = trackRequests();
    const { container } = renderApp('/admin/contas/abc');

    expect((await screen.findByRole('alert')).textContent).toContain('Not found.');
    expect(screen.queryByRole('button', { name: 'Show the content' })).toBeNull();
    expect(adminRequests(requests)).toEqual([]);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows the API error for an account that no longer exists', async () => {
    signedIn();
    server.use(
      http.get(api('/admin/users/9/habits'), () =>
        HttpResponse.json({ error: 'not_found', field: null }, { status: 404 }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/admin/contas/9');

    await user.click(await screen.findByRole('button', { name: 'Show the content' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Not found.');
  });

  it('shows an account without habits', async () => {
    signedIn();
    server.use(
      http.get(api('/admin/users/2/habits'), () =>
        HttpResponse.json({ user: accountFixture({ last_login_at: null }), habits: [], marks: [], next_cursor: null }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/admin/contas/2');

    await user.click(await screen.findByRole('button', { name: 'Show the content' }));

    expect(await screen.findByText('This account owns no habits.')).toBeDefined();
    expect(screen.getByText('No marks.')).toBeDefined();
    expect(screen.getByText('Never signed in')).toBeDefined();
    expect(screen.queryByLabelText('Habit')).toBeNull();
  });
});
