import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { BASENAME } from '../../paths';
import { axe } from '../../test/axe';
import { habitFixture, markFixture, mockHabitsApi } from '../../test/habits';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

// Um ano inteiro de botões no jsdom (com axe) é pesado: folga para o CI,
vi.setConfig({ testTimeout: 15_000 });
// e o primeiro desenho do ano pode passar de 1 s (o padrão do findBy/waitFor) com os testes em paralelo
configure({ asyncUtilTimeout: 5_000 });

const NOW = new Date('2026-03-10T15:00:00Z');
const COLORS = ['red', 'orange', 'amber', 'green', 'blue', 'violet'];
const CODES = ['RUN', 'READ', 'GYM', 'MED', 'H2O', 'SLP'];

function signedIn() {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
}

/** Seis hábitos, todos marcados em 4 de março; RUN e READ também em 2 de março. */
function sixHabits() {
  const habits = CODES.map((code, index) =>
    habitFixture({ id: index + 1, code, name: `Habit ${index + 1}`, color: COLORS[index] }),
  );
  const marks = Object.fromEntries(
    habits.map((habit) => [
      habit.id,
      [
        ...(habit.id <= 2 ? [markFixture({ id: habit.id * 10, habit_id: habit.id, marked_at: '2026-03-02T15:00:00Z' })] : []),
        markFixture({ id: habit.id * 10 + 1, habit_id: habit.id, marked_at: '2026-03-04T15:00:00Z' }),
      ],
    ]),
  );
  return { habits, marks };
}

function dayButton(container, day) {
  return container.querySelector(`[data-day="${day}"]`);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('home calendar', () => {
  it('shows up to 4 dots and "+N" for the rest', async () => {
    signedIn();
    mockHabitsApi(sixHabits());
    const { container } = renderApp('/');

    await waitFor(() => {
      expect(dayButton(container, '2026-03-04').querySelectorAll('[data-habit-color]')).toHaveLength(4);
    });
    const day = dayButton(container, '2026-03-04');
    const dots = [...day.querySelectorAll('[data-habit-color]')].map((dot) => dot.dataset.habitColor);

    expect(dots).toEqual(['red', 'orange', 'amber', 'green']);
    expect(day.textContent).toContain('+2');
    // Siglas no hover e no foco (dica) e no nome acessível
    expect(day.getAttribute('aria-label')).toBe(
      'Wednesday, March 4, 2026. Marked: RUN, READ, GYM, MED, H2O, SLP',
    );
    expect(day.textContent).toContain('RUN, READ, GYM, MED, H2O, SLP');

    const fewer = dayButton(container, '2026-03-02');
    expect(fewer.querySelectorAll('[data-habit-color]')).toHaveLength(2);
    expect(fewer.textContent).not.toContain('+');
    expect(dayButton(container, '2026-03-03').getAttribute('aria-label')).toBe(
      'Tuesday, March 3, 2026. Nothing marked',
    );
  });

  it('loads each habit year in one request', async () => {
    signedIn();
    const { requests } = mockHabitsApi(sixHabits());
    const { container } = renderApp('/');

    await waitFor(() => {
      expect(dayButton(container, '2026-03-04').querySelectorAll('[data-habit-color]')).toHaveLength(4);
    });
    const markRequests = requests.filter((request) => request.path.endsWith('/marks'));

    expect(markRequests.map((request) => request.path).sort()).toEqual(
      CODES.map((_, index) => `/habits/${index + 1}/marks`).sort(),
    );
  });

  it('has no accessibility violations', async () => {
    signedIn();
    mockHabitsApi(sixHabits());
    const { container } = renderApp('/?day=2026-03-04');

    await waitFor(() => {
      expect(dayButton(container, '2026-03-04').querySelectorAll('[data-habit-color]')).toHaveLength(4);
    });

    expect(await axe(container)).toHaveNoViolations();
  });

  it('marks a habit from the day panel and shows it in the calendar', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture({ id: 1 }), habitFixture({ id: 2, code: null, name: 'Water', multi_mark: true })] });
    const bodies = [];
    server.use(
      http.post(api('/habits/:id/toggle'), async ({ request }) => {
        const body = await request.json();
        bodies.push(body);
        return HttpResponse.json({ marked: true, mark: markFixture({ id: 9, marked_at: body.marked_at }) });
      }),
    );
    const user = userEvent.setup();
    const { container } = renderApp('/');

    // Hoje já vem escolhido
    expect(await screen.findByRole('heading', { level: 2, name: 'Tuesday, March 10, 2026' })).toBeDefined();
    await user.click(dayButton(container, '2026-03-04'));
    const panel = screen.getByRole('region', { name: 'Wednesday, March 4, 2026' });
    const rows = within(panel).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(within(rows[1]).getByRole('link', { name: 'Water' }).getAttribute('href')).toBe(
      `${BASENAME}/habits/2?day=2026-03-04`,
    );
    expect(within(rows[1]).getByRole('button', { name: 'Add a mark to Water' })).toBeDefined();

    await user.click(within(rows[0]).getByRole('button', { name: 'Mark RUN' }));

    expect(bodies).toEqual([
      {
        day_start: '2026-03-04T03:00:00.000Z',
        day_end: '2026-03-05T03:00:00.000Z',
        marked_at: '2026-03-04T15:00:00.000Z',
      },
    ]);
    await waitFor(() => {
      expect(dayButton(container, '2026-03-04').getAttribute('aria-label')).toBe(
        'Wednesday, March 4, 2026. Marked: RUN',
      );
    });
    expect(within(rows[0]).getByRole('button', { name: 'Unmark RUN' })).toBeDefined();
  });

  it('opens a habit tab from the tabs', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture({ id: 3 })] });
    const user = userEvent.setup();
    const { router } = renderApp('/');

    const tabs = await screen.findByRole('navigation', { name: 'Habits' });
    await user.click(await within(tabs).findByRole('link', { name: 'RUN' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'RUN' })).toBeDefined();
    expect(router.state.location.pathname).toBe(`${BASENAME}/habits/3`);
  });

  it('keeps archived habits out of the calendar, in their own section', async () => {
    signedIn();
    const archived = habitFixture({ id: 9, code: 'OLD', status: 'archived' });
    const { requests } = mockHabitsApi({ habits: [habitFixture({ id: 1 })], archived: [archived] });
    const user = userEvent.setup();
    renderApp('/');

    const tabs = await screen.findByRole('navigation', { name: 'Habits' });
    await within(tabs).findByRole('link', { name: 'RUN' });
    expect(within(tabs).queryByRole('link', { name: 'OLD' })).toBeNull();
    // A lista dos arquivados só é buscada ao abrir a seção
    expect(requests.some((request) => request.query.archived)).toBe(false);

    await user.click(screen.getByText('Archived habits'));

    expect((await screen.findByRole('link', { name: 'OLD' })).getAttribute('href')).toBe(`${BASENAME}/habits/9`);
    expect(requests.filter((request) => request.path === '/habits/9/marks')).toEqual([]);
  });

  it('says when there are no habits yet', async () => {
    signedIn();
    mockHabitsApi({ habits: [] });
    const { container } = renderApp('/');

    expect(await screen.findByText('You do not have any habits yet.')).toBeDefined();
    expect(container.querySelector('[data-day]')).toBeNull();
  });

  it('shows the error of the habit list', async () => {
    signedIn();
    server.use(
      http.get(api('/habits'), () => HttpResponse.json({ error: 'forbidden', field: null }, { status: 403 })),
    );
    renderApp('/');

    expect((await screen.findByRole('alert')).textContent).toContain('You do not have permission');
  });
});
