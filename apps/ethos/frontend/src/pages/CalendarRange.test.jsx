import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { markKeys } from '../api/marks';
import { BASENAME } from '../paths';
import { axe } from '../test/axe';
import { deferred, habitFixture, markFixture, mockHabitsApi } from '../test/habits';
import { meFixture, renderApp } from '../test/render';
import { api, server } from '../test/server';

// Faixa do calendário (mês, 3 meses ou ano) nas duas abas. O ano inteiro no jsdom (com axe) é
// pesado: folga para o CI, como nos testes das telas do calendário
vi.setConfig({ testTimeout: 20_000 });
configure({ asyncUtilTimeout: 5_000 });

// "Agora": terça, 10 de março de 2026, 12:00 em São Paulo (UTC-3)
const NOW = new Date('2026-03-10T15:00:00Z');
const TIME_ZONE = 'America/Sao_Paulo';
const YEAR_2025 = { from: '2025-01-01T03:00:00.000Z', to: '2026-01-01T03:00:00.000Z' };
const YEAR_2026 = { from: '2026-01-01T03:00:00.000Z', to: '2027-01-01T03:00:00.000Z' };

function signedIn() {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
}

/** Nomes dos meses na tela, na ordem. */
function shownMonths() {
  const calendar = screen.getByRole('group', { name: /^Calendar for / });
  return [...calendar.querySelectorAll('h3')].map((heading) => heading.textContent);
}

/** Botão do dia, pelo começo do aria-label ("Wednesday, March 4, 2026"). */
function dayButton(date) {
  return screen.getByRole('button', { name: new RegExp(`^${date}\\.`) });
}

function findDay(date) {
  return screen.findByRole('button', { name: new RegExp(`^${date}\\.`) });
}

/** As buscas de marcações do hábito `id`, como `{from, to}`. */
function markQueries(requests, id = 1) {
  return requests
    .filter((request) => request.path === `/habits/${id}/marks`)
    .map(({ query }) => ({ from: query.from, to: query.to }));
}

function search(router) {
  return router.state.location.search;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('calendar range: habit tab', () => {
  it('shows the whole year by default, the current month or the 3 months up to it', async () => {
    signedIn();
    const { requests } = mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    const { container, router } = renderApp('/habits/1');

    // Quem nunca escolheu vê o ano inteiro
    await findDay('Tuesday, March 10, 2026');
    expect(screen.getByRole('radio', { name: 'Year' }).checked).toBe(true);
    expect(shownMonths()).toHaveLength(12);
    expect(screen.getByRole('group', { name: 'Calendar for 2026' })).toBeDefined();

    await user.click(screen.getByRole('radio', { name: 'Month' }));

    expect(shownMonths()).toEqual(['March']);
    expect(screen.getByRole('heading', { level: 2, name: 'March 2026' })).toBeDefined();
    expect(search(router)).toBe('?range=month&month=2026-03');
    expect(window.localStorage.getItem('ethos:calendar-range')).toBe('month');
    // Hoje continua escolhido; os dias depois dele, desabilitados
    expect(screen.getByRole('heading', { level: 2, name: 'Tuesday, March 10, 2026' })).toBeDefined();
    expect(container.querySelectorAll('[data-day]')).toHaveLength(31);
    expect(container.querySelectorAll('[aria-disabled="true"]')).toHaveLength(21);
    expect(screen.getByRole('button', { name: 'Next month (April 2026)' }).disabled).toBe(true);
    expect(await axe(container)).toHaveNoViolations();

    await user.click(screen.getByRole('radio', { name: '3 months' }));

    // O mês atual e os dois anteriores
    expect(shownMonths()).toEqual(['January', 'February', 'March']);
    expect(screen.getByRole('heading', { level: 2, name: /^Jan\s–\sMar 2026$/ })).toBeDefined();
    expect(search(router)).toBe('?range=3months&month=2026-03');
    expect(container.querySelectorAll('[data-day]')).toHaveLength(31 + 28 + 31);
    // Só o resto de março está no futuro
    expect(container.querySelectorAll('[aria-disabled="true"]')).toHaveLength(21);
    expect(screen.getByRole('button', { name: /^Next 3 months \(/ }).disabled).toBe(true);
    expect(await axe(container)).toHaveNoViolations();

    // Todas as faixas leem o mesmo ano do cache: uma busca só
    expect(markQueries(requests)).toEqual([YEAR_2026]);
  });

  it.each([
    ['2026-02', ['December 2025', 'January 2026', 'February 2026'], /^Dec 2025\s–\sFeb 2026$/],
    ['2026-01', ['November 2025', 'December 2025', 'January 2026'], /^Nov 2025\s–\sJan 2026$/],
  ])('crosses the year in the 3-month window ending at %s', async (month, months, period) => {
    signedIn();
    const { requests } = mockHabitsApi({
      habits: [habitFixture()],
      marks: {
        1: [
          markFixture({ id: 1, marked_at: '2025-12-31T15:00:00Z' }),
          markFixture({ id: 2, marked_at: '2026-01-02T15:00:00Z' }),
        ],
      },
    });
    const { container } = renderApp(`/habits/1?range=3months&month=${month}`);

    const lastDay = await findDay('Wednesday, December 31, 2025');
    expect(shownMonths()).toEqual(months);
    expect(screen.getByRole('heading', { level: 2, name: period })).toBeDefined();
    expect(screen.getByRole('radio', { name: '3 months' }).checked).toBe(true);
    // As marcações dos dois anos aparecem, cada ano numa busca
    await waitFor(() => expect(lastDay.getAttribute('aria-label')).toMatch(/Marked$/));
    expect(dayButton('Friday, January 2, 2026').getAttribute('aria-label')).toMatch(/Marked$/);
    expect(markQueries(requests).sort((a, b) => a.from.localeCompare(b.from))).toEqual([
      YEAR_2025,
      YEAR_2026,
    ]);
    // Hoje não está na faixa: nenhum dia escolhido
    expect(screen.getByText('Choose a day in the calendar to see its marks.')).toBeDefined();
    expect(container.querySelectorAll('[aria-disabled="true"]')).toHaveLength(0);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('moves by one month in the month range', async () => {
    signedIn();
    const { requests } = mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1?range=month');

    await findDay('Tuesday, March 10, 2026');
    await user.click(screen.getByRole('button', { name: 'Previous month (February 2026)' }));

    expect(screen.getByRole('heading', { level: 2, name: 'February 2026' })).toBeDefined();
    expect(shownMonths()).toEqual(['February']);
    expect(search(router)).toBe('?range=month&month=2026-02');
    // Hoje saiu da faixa: nenhum dia escolhido
    expect(screen.getByText('Choose a day in the calendar to see its marks.')).toBeDefined();

    await user.click(screen.getByRole('button', { name: 'Previous month (January 2026)' }));
    await user.click(screen.getByRole('button', { name: 'Previous month (December 2025)' }));

    expect(await findDay('Wednesday, December 31, 2025')).toBeDefined();
    expect(shownMonths()).toEqual(['December']);
    expect(search(router)).toBe('?range=month&month=2025-12');
    await waitFor(() => expect(markQueries(requests)).toEqual([YEAR_2026, YEAR_2025]));

    await user.click(screen.getByRole('button', { name: 'Next month (January 2026)' }));
    expect(shownMonths()).toEqual(['January']);
    // O voltar do navegador volta para a faixa anterior
    router.navigate(-1);
    expect(await screen.findByRole('heading', { level: 2, name: 'December 2025' })).toBeDefined();
  });

  it('moves by three months in the 3-month range, across the year', async () => {
    signedIn();
    const { requests } = mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1?range=3months');

    await findDay('Tuesday, March 10, 2026');
    await user.click(screen.getByRole('button', { name: /^Previous 3 months \(Oct\s–\sDec 2025\)$/ }));

    expect(shownMonths()).toEqual(['October', 'November', 'December']);
    expect(search(router)).toBe('?range=3months&month=2025-12');
    await waitFor(() => expect(markQueries(requests)).toEqual([YEAR_2026, YEAR_2025]));

    await user.click(screen.getByRole('button', { name: /^Previous 3 months \(Jul\s–\sSep 2025\)$/ }));
    expect(shownMonths()).toEqual(['July', 'August', 'September']);
    expect(search(router)).toBe('?range=3months&month=2025-09');

    await user.click(screen.getByRole('button', { name: /^Next 3 months \(Oct\s–\sDec 2025\)$/ }));
    await user.click(screen.getByRole('button', { name: /^Next 3 months \(Jan\s–\sMar 2026\)$/ }));
    expect(shownMonths()).toEqual(['January', 'February', 'March']);
    expect(screen.getByRole('button', { name: /^Next 3 months \(/ }).disabled).toBe(true);
    // Voltou a ter hoje na faixa
    expect(screen.getByRole('heading', { level: 2, name: 'Tuesday, March 10, 2026' })).toBeDefined();
  });

  it('moves by one year in the year range', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1?range=year&year=2024');

    await screen.findByRole('heading', { level: 2, name: '2024' });
    await user.click(screen.getByRole('button', { name: 'Next year (2025)' }));

    expect(await screen.findByRole('heading', { level: 2, name: '2025' })).toBeDefined();
    expect(shownMonths()).toHaveLength(12);
    expect(search(router)).toBe('?range=year&year=2025');
    expect(screen.getByRole('button', { name: 'Previous year (2024)' }).disabled).toBe(false);
  });

  it('keeps the chosen day visible when the range changes', async () => {
    signedIn();
    // Viewer: clicar só escolhe o dia
    mockHabitsApi({ habits: [habitFixture({ role: 'viewer' })] });
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1?year=2025&day=2025-12-20');

    await screen.findByRole('heading', { level: 2, name: 'Saturday, December 20, 2025' });
    await user.click(screen.getByRole('radio', { name: 'Month' }));

    expect(shownMonths()).toEqual(['December']);
    expect(dayButton('Saturday, December 20, 2025').dataset.selected).toBe('true');
    expect(search(router)).toBe('?day=2025-12-20&range=month&month=2025-12');

    await user.click(screen.getByRole('radio', { name: '3 months' }));

    // O mês do dia fica por último na janela
    expect(shownMonths()).toEqual(['October', 'November', 'December']);
    expect(dayButton('Saturday, December 20, 2025').dataset.selected).toBe('true');
    expect(screen.getByRole('heading', { level: 2, name: 'Saturday, December 20, 2025' })).toBeDefined();

    // Escolher outro dia não mexe na janela
    await user.click(dayButton('Monday, November 3, 2025'));
    expect(shownMonths()).toEqual(['October', 'November', 'December']);
    expect(search(router)).toBe('?day=2025-11-03&range=3months&month=2025-12');

    await user.click(screen.getByRole('radio', { name: 'Year' }));

    expect(screen.getByRole('heading', { level: 2, name: '2025' })).toBeDefined();
    expect(shownMonths()).toHaveLength(12);
    expect(dayButton('Monday, November 3, 2025').dataset.selected).toBe('true');
  });

  it('starts the new range at the first month on screen without a chosen day', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    renderApp('/habits/1?year=2024');

    await screen.findByRole('heading', { level: 2, name: '2024' });
    await user.click(screen.getByRole('radio', { name: '3 months' }));

    expect(shownMonths()).toEqual(['January', 'February', 'March']);
  });

  it('remembers the choice after a reload, in both tabs, and the URL wins', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    const first = renderApp('/habits/1');

    await findDay('Tuesday, March 10, 2026');
    await user.click(screen.getByRole('radio', { name: '3 months' }));
    expect(shownMonths()).toHaveLength(3);
    first.unmount();

    // Recarregar sem a faixa na URL: a escolha lembrada
    const second = renderApp('/habits/1');
    await findDay('Tuesday, March 10, 2026');
    expect(screen.getByRole('radio', { name: '3 months' }).checked).toBe(true);
    expect(shownMonths()).toEqual(['January', 'February', 'March']);
    second.unmount();

    const home = renderApp('/');
    await findDay('Tuesday, March 10, 2026');
    expect(shownMonths()).toEqual(['January', 'February', 'March']);
    home.unmount();

    // Um link com a faixa mostra a do link, sem trocar a lembrada
    renderApp('/?range=year');
    await findDay('Tuesday, March 10, 2026');
    expect(shownMonths()).toHaveLength(12);
    expect(window.localStorage.getItem('ethos:calendar-range')).toBe('3months');
  });

  it('keeps the keyboard inside the range', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    renderApp('/habits/1?range=3months&month=2026-01&day=2025-12-31');

    const lastDay = await findDay('Wednesday, December 31, 2025');
    // Uma parada de Tab na faixa: o dia escolhido
    expect(lastDay.tabIndex).toBe(0);
    expect(dayButton('Friday, January 2, 2026').tabIndex).toBe(-1);

    lastDay.focus();
    await user.keyboard('{ArrowRight}');
    expect(document.activeElement).toBe(dayButton('Thursday, January 1, 2026'));
    await user.keyboard('{End}');
    expect(document.activeElement).toBe(dayButton('Saturday, January 31, 2026'));
    await user.keyboard('{ArrowDown}{ArrowRight}');
    // O último dia da faixa segura o foco
    expect(document.activeElement).toBe(dayButton('Saturday, January 31, 2026'));

    dayButton('Saturday, November 1, 2025').focus();
    await user.keyboard('{ArrowUp}');
    expect(document.activeElement).toBe(dayButton('Saturday, November 1, 2025'));
    await user.keyboard('{ArrowLeft}');
    expect(document.activeElement).toBe(dayButton('Saturday, November 1, 2025'));
    await user.keyboard('{Home}');
    expect(document.activeElement).toBe(dayButton('Saturday, November 1, 2025'));
  });

  it('marks on both sides of the year and undoes a failed mark in its own year', async () => {
    signedIn();
    const { marks } = mockHabitsApi({ habits: [habitFixture()], marks: { 1: [] } });
    const failure = deferred();
    const bodies = [];
    server.use(
      http.post(api('/habits/:id/toggle'), async ({ request }) => {
        const body = await request.json();
        bodies.push(body);
        if (body.day_start.startsWith('2026-01-01')) return failure.promise;
        // A API falsa guarda a marcação: a nova busca do ano depois das escritas a encontra
        const mark = markFixture({ id: 9, marked_at: body.marked_at });
        marks[1].push(mark);
        return HttpResponse.json({ marked: true, mark });
      }),
    );
    const user = userEvent.setup();
    const { queryClient } = renderApp('/habits/1?range=3months&month=2026-01');

    const december = await findDay('Wednesday, December 31, 2025');
    await waitFor(() => expect(december.getAttribute('aria-label')).toMatch(/Not marked$/));
    // Clicar no dia só o escolhe; marca o botão do painel
    await user.click(december);
    await user.click(screen.getByRole('button', { name: 'Mark this day' }));
    await waitFor(() => expect(december.getAttribute('aria-label')).toMatch(/Marked$/));

    const january = dayButton('Thursday, January 1, 2026');
    await user.click(january);
    await user.click(screen.getByRole('button', { name: 'Mark this day' }));
    await waitFor(() => expect(january.getAttribute('aria-label')).toMatch(/Marked$/));
    failure.resolve(HttpResponse.json({ error: 'internal_error', field: null }, { status: 500 }));

    await waitFor(() => expect(january.getAttribute('aria-label')).toMatch(/Not marked$/));
    expect(december.getAttribute('aria-label')).toMatch(/Marked$/);
    expect(bodies.map((body) => body.day_start)).toEqual([
      '2025-12-31T03:00:00.000Z',
      '2026-01-01T03:00:00.000Z',
    ]);
    // Cada marcação no cache do ano do seu dia
    await waitFor(() => {
      expect(queryClient.getQueryData(markKeys.year(1, 2025, TIME_ZONE)).map((mark) => mark.id)).toEqual([9]);
    });
    expect(queryClient.getQueryData(markKeys.year(1, 2026, TIME_ZONE))).toEqual([]);
  });
});

describe('calendar range: home', () => {
  const COLORS = ['red', 'orange', 'amber', 'green', 'blue', 'violet'];

  /** Seis hábitos, todos marcados em 31 de dezembro de 2025; o primeiro também em 2 de janeiro. */
  function sixHabits() {
    const habits = COLORS.map((color, index) =>
      habitFixture({ id: index + 1, code: `H${index + 1}`, name: `Habit ${index + 1}`, color }),
    );
    const marks = Object.fromEntries(
      habits.map((habit) => [
        habit.id,
        [
          markFixture({ id: habit.id * 10, habit_id: habit.id, marked_at: '2025-12-31T15:00:00Z' }),
          ...(habit.id === 1
            ? [markFixture({ id: 1, habit_id: 1, marked_at: '2026-01-02T15:00:00Z' })]
            : []),
        ],
      ]),
    );
    return { habits, marks };
  }

  it('shows the dots of both years in the 3-month window', async () => {
    signedIn();
    const { requests } = mockHabitsApi(sixHabits());
    const { container, router } = renderApp('/?range=3months&month=2026-01');

    await waitFor(() => {
      expect(container.querySelectorAll('[data-day="2025-12-31"] [data-habit-color]')).toHaveLength(4);
    });
    const lastDay = dayButton('Wednesday, December 31, 2025');
    expect(lastDay.textContent).toContain('+2');
    expect(lastDay.getAttribute('aria-label')).toBe(
      'Wednesday, December 31, 2025. Marked: H1, H2, H3, H4, H5, H6',
    );
    expect(dayButton('Friday, January 2, 2026').getAttribute('aria-label')).toBe(
      'Friday, January 2, 2026. Marked: H1',
    );
    // Uma busca por hábito e ano na tela
    for (const habit of COLORS.keys()) {
      expect(markQueries(requests, habit + 1)).toHaveLength(2);
    }
    expect(router.state.location.pathname).toBe(`${BASENAME}/`);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows one month and marks a day from the panel', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    server.use(
      http.post(api('/habits/:id/toggle'), async ({ request }) => {
        const body = await request.json();
        return HttpResponse.json({ marked: true, mark: markFixture({ id: 9, marked_at: body.marked_at }) });
      }),
    );
    const user = userEvent.setup();
    const { container } = renderApp('/?range=month&month=2025-12');

    await user.click(await findDay('Wednesday, December 24, 2025'));
    const panel = screen.getByRole('region', { name: 'Wednesday, December 24, 2025' });
    await user.click(await within(panel).findByRole('button', { name: 'Mark RUN' }));

    await waitFor(() => {
      expect(dayButton('Wednesday, December 24, 2025').getAttribute('aria-label')).toBe(
        'Wednesday, December 24, 2025. Selected. Marked: RUN',
      );
    });
    expect(shownMonths()).toEqual(['December']);
    expect(await axe(container)).toHaveNoViolations();
  });
});
