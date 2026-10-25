import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { axe } from '../test/axe';
import { habitFixture, markFixture, mockHabitsApi } from '../test/habits';
import { meFixture, renderApp } from '../test/render';
import { api, server } from '../test/server';

// Visão do calendário (grade ou colunas) nas duas abas. O ano inteiro no jsdom (com axe) é pesado:
// folga para o CI, como nos testes das telas do calendário
vi.setConfig({ testTimeout: 20_000 });
configure({ asyncUtilTimeout: 5_000 });

// "Agora": terça, 10 de março de 2026, 12:00 em São Paulo (UTC-3)
const NOW = new Date('2026-03-10T15:00:00Z');

function signedIn() {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
}

function calendarGroup() {
  return screen.getByRole('group', { name: /^Calendar for / });
}

/**
 * Cada mês na tela: `{name, days}`, com o nome completo (nas colunas, o do leitor de tela; o visível
 * é abreviado) e os dias ("AAAA-MM-DD") do mês, na ordem.
 */
function shownMonths() {
  return [...calendarGroup().querySelectorAll('section')].map((section) => ({
    name: (section.querySelector('h3 .visually-hidden') ?? section.querySelector('h3')).textContent,
    days: [...section.querySelectorAll('[data-day]')].map((day) => day.dataset.day),
  }));
}

/** Botão do dia, pelo começo do aria-label ("Wednesday, March 4, 2026"). */
function dayButton(date) {
  return screen.getByRole('button', { name: new RegExp(`^${date}\\.`) });
}

function findDay(date) {
  return screen.findByRole('button', { name: new RegExp(`^${date}\\.`) });
}

function query(router) {
  return new URLSearchParams(router.state.location.search);
}

function dayPanelTitle(date) {
  return screen.getByRole('heading', { level: 2, name: date });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('calendar view: habit tab', () => {
  it('shows the grid by default and every month in its own column', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    const { container, router } = renderApp('/habits/1?year=2024');

    await screen.findByRole('heading', { level: 2, name: '2024' });
    expect(screen.getByRole('radio', { name: 'Grid' }).checked).toBe(true);
    expect(calendarGroup().dataset.view).toBe('grid');
    // A grade tem o cabeçalho dos dias da semana; os dias não repetem o nome
    expect(dayButton('Monday, January 1, 2024').textContent).toBe('1');

    await user.click(screen.getByRole('radio', { name: 'Columns' }));

    expect(screen.getByRole('radio', { name: 'Columns' }).checked).toBe(true);
    expect(calendarGroup().dataset.view).toBe('columns');
    const months = shownMonths();
    // 2024 é bissexto: fevereiro com 29 dias
    expect(months.map((month) => month.days.length)).toEqual([
      31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
    ]);
    expect(months.map((month) => month.name)).toEqual([
      'January',
      'February',
      'March',
      'April',
      'May',
      'June',
      'July',
      'August',
      'September',
      'October',
      'November',
      'December',
    ]);
    months.forEach(({ days }, index) => {
      const month = String(index + 1).padStart(2, '0');
      expect(days[0]).toBe(`2024-${month}-01`);
      // De cima para baixo, em ordem
      expect(days).toEqual([...days].sort());
      expect(days.every((day) => day.startsWith(`2024-${month}-`))).toBe(true);
    });
    expect(container.querySelectorAll('[data-day]')).toHaveLength(366);
    // Nas colunas, o nome do mês aparece abreviado (a coluna tem a largura de um dia), e o leitor
    // de tela ouve o nome completo
    expect(
      [...calendarGroup().querySelectorAll('h3 [aria-hidden="true"]')].map((name) => name.textContent),
    ).toEqual(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']);
    expect(screen.getByRole('region', { name: 'September' })).toBeDefined();
    // Sem o dia da semana nas colunas, como na grade: só o número; o aria-label continua com a
    // data completa. Uma linha antes de cada domingo (1º de janeiro de 2024 foi uma segunda)
    const newYear = dayButton('Monday, January 1, 2024');
    expect(newYear.textContent).toBe('1');
    expect(newYear.getAttribute('aria-label')).toBe('Monday, January 1, 2024. Not marked');
    expect(newYear.dataset.weekStart).toBeUndefined();
    expect(dayButton('Sunday, January 7, 2024').dataset.weekStart).toBe('true');
    expect(dayButton('Saturday, January 6, 2024').dataset.weekStart).toBeUndefined();

    expect(query(router).get('view')).toBe('columns');
    expect(query(router).get('range')).toBe('year');
    expect(query(router).get('year')).toBe('2024');
    expect(window.localStorage.getItem('ethos:calendar-view')).toBe('columns');
    // A visão não mexe no tipo da faixa lembrado
    expect(window.localStorage.getItem('ethos:calendar-range')).toBeNull();
    expect(await axe(container)).toHaveNoViolations();

    await user.click(screen.getByRole('radio', { name: 'Grid' }));
    expect(calendarGroup().dataset.view).toBe('grid');
    expect(query(router).get('view')).toBe('grid');
    expect(window.localStorage.getItem('ethos:calendar-view')).toBe('grid');
  });

  it('draws the month and the 3-month ranges in columns, with the future disabled', async () => {
    signedIn();
    mockHabitsApi({
      habits: [habitFixture()],
      marks: { 1: [markFixture({ id: 1, marked_at: '2026-03-02T15:00:00Z' })] },
    });
    const user = userEvent.setup();
    const { container, router } = renderApp('/habits/1?range=month&view=columns');

    const marked = await findDay('Monday, March 2, 2026');
    await waitFor(() => expect(marked.getAttribute('aria-label')).toMatch(/Marked$/));
    expect(marked.dataset.marked).toBe('true');
    expect(marked.dataset.habitColor).toBe('teal');
    expect(shownMonths()).toEqual([
      { name: 'March', days: Array.from({ length: 31 }, (_, i) => `2026-03-${String(i + 1).padStart(2, '0')}`) },
    ]);
    // Depois de hoje (10 de março), desabilitados
    expect(container.querySelectorAll('[aria-disabled="true"]')).toHaveLength(21);
    expect(dayButton('Wednesday, March 11, 2026').getAttribute('aria-disabled')).toBe('true');
    expect(dayButton('Tuesday, March 10, 2026').getAttribute('aria-current')).toBe('date');
    expect(await axe(container)).toHaveNoViolations();

    await user.click(screen.getByRole('radio', { name: '3 months' }));

    expect(calendarGroup().dataset.view).toBe('columns');
    // A janela de 3 meses termina no mês escolhido
    expect(shownMonths().map((month) => [month.name, month.days.length])).toEqual([
      ['January', 31],
      ['February', 28],
      ['March', 31],
    ]);
    expect(container.querySelectorAll('[aria-disabled="true"]')).toHaveLength(21);
    expect(query(router).get('view')).toBe('columns');

    // Anterior e próximo mantêm a visão
    await user.click(screen.getByRole('button', { name: /^Previous 3 months \(/ }));
    expect(shownMonths().map((month) => [month.name, month.days.length])).toEqual([
      ['October', 31],
      ['November', 30],
      ['December', 31],
    ]);
    expect(screen.getByRole('heading', { level: 2, name: /^Oct\s–\sDec 2025$/ })).toBeDefined();
    await user.click(screen.getByRole('button', { name: /^Next 3 months \(/ }));
    expect(shownMonths().map((month) => month.name)).toEqual(['January', 'February', 'March']);
    expect(calendarGroup().dataset.view).toBe('columns');
    expect(query(router).get('view')).toBe('columns');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('keeps the range and the chosen day when the view changes', async () => {
    signedIn();
    // Viewer: clicar só escolhe o dia
    mockHabitsApi({ habits: [habitFixture({ role: 'viewer' })] });
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1?range=month&month=2025-12&day=2025-12-20');

    await findDay('Saturday, December 20, 2025');
    expect(dayPanelTitle('Saturday, December 20, 2025')).toBeDefined();

    await user.click(screen.getByRole('radio', { name: 'Columns' }));

    expect(shownMonths().map((month) => month.name)).toEqual(['December']);
    expect(dayButton('Saturday, December 20, 2025').dataset.selected).toBe('true');
    expect(dayButton('Saturday, December 20, 2025').tabIndex).toBe(0);
    expect(dayPanelTitle('Saturday, December 20, 2025')).toBeDefined();
    expect(screen.getByRole('heading', { level: 2, name: 'December 2025' })).toBeDefined();
    expect(screen.getByRole('radio', { name: 'Month' }).checked).toBe(true);
    expect(Object.fromEntries(query(router))).toEqual({
      range: 'month',
      month: '2025-12',
      day: '2025-12-20',
      view: 'columns',
    });

    // Escolher outro dia nas colunas e voltar para a grade
    await user.click(dayButton('Monday, December 1, 2025'));
    await user.click(screen.getByRole('radio', { name: 'Grid' }));

    expect(calendarGroup().dataset.view).toBe('grid');
    expect(shownMonths().map((month) => month.name)).toEqual(['December']);
    expect(dayButton('Monday, December 1, 2025').dataset.selected).toBe('true');
    expect(dayPanelTitle('Monday, December 1, 2025')).toBeDefined();
    expect(query(router).get('day')).toBe('2025-12-01');

    // O voltar do navegador volta para as colunas, com o mesmo dia
    router.navigate(-1);
    await waitFor(() => expect(calendarGroup().dataset.view).toBe('columns'));
    expect(dayButton('Monday, December 1, 2025').dataset.selected).toBe('true');
  });

  it('keeps today chosen and implicit, and the remembered range, when the view changes', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    window.localStorage.setItem('ethos:calendar-range', '3months');
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1');

    await findDay('Tuesday, March 10, 2026');
    await user.click(screen.getByRole('radio', { name: 'Columns' }));

    expect(shownMonths().map((month) => month.name)).toEqual(['January', 'February', 'March']);
    expect(dayPanelTitle('Tuesday, March 10, 2026')).toBeDefined();
    expect(dayButton('Tuesday, March 10, 2026').dataset.selected).toBe('true');
    // A faixa da tela fica explícita na URL; hoje continua implícito
    expect(Object.fromEntries(query(router))).toEqual({
      range: '3months',
      month: '2026-03',
      view: 'columns',
    });
  });

  it('remembers the view in both tabs after a reload, and the URL wins', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    const first = renderApp('/habits/1?range=month');

    await findDay('Tuesday, March 10, 2026');
    await user.click(screen.getByRole('radio', { name: 'Columns' }));
    expect(calendarGroup().dataset.view).toBe('columns');
    first.unmount();

    const second = renderApp('/habits/1');
    await findDay('Tuesday, March 10, 2026');
    expect(screen.getByRole('radio', { name: 'Columns' }).checked).toBe(true);
    expect(calendarGroup().dataset.view).toBe('columns');
    second.unmount();

    const home = renderApp('/');
    await findDay('Tuesday, March 10, 2026');
    expect(calendarGroup().dataset.view).toBe('columns');
    home.unmount();

    // Um link com a visão mostra a do link, sem trocar a lembrada; valor inválido é ignorado
    const link = renderApp('/?view=grid');
    await findDay('Tuesday, March 10, 2026');
    expect(calendarGroup().dataset.view).toBe('grid');
    expect(screen.getByRole('radio', { name: 'Grid' }).checked).toBe(true);
    expect(window.localStorage.getItem('ethos:calendar-view')).toBe('columns');
    link.unmount();

    renderApp('/habits/1?view=table');
    await findDay('Tuesday, March 10, 2026');
    expect(calendarGroup().dataset.view).toBe('columns');
  });

  it('scrolls the columns, not the page, to the chosen day', async () => {
    // O jsdom não tem layout: colunas de 90px a cada 100px, num calendário de 300px de largura
    const restore = [];
    const fake = (name, get) => {
      const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, name);
      Object.defineProperty(HTMLElement.prototype, name, { configurable: true, get });
      // Sem descritor próprio (clientWidth vem do Element), apagar devolve o herdado
      restore.push(() => {
        if (original) Object.defineProperty(HTMLElement.prototype, name, original);
        else delete HTMLElement.prototype[name];
      });
    };
    fake('offsetLeft', function offsetLeft() {
      return this.tagName === 'SECTION' ? [...this.parentElement.children].indexOf(this) * 100 : 0;
    });
    fake('offsetWidth', function offsetWidth() {
      return this.tagName === 'SECTION' ? 90 : 0;
    });
    fake('clientWidth', function clientWidth() {
      return this.dataset?.view === 'columns' ? 300 : 0;
    });
    try {
      signedIn();
      mockHabitsApi({ habits: [habitFixture({ role: 'viewer' })] });
      const user = userEvent.setup();
      renderApp('/habits/1?year=2025&day=2025-06-15&view=columns');

      await findDay('Sunday, June 15, 2025');
      // Junho (a 6ª coluna, de 500 a 590px) encosta na direita da rolagem
      expect(calendarGroup().scrollLeft).toBe(590 - 300);

      // Outro ano, sem dia escolhido: volta para o começo
      await user.click(screen.getByRole('button', { name: 'Previous year (2024)' }));
      await screen.findByRole('heading', { level: 2, name: '2024' });
      expect(calendarGroup().scrollLeft).toBe(0);
    } finally {
      restore.forEach((undo) => undo());
    }
  });

  it('moves the keyboard by day down the column and by month across columns', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    // Dezembro, janeiro e fevereiro: a janela termina no mês da URL
    renderApp('/habits/1?range=3months&month=2026-02&day=2025-12-31&view=columns');

    const lastDay = await findDay('Wednesday, December 31, 2025');
    // Com dois anos na tela, o ano vai embaixo do nome abreviado, e o rótulo tem os dois
    expect(shownMonths().map((month) => month.name)).toEqual([
      'December 2025',
      'January 2026',
      'February 2026',
    ]);
    expect(
      [...calendarGroup().querySelectorAll('h3')].map((name) =>
        [...name.querySelectorAll('[aria-hidden="true"]')].map((part) => part.textContent),
      ),
    ).toEqual([
      ['Dec', '2025'],
      ['Jan', '2026'],
      ['Feb', '2026'],
    ]);
    // Uma parada de Tab no calendário: o dia escolhido
    expect(lastDay.tabIndex).toBe(0);
    expect(calendarGroup().querySelectorAll('[tabindex="0"]')).toHaveLength(1);

    lastDay.focus();
    await user.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(dayButton('Thursday, January 1, 2026'));
    expect(document.activeElement.tabIndex).toBe(0);
    expect(lastDay.tabIndex).toBe(-1);
    await user.keyboard('{ArrowUp}');
    expect(document.activeElement).toBe(lastDay);
    // Para os lados: o mesmo dia na coluna vizinha, ou o último de um mês mais curto
    await user.keyboard('{ArrowRight}');
    expect(document.activeElement).toBe(dayButton('Saturday, January 31, 2026'));
    await user.keyboard('{ArrowRight}');
    expect(document.activeElement).toBe(dayButton('Saturday, February 28, 2026'));
    await user.keyboard('{ArrowLeft}');
    expect(document.activeElement).toBe(dayButton('Wednesday, January 28, 2026'));
    await user.keyboard('{Home}');
    expect(document.activeElement).toBe(dayButton('Thursday, January 1, 2026'));
    await user.keyboard('{End}');
    expect(document.activeElement).toBe(dayButton('Saturday, January 31, 2026'));

    // A faixa segura o foco nas pontas
    dayButton('Tuesday, February 10, 2026').focus();
    await user.keyboard('{ArrowRight}');
    expect(document.activeElement).toBe(dayButton('Saturday, February 28, 2026'));
    await user.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(dayButton('Saturday, February 28, 2026'));
    dayButton('Friday, December 5, 2025').focus();
    await user.keyboard('{ArrowLeft}');
    expect(document.activeElement).toBe(dayButton('Monday, December 1, 2025'));
    await user.keyboard('{ArrowUp}');
    expect(document.activeElement).toBe(dayButton('Monday, December 1, 2025'));
  });

  it('marks a day in columns and shows the count of a multi-mark habit', async () => {
    signedIn();
    mockHabitsApi({
      habits: [habitFixture({ id: 1 }), habitFixture({ id: 2, code: 'WTR', multi_mark: true })],
      marks: {
        1: [],
        2: [
          markFixture({ id: 1, habit_id: 2, marked_at: '2026-03-03T12:00:00Z' }),
          markFixture({ id: 2, habit_id: 2, marked_at: '2026-03-03T15:00:00Z' }),
          markFixture({ id: 3, habit_id: 2, marked_at: '2026-03-03T18:00:00Z' }),
        ],
      },
    });
    server.use(
      http.post(api('/habits/:id/toggle'), async ({ request }) => {
        const body = await request.json();
        return HttpResponse.json({ marked: true, mark: markFixture({ id: 9, marked_at: body.marked_at }) });
      }),
    );
    const user = userEvent.setup();
    const toggle = renderApp('/habits/1?range=month&view=columns');

    const day = await findDay('Wednesday, March 4, 2026');
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Not marked$/));
    await user.click(day);
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Marked$/));
    expect(day.dataset.marked).toBe('true');
    // Dia futuro não marca
    await user.click(dayButton('Thursday, March 12, 2026'));
    expect(dayButton('Thursday, March 12, 2026').getAttribute('aria-label')).toBe(
      'Thursday, March 12, 2026. Future day, cannot be marked',
    );
    expect(await axe(toggle.container)).toHaveNoViolations();
    toggle.unmount();

    const multi = renderApp('/habits/2?range=month&view=columns');
    const counted = await findDay('Tuesday, March 3, 2026');
    await waitFor(() => expect(counted.getAttribute('aria-label')).toBe('Tuesday, March 3, 2026. 3 marks'));
    // O número do dia e o contador, sem o dia da semana
    expect(counted.textContent).toBe('33');
    expect(await axe(multi.container)).toHaveNoViolations();
  });
});

describe('calendar view: home', () => {
  const COLORS = ['red', 'orange', 'amber', 'green', 'blue', 'violet'];

  /** Seis hábitos, todos marcados em 2 de março de 2026. */
  function sixHabits() {
    const habits = COLORS.map((color, index) =>
      habitFixture({ id: index + 1, code: `H${index + 1}`, name: `Habit ${index + 1}`, color }),
    );
    const marks = Object.fromEntries(
      habits.map((habit) => [
        habit.id,
        [markFixture({ id: habit.id * 10, habit_id: habit.id, marked_at: '2026-03-02T15:00:00Z' })],
      ]),
    );
    return { habits, marks };
  }

  it('shows the dots, "+N" and the habits of each day in columns', async () => {
    signedIn();
    mockHabitsApi(sixHabits());
    const user = userEvent.setup();
    const { container, router } = renderApp('/?range=3months');

    await findDay('Tuesday, March 10, 2026');
    await user.click(screen.getByRole('radio', { name: 'Columns' }));

    await waitFor(() => {
      expect(container.querySelectorAll('[data-day="2026-03-02"] [data-habit-color]')).toHaveLength(4);
    });
    const marked = dayButton('Monday, March 2, 2026');
    expect(marked.textContent).toContain('+2');
    expect(marked.textContent).toContain('H1, H2, H3, H4, H5, H6');
    expect(marked.getAttribute('aria-label')).toBe('Monday, March 2, 2026. Marked: H1, H2, H3, H4, H5, H6');
    expect(dayButton('Sunday, March 1, 2026').getAttribute('aria-label')).toBe(
      'Sunday, March 1, 2026. Nothing marked',
    );
    expect(shownMonths().map((month) => [month.name, month.days.length])).toEqual([
      ['January', 31],
      ['February', 28],
      ['March', 31],
    ]);
    expect(query(router).get('view')).toBe('columns');
    expect(await axe(container)).toHaveNoViolations();

    // Escolher um dia abre o painel, como na grade
    await user.click(marked);
    const panel = screen.getByRole('region', { name: 'Monday, March 2, 2026' });
    expect(within(panel).getAllByRole('listitem')).toHaveLength(6);
    expect(query(router).get('day')).toBe('2026-03-02');
    expect(query(router).get('view')).toBe('columns');
  });
});
