import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { BASENAME } from '../../paths';
import { axe } from '../../test/axe';
import { deferred, habitFixture, markFixture, mockHabitsApi } from '../../test/habits';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

// Um ano inteiro de botões no jsdom (com axe) é pesado: folga para o CI,
vi.setConfig({ testTimeout: 15_000 });
// e o primeiro desenho do ano pode passar de 1 s (o padrão do findBy/waitFor) com os testes em paralelo
configure({ asyncUtilTimeout: 5_000 });

// "Agora" de todos os testes: terça, 10 de março de 2026, 12:00 em São Paulo (UTC-3, sem horário
// de verão)
const NOW = new Date('2026-03-10T15:00:00Z');

function signedIn(overrides = {}) {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture(overrides))));
}

/** Botão do dia no calendário, pelo começo do aria-label ("Wednesday, March 4, 2026"). */
function dayButton(date) {
  return screen.getByRole('button', { name: new RegExp(`^${date}\\.`) });
}

async function findDay(date) {
  return screen.findByRole('button', { name: new RegExp(`^${date}\\.`) });
}

/** Escolhe o dia no calendário (clique) e espera o painel dele. */
async function selectDay(user, date) {
  await user.click(await findDay(date));
  return screen.findByRole('heading', { level: 2, name: date });
}

/** Registra o POST /habits/:id/toggle e devolve os corpos recebidos. */
function toggleApi(respond) {
  const bodies = [];
  server.use(
    http.post(api('/habits/:id/toggle'), async ({ request }) => {
      const body = await request.json();
      bodies.push(body);
      return respond(body);
    }),
  );
  return bodies;
}

function created(body, id = 500) {
  return HttpResponse.json({ marked: true, mark: markFixture({ id, marked_at: body.marked_at }) });
}

beforeEach(() => {
  // Só o relógio do Date: os timers continuam de verdade (MSW e user-event usam)
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('habit calendar: custom colour (ETH-49)', () => {
  it.each([
    ['#fde047', 'dark'],
    ['#1e3a8a', 'light'],
  ])('paints the marked days with %s and the number in %s text', async (color, tone) => {
    signedIn();
    mockHabitsApi({
      habits: [habitFixture({ color })],
      marks: { 1: [markFixture({ marked_at: '2026-03-02T15:00:00Z' })] },
    });
    const { container } = renderApp('/habits/1');

    const day = await findDay('Monday, March 2, 2026');
    await waitFor(() => expect(day.dataset.marked).toBe('true'));
    for (const element of container.querySelectorAll('[data-day]')) {
      expect(element.dataset.habitColor).toBe('custom');
      expect(element.style.getPropertyValue('--habit-color')).toBe(color);
      expect(element.dataset.habitText).toBe(tone);
    }
    // O cabeçalho da aba também
    const header = screen.getByRole('heading', { level: 1, name: 'RUN' });
    expect(header.querySelector('[data-habit-color]').style.getPropertyValue('--habit-color')).toBe(color);
  });
});

describe('habit calendar: toggle', () => {
  it('sends the start and end of the selected local day from the panel', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const bodies = toggleApi((body) => created(body));
    const user = userEvent.setup();
    renderApp('/habits/1');

    await selectDay(user, 'Wednesday, March 4, 2026');
    // Escolher o dia não marca
    expect(bodies).toEqual([]);
    await user.click(screen.getByRole('button', { name: 'Mark this day' }));

    expect(bodies).toEqual([
      {
        day_start: '2026-03-04T03:00:00.000Z',
        day_end: '2026-03-05T03:00:00.000Z',
        // Dia passado: 12:00 local
        marked_at: '2026-03-04T15:00:00.000Z',
      },
    ]);
    await waitFor(() => {
      expect(dayButton('Wednesday, March 4, 2026').getAttribute('aria-label')).toMatch(/Marked$/);
    });
    expect(screen.getByRole('button', { name: 'Unmark this day' })).toBeDefined();
  });

  it('marks today with the current instant', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const bodies = toggleApi((body) => created(body));
    const user = userEvent.setup();
    renderApp('/habits/1');

    // Sem dia na URL, o painel abre em hoje
    await screen.findByRole('heading', { level: 2, name: 'Tuesday, March 10, 2026' });
    await user.click(await screen.findByRole('button', { name: 'Mark this day' }));

    expect(bodies[0]).toEqual({
      day_start: '2026-03-10T03:00:00.000Z',
      day_end: '2026-03-11T03:00:00.000Z',
      marked_at: NOW.toISOString(),
    });
  });

  it('uses the 23-hour day when daylight saving time starts', async () => {
    vi.setSystemTime(new Date('2026-03-20T15:00:00Z'));
    signedIn({ timezone: 'America/New_York' });
    mockHabitsApi({ habits: [habitFixture()] });
    const bodies = toggleApi((body) => created(body));
    const user = userEvent.setup();
    renderApp('/habits/1');

    await selectDay(user, 'Sunday, March 8, 2026');
    await user.click(screen.getByRole('button', { name: 'Mark this day' }));

    expect(bodies[0]).toEqual({
      day_start: '2026-03-08T05:00:00.000Z',
      day_end: '2026-03-09T04:00:00.000Z',
      marked_at: '2026-03-08T16:00:00.000Z',
    });
  });

  it('unmarks a marked day', async () => {
    signedIn();
    mockHabitsApi({
      habits: [habitFixture()],
      marks: { 1: [markFixture({ marked_at: '2026-03-02T15:00:00Z' })] },
    });
    const bodies = toggleApi(() => HttpResponse.json({ marked: false, mark: null }));
    const user = userEvent.setup();
    renderApp('/habits/1?day=2026-03-02');

    const day = await findDay('Monday, March 2, 2026');
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Marked$/));
    // O dia escolhido diz que está escolhido, antes do estado
    expect(day.getAttribute('aria-label')).toBe('Monday, March 2, 2026. Selected. Marked');
    await user.click(screen.getByRole('button', { name: 'Unmark this day' }));

    // Sem observação, duração nem custo: desmarca sem perguntar
    expect(bodies).toHaveLength(1);
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Not marked$/));
    expect(screen.getByRole('button', { name: 'Mark this day' })).toBeDefined();
  });

  it('shows the mark at once and undoes it when the API fails', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const response = deferred();
    toggleApi(() => response.promise);
    const user = userEvent.setup();
    renderApp('/habits/1');

    await selectDay(user, 'Wednesday, March 4, 2026');
    const day = dayButton('Wednesday, March 4, 2026');
    await user.click(screen.getByRole('button', { name: 'Mark this day' }));

    // Otimista: marcado antes da resposta
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Marked$/));
    expect(day.dataset.pending).toBe('true');

    response.resolve(HttpResponse.json({ error: 'internal_error', field: null }, { status: 500 }));

    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Not marked$/));
    expect(screen.getByRole('alert').textContent).toContain('Something went wrong on our side');
  });

  it('cannot select a future day', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const bodies = toggleApi((body) => created(body));
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1');

    const future = await findDay('Wednesday, March 11, 2026');
    await user.click(future);

    expect(future.getAttribute('aria-disabled')).toBe('true');
    expect(future.getAttribute('aria-label')).toBe(
      'Wednesday, March 11, 2026. Future day, cannot be marked',
    );
    expect(router.state.location.search).toBe('');
    expect(bodies).toEqual([]);
    // O ano atual não tem "próximo"
    expect(screen.getByRole('button', { name: 'Next year (2027)' }).disabled).toBe(true);
  });

  it('marks days before the habit was created', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture({ created_at: '2026-03-01T12:00:00Z' })] });
    const bodies = toggleApi((body) => created(body));
    const user = userEvent.setup();
    renderApp('/habits/1');

    await selectDay(user, 'Thursday, January 15, 2026');
    await user.click(screen.getByRole('button', { name: 'Mark this day' }));

    expect(bodies).toHaveLength(1);
  });

  it('only selects a marked day on click, Enter and Space, and the mark stays (ETH-54)', async () => {
    signedIn();
    mockHabitsApi({
      habits: [habitFixture({ notes_enabled: true })],
      marks: {
        1: [
          markFixture({ id: 1, marked_at: '2026-03-02T15:00:00Z', note: 'leg day' }),
          markFixture({ id: 2, marked_at: '2026-03-09T15:00:00Z' }),
        ],
      },
    });
    const bodies = toggleApi((body) => created(body));
    const user = userEvent.setup();
    const { router, container } = renderApp('/habits/1');

    const marked = await findDay('Monday, March 2, 2026');
    await waitFor(() => expect(marked.getAttribute('aria-label')).toMatch(/Marked$/));
    await user.click(marked);

    expect(screen.getByRole('heading', { level: 2, name: 'Monday, March 2, 2026' })).toBeDefined();
    expect(new URLSearchParams(router.state.location.search).get('day')).toBe('2026-03-02');
    expect(marked.getAttribute('aria-label')).toBe('Monday, March 2, 2026. Selected. Marked');
    expect(screen.getByText('leg day')).toBeDefined();
    // O foco fica no dia: as setas continuam andando
    expect(document.activeElement).toBe(marked);

    // Teclado: Enter e Espaço só escolhem, nos dias marcados e nos não marcados
    await user.keyboard('{ArrowDown}');
    const next = dayButton('Monday, March 9, 2026');
    expect(document.activeElement).toBe(next);
    await user.keyboard('{Enter}');
    expect(screen.getByRole('heading', { level: 2, name: 'Monday, March 9, 2026' })).toBeDefined();
    expect(next.getAttribute('aria-label')).toBe('Monday, March 9, 2026. Selected. Marked');
    await user.keyboard(' ');
    await user.keyboard('{ArrowLeft}{Enter}');
    expect(screen.getByRole('heading', { level: 2, name: 'Sunday, March 8, 2026' })).toBeDefined();
    expect(dayButton('Sunday, March 8, 2026').getAttribute('aria-label')).toBe(
      'Sunday, March 8, 2026. Selected. Not marked',
    );

    expect(bodies).toEqual([]);
    expect(marked.dataset.marked).toBe('true');
    expect(next.dataset.marked).toBe('true');
    expect(container.querySelectorAll('[data-marked]')).toHaveLength(2);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('asks before unmarking a day with a note, and undoes a failed unmark', async () => {
    signedIn();
    const mark = markFixture({ id: 7, marked_at: '2026-03-02T15:00:00Z', note: 'leg day' });
    mockHabitsApi({ habits: [habitFixture({ notes_enabled: true })], marks: { 1: [mark] } });
    const response = deferred();
    const bodies = toggleApi(() => response.promise);
    const user = userEvent.setup();
    const { container } = renderApp('/habits/1?day=2026-03-02');

    const day = await findDay('Monday, March 2, 2026');
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Marked$/));
    const unmark = screen.getByRole('button', { name: 'Unmark this day' });
    await user.click(unmark);

    // Nada sai antes de confirmar; o foco vai para "Cancelar"
    const confirm = screen.getByRole('group', {
      name: 'Unmarking also deletes the details of this day (note, duration or cost).',
    });
    const cancel = within(confirm).getByRole('button', { name: 'Cancel' });
    expect(document.activeElement).toBe(cancel);
    expect(bodies).toEqual([]);
    expect(await axe(container)).toHaveNoViolations();

    // Cancelar (pelo botão e pelo Esc) mantém tudo e devolve o foco ao botão de desmarcar
    await user.click(cancel);
    expect(screen.queryByRole('group', { name: /^Unmarking also deletes/ })).toBeNull();
    expect(document.activeElement).toBe(unmark);
    await user.click(unmark);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('group', { name: /^Unmarking also deletes/ })).toBeNull();
    expect(document.activeElement).toBe(unmark);
    expect(bodies).toEqual([]);
    expect(screen.getByText('leg day')).toBeDefined();

    // Confirmar desmarca na hora; a API falha e a marcação volta, com a observação
    await user.click(unmark);
    await user.click(screen.getByRole('button', { name: 'Unmark anyway' }));
    expect(bodies).toHaveLength(1);
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Not marked$/));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Mark this day' }));

    response.resolve(HttpResponse.json({ error: 'internal_error', field: null }, { status: 500 }));

    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Marked$/));
    expect(screen.getByText('leg day')).toBeDefined();
    expect(screen.getByRole('alert').textContent).toContain('Something went wrong on our side');
  });

  it('asks only when the duration or the cost differ from the defaults of the habit', async () => {
    signedIn();
    const habit = habitFixture({
      duration_enabled: true,
      duration_minutes: 30,
      cost_enabled: true,
      cost_level: 'mark',
      cost_cents: 800,
    });
    mockHabitsApi({
      habits: [habit],
      marks: {
        1: [
          markFixture({ id: 1, marked_at: '2026-03-02T15:00:00Z', duration_minutes: 30, cost_cents: 800 }),
          markFixture({ id: 2, marked_at: '2026-03-03T15:00:00Z', duration_minutes: 45, cost_cents: 800 }),
          markFixture({ id: 3, marked_at: '2026-03-04T15:00:00Z', duration_minutes: 30, cost_cents: 1250 }),
        ],
      },
    });
    const bodies = toggleApi(() => HttpResponse.json({ marked: false, mark: null }));
    const user = userEvent.setup();
    renderApp('/habits/1?day=2026-03-03');

    // Duração diferente da padrão: pergunta
    await user.click(await screen.findByRole('button', { name: 'Unmark this day' }));
    expect(screen.getByRole('button', { name: 'Unmark anyway' })).toBeDefined();
    // Trocar de dia esquece a confirmação; custo diferente do padrão também pergunta
    await selectDay(user, 'Wednesday, March 4, 2026');
    expect(screen.queryByRole('button', { name: 'Unmark anyway' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Unmark this day' }));
    expect(screen.getByRole('button', { name: 'Unmark anyway' })).toBeDefined();
    expect(bodies).toEqual([]);
    // Sair e voltar ao dia não traz a confirmação de volta, nem tira o foco do calendário
    await selectDay(user, 'Tuesday, March 3, 2026');
    await selectDay(user, 'Wednesday, March 4, 2026');
    expect(screen.queryByRole('button', { name: 'Unmark anyway' })).toBeNull();
    expect(document.activeElement).toBe(dayButton('Wednesday, March 4, 2026'));

    // Só os padrões do hábito (voltam ao marcar de novo): desmarca direto
    await selectDay(user, 'Monday, March 2, 2026');
    await user.click(screen.getByRole('button', { name: 'Unmark this day' }));
    expect(screen.queryByRole('button', { name: 'Unmark anyway' })).toBeNull();
    expect(bodies).toHaveLength(1);
  });

  it('moves with the arrow keys from the tab stop', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    renderApp('/habits/1');

    const today = await findDay('Tuesday, March 10, 2026');
    // Uma parada de Tab no ano: hoje
    expect(today.tabIndex).toBe(0);
    expect(dayButton('Monday, March 9, 2026').tabIndex).toBe(-1);

    today.focus();
    await user.keyboard('{ArrowLeft}');
    const yesterday = dayButton('Monday, March 9, 2026');
    expect(document.activeElement).toBe(yesterday);
    expect(yesterday.tabIndex).toBe(0);

    await user.keyboard('{ArrowUp}');
    expect(document.activeElement).toBe(dayButton('Monday, March 2, 2026'));
    await user.keyboard('{Home}');
    expect(document.activeElement).toBe(dayButton('Sunday, March 1, 2026'));
    await user.keyboard('{End}');
    expect(document.activeElement).toBe(dayButton('Tuesday, March 31, 2026'));
  });

  it('draws the weeks from Sunday to Saturday and moves in that order', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    const { container } = renderApp('/habits/1');

    // Março de 2026 começa num domingo: o dia 1 abre a grade, na primeira coluna
    const march = await screen.findByRole('region', { name: 'March' });
    const header = [...march.querySelectorAll('div[aria-hidden="true"] > span')];
    expect(header.map((day) => day.textContent).join('')).toBe('SMTWTFS');
    const first = within(march).getByRole('button', { name: /^Sunday, March 1, 2026\./ });
    expect(first.previousElementSibling).toBeNull();
    // Agosto começa num sábado: 6 casas vazias antes do dia 1, que fica na última coluna
    const august = screen.getByRole('region', { name: 'August' });
    const firstOfAugust = within(august).getByRole('button', { name: /^Saturday, August 1, 2026\./ });
    expect(firstOfAugust.previousElementSibling.dataset.offset).toBe('6');

    // Setas: do sábado para o domingo seguinte (começo da linha de baixo) e uma semana para cima
    dayButton('Saturday, March 7, 2026').focus();
    await user.keyboard('{ArrowRight}');
    expect(document.activeElement).toBe(dayButton('Sunday, March 8, 2026'));
    await user.keyboard('{ArrowUp}');
    expect(document.activeElement).toBe(first);
    await user.keyboard('{ArrowLeft}');
    expect(document.activeElement).toBe(dayButton('Saturday, February 28, 2026'));
    await user.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(dayButton('Saturday, March 7, 2026'));

    expect(await axe(container)).toHaveNoViolations();
  });


  it('keeps the day right when two clicks cross each other', async () => {
    signedIn();
    const { requests } = mockHabitsApi({ habits: [habitFixture()] });
    const first = deferred();
    const responses = [first.promise, Promise.resolve(HttpResponse.json({ marked: false, mark: null }))];
    toggleApi(() => responses.shift());
    const user = userEvent.setup();
    renderApp('/habits/1');

    await selectDay(user, 'Wednesday, March 4, 2026');
    const day = dayButton('Wednesday, March 4, 2026');
    await waitFor(() => expect(requests.filter((r) => r.path === '/habits/1/marks')).toHaveLength(1));
    // Dois cliques no botão do painel: marca e desmarca (a marcação otimista não tem detalhes)
    await user.dblClick(screen.getByRole('button', { name: 'Mark this day' }));
    // A segunda resposta chega antes da primeira
    first.resolve(HttpResponse.json({ marked: true, mark: markFixture({ id: 9 }) }));

    // Depois da última escrita, o ano é buscado de novo para confirmar o estado
    await waitFor(() => expect(requests.filter((r) => r.path === '/habits/1/marks')).toHaveLength(2));
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/Not marked$/));
  });
});

describe('habit calendar: several marks per day', () => {
  const multi = () =>
    habitFixture({ multi_mark: true, notes_enabled: true, code: null, name: 'Water' });

  it('counts the marks of the day and adds one', async () => {
    signedIn();
    mockHabitsApi({
      habits: [multi()],
      marks: {
        1: [
          markFixture({ id: 1, marked_at: '2026-03-10T11:00:00Z' }),
          markFixture({ id: 2, marked_at: '2026-03-10T13:00:00Z' }),
        ],
      },
    });
    const bodies = [];
    server.use(
      http.post(api('/habits/:id/marks'), async ({ request }) => {
        const body = await request.json();
        bodies.push(body);
        return HttpResponse.json(markFixture({ id: 3, marked_at: body.marked_at }), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/habits/1');

    const today = await findDay('Tuesday, March 10, 2026');
    await waitFor(() => expect(today.getAttribute('aria-label')).toMatch(/2 marks$/));
    const list = screen.getByRole('list', { name: 'Marks of the day' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);

    await user.click(screen.getByRole('button', { name: 'Add mark' }));

    expect(bodies).toEqual([{ marked_at: NOW.toISOString() }]);
    await waitFor(() => expect(today.getAttribute('aria-label')).toMatch(/3 marks$/));
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
  });

  it('shows the limit error and undoes the new mark', async () => {
    signedIn();
    mockHabitsApi({
      habits: [multi()],
      marks: { 1: [markFixture({ id: 1, marked_at: '2026-03-04T15:00:00Z' })] },
    });
    server.use(
      http.post(api('/habits/:id/marks'), () =>
        HttpResponse.json({ error: 'mark_limit_reached', field: null }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/habits/1');

    // Clicar num dia de um hábito com várias por dia só escolhe o dia
    const day = await findDay('Wednesday, March 4, 2026');
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/1 mark$/));
    await user.click(day);
    expect(screen.getByRole('heading', { level: 2, name: 'Wednesday, March 4, 2026' })).toBeDefined();

    await user.click(screen.getByRole('button', { name: 'Add mark' }));

    expect((await screen.findByRole('alert')).textContent).toContain(
      'This day has reached the mark limit for this habit.',
    );
    expect(day.getAttribute('aria-label')).toMatch(/1 mark$/);
    expect(within(screen.getByRole('list', { name: 'Marks of the day' })).getAllByRole('listitem')).toHaveLength(1);
  });

  it('deletes a mark after confirmation', async () => {
    signedIn();
    mockHabitsApi({
      habits: [multi()],
      marks: { 1: [markFixture({ id: 7, marked_at: '2026-03-10T13:00:00Z' })] },
    });
    const deleted = [];
    server.use(
      http.delete(api('/habits/:id/marks/:markId'), ({ params }) => {
        deleted.push(params.markId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/habits/1');

    await user.click(await screen.findByRole('button', { name: 'Delete the mark of 10:00 AM' }));
    expect(deleted).toEqual([]);
    await user.click(screen.getByRole('button', { name: 'Confirm deletion' }));

    await waitFor(() => expect(deleted).toEqual(['7']));
    expect(screen.queryByRole('list', { name: 'Marks of the day' })).toBeNull();
    expect(screen.getByText('No marks')).toBeDefined();
  });
});

describe('habit calendar: read only', () => {
  it('shows no write controls to a viewer', async () => {
    signedIn();
    mockHabitsApi({
      habits: [habitFixture({ role: 'viewer', notes_enabled: true })],
      marks: { 1: [markFixture({ marked_at: '2026-03-10T13:00:00Z', note: 'leg day' })] },
    });
    const bodies = toggleApi((body) => created(body));
    const user = userEvent.setup();
    const { container } = renderApp('/habits/1');

    const today = await findDay('Tuesday, March 10, 2026');
    await waitFor(() => expect(today.getAttribute('aria-label')).toMatch(/Marked$/));
    expect(screen.getByText('You can view this habit, but not mark it.')).toBeDefined();
    expect(screen.getByText('leg day')).toBeDefined();
    expect(screen.queryByRole('button', { name: /Mark this day|Unmark this day|Add mark/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Edit/ })).toBeNull();

    // Clicar e o teclado só escolhem o dia
    await user.click(dayButton('Monday, March 9, 2026'));
    expect(screen.getByRole('heading', { level: 2, name: 'Monday, March 9, 2026' })).toBeDefined();
    await user.keyboard('{ArrowRight}{Enter}');
    expect(screen.getByRole('heading', { level: 2, name: 'Tuesday, March 10, 2026' })).toBeDefined();
    await user.keyboard(' ');
    expect(bodies).toEqual([]);
    expect(today.dataset.marked).toBe('true');
    expect(screen.queryByRole('button', { name: /Mark this day|Unmark this day|Add mark/ })).toBeNull();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('keeps an archived habit read-only, even for the owner', async () => {
    signedIn();
    mockHabitsApi({ archived: [habitFixture({ status: 'archived', archived_at: '2026-03-01T00:00:00Z' })] });
    const bodies = toggleApi((body) => created(body));
    const user = userEvent.setup();
    const { container } = renderApp('/habits/1');

    await selectDay(user, 'Monday, March 9, 2026');
    await user.keyboard('{Enter} ');

    expect(screen.getByText(/This habit is archived and read-only/)).toBeDefined();
    expect(screen.getByText('Archived')).toBeDefined();
    expect(screen.queryByRole('button', { name: /Mark this day|Unmark this day|Add mark/ })).toBeNull();
    expect(bodies).toEqual([]);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('habit calendar: details of a mark', () => {
  it('edits note, duration and cost but never the date', async () => {
    signedIn();
    const habit = habitFixture({
      notes_enabled: true,
      duration_enabled: true,
      duration_minutes: 30,
      cost_enabled: true,
      cost_level: 'mark',
      cost_cents: 800,
    });
    const mark = markFixture({
      id: 42,
      marked_at: '2026-03-04T15:00:00Z',
      duration_minutes: 30,
      cost_cents: 800,
      note: null,
      author: null,
    });
    mockHabitsApi({ habits: [habit], marks: { 1: [mark] } });
    const patches = [];
    server.use(
      http.patch(api('/habits/:id/marks/:markId'), async ({ request }) => {
        const body = await request.json();
        patches.push(body);
        return HttpResponse.json({ ...mark, ...body });
      }),
    );
    const user = userEvent.setup();
    const { container } = renderApp('/habits/1?day=2026-03-04');

    const list = await screen.findByRole('list', { name: 'Marks of the day' });
    // Autor apagado
    expect(within(list).getByText('Removed user')).toBeDefined();
    expect(within(list).getByText('30 min')).toBeDefined();
    expect(within(list).getByText('8.00')).toBeDefined();

    await user.click(within(list).getByRole('button', { name: 'Edit the mark of 12:00 PM' }));
    expect(screen.getByText(/The date of a mark cannot be changed/)).toBeDefined();
    expect(container.querySelector('input[type="date"], input[type="datetime-local"]')).toBeNull();
    expect(await axe(container)).toHaveNoViolations();

    await user.type(screen.getByLabelText('Note'), 'felt great');
    const duration = screen.getByLabelText('Duration (minutes)');
    await user.clear(duration);
    await user.type(duration, '0');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByText('Enter whole minutes, from 1 to 1440.')).toBeDefined();
    expect(patches).toEqual([]);

    await user.clear(duration);
    await user.type(duration, '45');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    // Só os campos que mudaram; o custo ficou igual
    await waitFor(() => expect(patches).toEqual([{ note: 'felt great', duration_minutes: 45 }]));
    expect(await within(list).findByText('felt great')).toBeDefined();
    expect(within(list).getByText('45 min')).toBeDefined();
  });

  it('shows a validation error from the API in its field', async () => {
    signedIn();
    const habit = habitFixture({ notes_enabled: true });
    const mark = markFixture({ id: 42, marked_at: '2026-03-04T15:00:00Z' });
    mockHabitsApi({ habits: [habit], marks: { 1: [mark] } });
    server.use(
      http.patch(api('/habits/:id/marks/:markId'), () =>
        HttpResponse.json({ error: 'validation_error', field: 'note' }, { status: 422 }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/habits/1?day=2026-03-04');

    await user.click(await screen.findByRole('button', { name: 'Edit the mark of 12:00 PM' }));
    await user.click(screen.getByLabelText('Note'));
    await user.paste('x'.repeat(200));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    const note = screen.getByLabelText('Note');
    await waitFor(() => expect(note.getAttribute('aria-invalid')).toBe('true'));
    expect(screen.getByText('The note is too long or has characters that are not allowed.')).toBeDefined();
  });

  it('does not offer to edit the cost fixed by the habit', async () => {
    signedIn();
    const habit = habitFixture({ cost_enabled: true, cost_level: 'habit', cost_cents: 800 });
    mockHabitsApi({
      habits: [habit],
      marks: { 1: [markFixture({ marked_at: '2026-03-04T15:00:00Z', cost_cents: 800 })] },
    });
    renderApp('/habits/1?day=2026-03-04');

    const list = await screen.findByRole('list', { name: 'Marks of the day' });
    expect(within(list).getByText('8.00')).toBeDefined();
    expect(within(list).queryByRole('button', { name: /^Edit/ })).toBeNull();
  });
});

describe('habit calendar: year and score', () => {
  it.each([
    [2024, 366],
    [2025, 365],
  ])('renders %i with %i days', async (year, days) => {
    signedIn();
    const { requests } = mockHabitsApi({ habits: [habitFixture()] });
    const { container } = renderApp(`/habits/1?year=${year}`);

    await screen.findByRole('heading', { level: 2, name: String(year) });
    await waitFor(() => expect(requests.some((r) => r.path === '/habits/1/marks')).toBe(true));

    expect(container.querySelectorAll('[data-day]')).toHaveLength(days);
    expect(container.querySelectorAll('[aria-disabled="true"]')).toHaveLength(0);
    expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(12);
    // Sem dia escolhido em outro ano
    expect(screen.getByText('Choose a day in the calendar to see its marks.')).toBeDefined();
  });

  it('moves between years and loads the year in the account time zone', async () => {
    signedIn();
    const { requests } = mockHabitsApi({ habits: [habitFixture()] });
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1');

    await screen.findByRole('heading', { level: 2, name: '2026' });
    await user.click(screen.getByRole('button', { name: 'Previous year (2025)' }));

    expect(await screen.findByRole('heading', { level: 2, name: '2025' })).toBeDefined();
    expect(router.state.location.search).toBe('?range=year&year=2025');
    await waitFor(() => {
      expect(requests.filter((r) => r.path === '/habits/1/marks').map((r) => r.query)).toEqual([
        { from: '2026-01-01T03:00:00.000Z', to: '2027-01-01T03:00:00.000Z' },
        { from: '2025-01-01T03:00:00.000Z', to: '2026-01-01T03:00:00.000Z' },
      ]);
    });
    expect(router.state.location.pathname).toBe(`${BASENAME}/habits/1`);
  });

  it('follows the cursor until the last page of the year', async () => {
    signedIn();
    const habit = habitFixture({ multi_mark: true });
    const marks = Array.from({ length: 5 }, (_, index) =>
      markFixture({ id: index + 1, marked_at: `2026-02-0${index + 1}T15:00:00Z` }),
    );
    const { requests } = mockHabitsApi({ habits: [habit], marks: { 1: marks }, pageSize: 2 });
    renderApp('/habits/1');

    const day = await findDay('Thursday, February 5, 2026');
    await waitFor(() => expect(day.getAttribute('aria-label')).toMatch(/1 mark$/));
    expect(requests.filter((r) => r.path === '/habits/1/marks').map((r) => r.query.cursor)).toEqual([
      undefined,
      '2',
      '4',
    ]);
  });

  it('does not show the score when it is off', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture({ score_enabled: false })] });
    renderApp('/habits/1');

    await screen.findByRole('heading', { level: 1, name: 'RUN' });
    expect(screen.queryByText('Score')).toBeNull();
    expect(screen.queryByText('Threshold')).toBeNull();
  });

  it('shows the score, the threshold and the result when it is on', async () => {
    signedIn();
    mockHabitsApi({
      habits: [habitFixture({ score_enabled: true, score_threshold: 80, score: { value: 75, success: false } })],
    });
    const { container } = renderApp('/habits/1');

    await screen.findByRole('heading', { level: 1, name: 'RUN' });
    expect(screen.getByText('Score').nextElementSibling.textContent).toBe('75/100');
    expect(screen.getByText('Threshold').nextElementSibling.textContent).toBe('80');
    expect(screen.getByText('Failure')).toBeDefined();
    // A sigla aparece no lugar do nome, que fica embaixo
    expect(screen.getByText('Running')).toBeDefined();
    expect(document.title).toBe('RUN · ethos');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows "no data" until the first full period closes', async () => {
    signedIn();
    mockHabitsApi({
      habits: [habitFixture({ score_enabled: true, score: { value: null, success: null } })],
    });
    renderApp('/habits/1');

    expect(await screen.findByText('No data yet')).toBeDefined();
    expect(screen.queryByText('Success')).toBeNull();
    expect(screen.queryByText('Failure')).toBeNull();
  });

  it('refreshes the score after a mark', async () => {
    signedIn();
    const { requests } = mockHabitsApi({
      habits: [habitFixture({ score_enabled: true, score: { value: null, success: null } })],
    });
    toggleApi((body) => created(body));
    const user = userEvent.setup();
    renderApp('/habits/1');

    await selectDay(user, 'Monday, March 2, 2026');
    await user.click(screen.getByRole('button', { name: 'Mark this day' }));

    await waitFor(() => expect(requests.filter((r) => r.path === '/habits/1')).toHaveLength(2));
  });

  it('shows not found for a habit without access and for a bad id', async () => {
    signedIn();
    mockHabitsApi({ habits: [] });
    renderApp('/habits/99');

    expect((await screen.findByRole('alert')).textContent).toContain('Not found');
  });

  it('shows the not found page for an invalid id', async () => {
    signedIn();
    renderApp('/habits/abc');

    expect(await screen.findByRole('heading', { level: 1, name: 'Page not found' })).toBeDefined();
  });
});
