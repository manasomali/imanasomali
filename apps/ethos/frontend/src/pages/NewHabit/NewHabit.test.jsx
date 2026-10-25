import { describe, expect, it, vi } from 'vitest';
import { configure, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { BASENAME } from '../../paths';
import { axe } from '../../test/axe';
import { habitFixture, mockHabitWritesApi, mockHabitsApi } from '../../test/habits';
import { createTestI18n } from '../../test/i18n';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

// Criar abre a aba do hábito, com o calendário do ano inteiro: folga para o CI
vi.setConfig({ testTimeout: 15_000 });
configure({ asyncUtilTimeout: 5_000 });

function signedIn() {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
}

/** Tela de criar com a API falsa; `habits` é a lista que a API devolve (e que a criação muda). */
async function openNewHabit({ habits = [], fail } = {}) {
  signedIn();
  mockHabitsApi({ habits, marks: {} });
  const writes = mockHabitWritesApi(habits, { fail });
  const user = userEvent.setup();
  const view = renderApp('/habits/new');
  await screen.findByRole('heading', { level: 1, name: 'New habit' });
  return { ...view, user, writes, habits };
}

function form() {
  return screen.getByRole('form', { name: 'Create habit' });
}

function posts(writes) {
  return writes.requests.filter((request) => request.method === 'POST');
}

describe('new habit', () => {
  it('is reached from the main tab', async () => {
    signedIn();
    mockHabitsApi({ habits: [] });
    const user = userEvent.setup();
    const { router } = renderApp('/');

    await user.click(await screen.findByRole('link', { name: 'New habit' }));

    expect(router.state.location.pathname).toBe(`${BASENAME}/habits/new`);
    expect(await screen.findByRole('form', { name: 'Create habit' })).toBeTruthy();
  });

  it('has no accessibility violations, with every feature on', async () => {
    const { container, user } = await openNewHabit();
    for (const name of ['Several marks per day', 'Duration', 'Note', 'Score', 'Cost']) {
      await user.click(screen.getByRole('switch', { name }));
    }
    await user.selectOptions(screen.getByLabelText('Spending limit'), 'week');

    expect(await axe(container)).toHaveNoViolations();
  });

  it('creates the habit with the valid data and opens its tab', async () => {
    const { user, writes, router } = await openNewHabit();

    await user.type(screen.getByLabelText('Name'), '  Meditate ');
    await user.type(screen.getByLabelText('Code (optional)'), 'med');
    await user.click(screen.getByRole('radio', { name: 'Blue' }));
    await user.selectOptions(screen.getByLabelText('Goal type'), 'exact');
    await user.clear(screen.getByLabelText('How many times'));
    await user.type(screen.getByLabelText('How many times'), '2');
    await user.selectOptions(screen.getByLabelText('Per'), 'month');
    await user.click(screen.getByRole('switch', { name: 'Duration' }));
    await user.type(screen.getByLabelText('Default duration (minutes)'), '40');
    await user.click(screen.getByRole('switch', { name: 'Cost' }));
    await user.type(screen.getByLabelText('Amount of each mark'), '1,234.5');
    await user.click(screen.getByRole('button', { name: 'Create habit' }));

    await waitFor(() => expect(router.state.location.pathname).toBe(`${BASENAME}/habits/1`));
    expect(posts(writes)).toEqual([
      {
        method: 'POST',
        path: '/habits',
        body: {
          name: 'Meditate',
          code: 'MED',
          description: null,
          color: 'blue',
          goal_type: 'exact',
          goal_count: 2,
          goal_period: 'month',
          multi_mark: false,
          duration_enabled: true,
          duration_minutes: 40,
          notes_enabled: false,
          score_enabled: false,
          cost_enabled: true,
          cost_level: 'habit',
          cost_cents: 123450,
          cost_limit_cents: null,
          cost_limit_period: null,
        },
      },
    ]);
    expect(await screen.findByRole('heading', { level: 1, name: 'MED' })).toBeTruthy();
  });

  it('shows a clear message when the habit limit is reached', async () => {
    const { user, router } = await openNewHabit({
      fail: () => HttpResponse.json({ error: 'habit_limit_reached', field: null }, { status: 409 }),
    });

    await user.type(screen.getByLabelText('Name'), 'Read');
    await user.click(screen.getByRole('button', { name: 'Create habit' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(
      /reached the limit of active and paused habits\. Archive or delete a habit/,
    );
    expect(router.state.location.pathname).toBe(`${BASENAME}/habits/new`);
  });

  it('shows a 422 from the API under its field, and focuses it', async () => {
    const { user } = await openNewHabit({
      fail: () => HttpResponse.json({ error: 'validation_error', field: 'name' }, { status: 422 }),
    });

    await user.type(screen.getByLabelText('Name'), 'Read');
    await user.click(screen.getByRole('button', { name: 'Create habit' }));

    const name = screen.getByLabelText('Name');
    await waitFor(() => expect(name.getAttribute('aria-invalid')).toBe('true'));
    expect(document.activeElement).toBe(name);
    const error = document.getElementById(name.getAttribute('aria-describedby').split(' ').at(-1));
    expect(error.textContent).toBe('Invalid name: use 1 to 60 characters, on a single line.');
    expect(screen.queryByRole('alert')).toBeNull();

    // Mexer no campo tira o erro da API
    await user.type(name, 's');
    expect(name.getAttribute('aria-invalid')).toBeNull();
  });

  it('checks the fields before calling the API and focuses the first invalid one', async () => {
    const { user, writes } = await openNewHabit();

    await user.type(screen.getByLabelText('Code (optional)'), 'a-1');
    await user.click(screen.getByRole('button', { name: 'Create habit' }));

    const name = screen.getByLabelText('Name');
    expect(document.activeElement).toBe(name);
    expect(name.getAttribute('aria-invalid')).toBe('true');
    expect(within(form()).getByText('Fill in this field.')).toBeTruthy();
    expect(within(form()).getByText('Use 1 to 4 unaccented letters or digits.')).toBeTruthy();
    expect(posts(writes)).toEqual([]);
  });

  it('counts the characters of the fields with a limit', async () => {
    const { user } = await openNewHabit();

    expect(screen.getByText('0/60 characters')).toBeTruthy();
    expect(screen.getByText('0/4 characters')).toBeTruthy();
    expect(screen.getByText('0/500 characters')).toBeTruthy();

    await user.type(screen.getByLabelText('Name'), 'Run 🏃');
    expect(screen.getByText('5/60 characters')).toBeTruthy();

    await user.click(screen.getByRole('switch', { name: 'Score' }));
    expect(screen.getAllByText('0/140 characters')).toHaveLength(2);
  });

  it('shows an error on N when the type changes to at least with N = 0', async () => {
    const { user } = await openNewHabit();
    const count = screen.getByLabelText('How many times');

    await user.selectOptions(screen.getByLabelText('Goal type'), 'max');
    await user.clear(count);
    await user.type(count, '0');
    expect(screen.getByText('zero times a week.')).toBeTruthy();
    expect(count.getAttribute('aria-invalid')).toBeNull();

    await user.selectOptions(screen.getByLabelText('Goal type'), 'min');

    expect(count.getAttribute('aria-invalid')).toBe('true');
    expect(screen.getByText('Use a whole number from 1 to 7.')).toBeTruthy();
    expect(screen.getByText('pick a valid number to see the goal.')).toBeTruthy();
  });

  it('caps N by the period, and by MAX_MARKS_PER_DAY with several marks per day', async () => {
    const { user } = await openNewHabit();
    const count = screen.getByLabelText('How many times');

    await user.clear(count);
    await user.type(count, '8');
    expect(screen.getByText('Use a whole number from 1 to 7.')).toBeTruthy();

    await user.click(screen.getByRole('switch', { name: 'Several marks per day' }));
    expect(count.getAttribute('aria-invalid')).toBeNull();
    expect(screen.getByText('From 1 to 6993 in this period.')).toBeTruthy();
    expect(screen.getByText('at least 8 times a week.')).toBeTruthy();
  });

  it('previews the goal in Portuguese, with "nenhuma vez" for at most 0', async () => {
    window.localStorage.setItem('i18nextLng', 'pt');
    createTestI18n();
    signedIn();
    mockHabitsApi({ habits: [] });
    const user = userEvent.setup();
    renderApp('/habits/new');
    await screen.findByRole('heading', { level: 1, name: 'Novo hábito' });
    const count = screen.getByLabelText('Quantas vezes');

    expect(screen.getByText('pelo menos 1 vez por semana.')).toBeTruthy();
    // O calendário começa no domingo, mas a semana da meta é a ISO
    expect(screen.getByText('A semana da meta vai de segunda a domingo.')).toBeTruthy();

    await user.clear(count);
    await user.type(count, '3');
    expect(screen.getByText('pelo menos 3 vezes por semana.')).toBeTruthy();

    await user.selectOptions(screen.getByLabelText('Tipo da meta'), 'max');
    await user.clear(count);
    await user.type(count, '0');
    await user.selectOptions(screen.getByLabelText('Por'), 'month');
    expect(screen.getByText('nenhuma vez por mês.')).toBeTruthy();
    expect(screen.queryByText('A semana da meta vai de segunda a domingo.')).toBeNull();

    await user.selectOptions(screen.getByLabelText('Tipo da meta'), 'exact');
    await user.clear(count);
    await user.type(count, '2');
    await user.click(screen.getByRole('switch', { name: 'Duração' }));
    await user.type(screen.getByLabelText('Duração padrão (minutos)'), '40');
    expect(screen.getByText('exatamente 2 vezes por mês.')).toBeTruthy();
    expect(
      screen.getByText('Com a duração ligada, conta a soma dos minutos: exatamente 80 min por mês.'),
    ).toBeTruthy();
  });

  it('shows and hides the fields of each feature', async () => {
    const { user } = await openNewHabit();
    const hidden = (label) => expect(screen.queryByLabelText(label)).toBeNull();
    const shown = (label) => expect(screen.getByLabelText(label)).toBeTruthy();

    const features = {
      Duration: ['Default duration (minutes)'],
      Score: ['Success threshold', 'Reward (optional)', 'Punishment (optional)'],
      Cost: ['Amount of each mark', 'Spending limit'],
    };
    for (const [name, labels] of Object.entries(features)) {
      const toggle = screen.getByRole('switch', { name });
      expect(toggle.checked).toBe(false);
      labels.forEach(hidden);

      await user.click(toggle);
      labels.forEach(shown);

      await user.click(toggle);
      labels.forEach(hidden);
    }

    // Os recursos sem campos próprios só mudam a chave
    for (const name of ['Several marks per day', 'Note']) {
      await user.click(screen.getByRole('switch', { name }));
      expect(screen.getByRole('switch', { name }).checked).toBe(true);
    }
  });

  it('starts the score at the threshold of 70 and the reward only with the score on', async () => {
    const { user } = await openNewHabit();

    expect(screen.queryByLabelText('Reward (optional)')).toBeNull();
    await user.click(screen.getByRole('switch', { name: 'Score' }));

    expect(screen.getByLabelText('Success threshold').value).toBe('70');
    expect(screen.getByLabelText('Reward (optional)')).toBeTruthy();
  });

  it('asks for the cost per mark as an optional default, and the limit amount with a period', async () => {
    const { user, writes } = await openNewHabit();

    await user.type(screen.getByLabelText('Name'), 'Bets');
    await user.click(screen.getByRole('switch', { name: 'Cost' }));
    await user.click(screen.getByRole('radio', { name: 'Per mark: each mark has its own amount' }));
    expect(screen.getByLabelText('Default amount of the marks (optional)')).toBeTruthy();
    expect(screen.queryByLabelText('Limit amount')).toBeNull();

    const limitPeriod = screen.getByLabelText('Spending limit');
    expect(screen.queryByText('The limit week runs from Monday to Sunday.')).toBeNull();
    await user.selectOptions(limitPeriod, 'week');
    const weekHint = screen.getByText('The limit week runs from Monday to Sunday.');
    expect(limitPeriod.getAttribute('aria-describedby').split(' ')).toContain(weekHint.id);
    await user.click(screen.getByRole('button', { name: 'Create habit' }));
    expect(screen.getByLabelText('Limit amount').getAttribute('aria-invalid')).toBe('true');
    expect(posts(writes)).toEqual([]);

    await user.type(screen.getByLabelText('Limit amount'), '50');
    await user.click(screen.getByRole('button', { name: 'Create habit' }));

    await waitFor(() => expect(posts(writes)).toHaveLength(1));
    expect(posts(writes)[0].body).toMatchObject({
      cost_level: 'mark',
      cost_cents: null,
      cost_limit_cents: 5000,
      cost_limit_period: 'week',
    });
  });

  it('offers the palette of 12 first and a custom colour last, without a free text field', async () => {
    await openNewHabit();
    const radios = within(screen.getByRole('group', { name: /^Colour/ })).getAllByRole('radio');

    expect(radios).toHaveLength(13);
    expect(radios.at(-1)).toBe(screen.getByRole('radio', { name: 'Custom' }));
    expect(screen.getByRole('radio', { name: 'Teal' }).checked).toBe(true);
    expect(screen.getByLabelText('Pick a custom colour').type).toBe('color');
    expect(screen.queryByRole('textbox', { name: /colour/i })).toBeNull();
    expect(screen.queryByText(/Low contrast/)).toBeNull();
  });

  it('sends the custom colour picked in the selector, with a preview and no warning when it is readable', async () => {
    const { container, user, writes } = await openNewHabit();

    await user.type(screen.getByLabelText('Name'), 'Read');
    fireEvent.input(screen.getByLabelText('Pick a custom colour'), { target: { value: '#808080' } });

    const group = screen.getByRole('group', { name: 'Colour: Custom (#808080)' });
    expect(within(group).getByRole('radio', { name: 'Custom' }).checked).toBe(true);
    expect(within(group).getByText('Light theme')).toBeTruthy();
    expect(within(group).getByText('Dark theme')).toBeTruthy();
    expect(screen.queryByText(/Low contrast/)).toBeNull();
    // A prévia pinta pelo CSSOM, como o calendário: cor e texto escuro sobre ela
    const day = within(group).getAllByText('12')[0];
    expect(day.dataset.habitColor).toBe('custom');
    expect(day.style.getPropertyValue('--habit-color')).toBe('#808080');
    expect(day.dataset.habitText).toBe('dark');
    expect(await axe(container)).toHaveNoViolations();

    await user.click(screen.getByRole('button', { name: 'Create habit' }));

    await waitFor(() => expect(posts(writes)).toHaveLength(1));
    expect(posts(writes)[0].body.color).toBe('#808080');
  });

  it('sends the palette name again after going back to the palette, and keeps the custom colour', async () => {
    const { user, writes } = await openNewHabit();

    await user.type(screen.getByLabelText('Name'), 'Read');
    fireEvent.input(screen.getByLabelText('Pick a custom colour'), { target: { value: '#0a1b2c' } });
    await user.click(screen.getByRole('radio', { name: 'Pink' }));

    expect(screen.getByRole('group', { name: 'Colour: Pink' })).toBeTruthy();
    expect(screen.queryByText('Light theme')).toBeNull();
    // A opção "personalizada" volta com a última cor própria
    await user.click(screen.getByRole('radio', { name: 'Custom' }));
    expect(screen.getByRole('group', { name: 'Colour: Custom (#0a1b2c)' })).toBeTruthy();
    await user.click(screen.getByRole('radio', { name: 'Pink' }));

    await user.click(screen.getByRole('button', { name: 'Create habit' }));
    await waitFor(() => expect(posts(writes)).toHaveLength(1));
    expect(posts(writes)[0].body.color).toBe('pink');
  });

  it('takes the colour in the selector when "custom" is chosen first', async () => {
    const { user } = await openNewHabit();
    const picker = screen.getByLabelText('Pick a custom colour');

    await user.click(screen.getByRole('radio', { name: 'Custom' }));

    // Sem o CSS (jsdom), o seletor começa no padrão do navegador
    expect(screen.getByRole('group', { name: `Colour: Custom (${picker.value})` })).toBeTruthy();
    expect(screen.getByRole('radio', { name: 'Custom' }).checked).toBe(true);
  });

  it('warns about a custom colour with low contrast against the light theme', async () => {
    const { container, user, writes } = await openNewHabit();

    await user.type(screen.getByLabelText('Name'), 'Read');
    fireEvent.input(screen.getByLabelText('Pick a custom colour'), { target: { value: '#ffffff' } });

    const warning = screen.getByText(/^Low contrast against the light theme background: 1:1 \(at least 3:1/);
    expect(screen.queryByText(/dark theme background/)).toBeNull();
    // O aviso descreve o seletor e a opção, e é anunciado quando aparece
    const picker = screen.getByLabelText('Pick a custom colour');
    expect(picker.getAttribute('aria-describedby')).toContain(warning.parentElement.id);
    expect(warning.parentElement.getAttribute('aria-live')).toBe('polite');
    expect(await axe(container)).toHaveNoViolations();

    // Aceita mesmo assim
    await user.click(screen.getByRole('button', { name: 'Create habit' }));
    await waitFor(() => expect(posts(writes)).toHaveLength(1));
    expect(posts(writes)[0].body.color).toBe('#ffffff');
  });

  it('warns in Portuguese too', async () => {
    window.localStorage.setItem('i18nextLng', 'pt');
    createTestI18n();
    signedIn();
    mockHabitsApi({ habits: [] });
    renderApp('/habits/new');
    await screen.findByRole('heading', { level: 1, name: 'Novo hábito' });

    fireEvent.input(screen.getByLabelText('Escolher a cor personalizada'), { target: { value: '#1c1c1c' } });

    expect(screen.getByRole('group', { name: 'Cor: Personalizada (#1c1c1c)' })).toBeTruthy();
    expect(screen.getByText(/^Pouco contraste com o fundo do tema escuro: 1:1/)).toBeTruthy();
  });

  it('keeps a habit that already exists in the list after creating', async () => {
    const existing = habitFixture({ id: 4, name: 'Running' });
    const { user, habits } = await openNewHabit({ habits: [existing] });

    await user.type(screen.getByLabelText('Name'), 'Read');
    await user.click(screen.getByRole('button', { name: 'Create habit' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Read' })).toBeTruthy();
    expect(habits.map((habit) => habit.id)).toEqual([4, 5]);
  });
});
