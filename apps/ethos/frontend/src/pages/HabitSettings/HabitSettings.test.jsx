import { describe, expect, it, vi } from 'vitest';
import { configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { habitKeys } from '../../api/habits';
import { BASENAME } from '../../paths';
import { axe } from '../../test/axe';
import { habitFixture, mockHabitWritesApi, mockHabitsApi } from '../../test/habits';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

// Sair da configuração leva para telas com o calendário do ano inteiro: folga para o CI
vi.setConfig({ testTimeout: 15_000 });
configure({ asyncUtilTimeout: 5_000 });

function signedIn() {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
}

/** Configuração do hábito 1 com a API falsa (leituras e escritas sobre o mesmo array). */
async function openSettings(overrides = {}, { fail } = {}) {
  signedIn();
  const habits = [habitFixture(overrides)];
  const reads = mockHabitsApi({ habits, marks: {} });
  const writes = mockHabitWritesApi(habits, { fail });
  const user = userEvent.setup();
  const view = renderApp('/habits/1/settings');
  await screen.findByRole('heading', { level: 2, name: 'Settings' });
  return { ...view, user, habits, reads, writes };
}

function writesOf(writes, method) {
  return writes.requests.filter((request) => request.method === method);
}

function save() {
  return screen.getByRole('button', { name: 'Save settings' });
}

describe('habit settings: access', () => {
  it('appears in the habit menu only for the owner', async () => {
    signedIn();
    mockHabitsApi({
      habits: [habitFixture(), habitFixture({ id: 2, code: 'BIA', role: 'editor' })],
      marks: {},
    });
    renderApp('/habits/1');

    const nav = await screen.findByRole('navigation', { name: 'Habit sections' });
    expect(within(nav).getByRole('link', { name: 'Settings' }).getAttribute('href')).toBe(
      `${BASENAME}/habits/1/settings`,
    );
  });

  it.each(['editor', 'viewer'])('sends the %s back to the calendar', async (role) => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture({ role })], marks: {} });
    const { router } = renderApp('/habits/1/settings');

    await waitFor(() => expect(router.state.location.pathname).toBe(`${BASENAME}/habits/1`));
    const nav = await screen.findByRole('navigation', { name: 'Habit sections' });
    expect(within(nav).queryByRole('link', { name: 'Settings' })).toBeNull();
    expect(screen.queryByRole('form', { name: 'Save settings' })).toBeNull();
  });
});

describe('habit settings: form', () => {
  it('has no accessibility violations', async () => {
    const { container } = await openSettings({
      description: 'Mornings',
      duration_enabled: true,
      duration_minutes: 40,
      score_enabled: true,
      score: { value: 80, success: true },
      reward: 'Pizza',
      cost_enabled: true,
      cost_cents: 800,
      cost_limit_cents: 10000,
      cost_limit_period: 'month',
    });

    expect(await axe(container)).toHaveNoViolations();
  });

  it('starts from the saved configuration', async () => {
    await openSettings({ code: 'RUN', goal_type: 'max', goal_count: 2, cost_enabled: true, cost_cents: 123450 });

    expect(screen.getByLabelText('Name').value).toBe('Running');
    expect(screen.getByLabelText('Code (optional)').value).toBe('RUN');
    expect(screen.getByLabelText('Goal type').value).toBe('max');
    expect(screen.getByLabelText('How many times').value).toBe('2');
    expect(screen.getByLabelText('Amount of each mark').value).toBe('1,234.50');
    expect(screen.getByText('at most 2 times a week.')).toBeTruthy();
  });

  it('sends only the fields that changed and refreshes the habit', async () => {
    const { user, writes } = await openSettings();

    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Run');
    await user.clear(screen.getByLabelText('Code (optional)'));
    await user.click(screen.getByRole('switch', { name: 'Score' }));
    await user.click(save());

    expect(await screen.findByText('Settings saved.')).toBeTruthy();
    expect(writesOf(writes, 'PATCH')).toEqual([
      {
        method: 'PATCH',
        path: '/habits/1',
        body: { name: 'Run', code: null, score_enabled: true },
      },
    ]);
    // O cabeçalho da aba já mostra o nome novo (sem sigla, o nome é o rótulo)
    expect(screen.getByRole('heading', { level: 1, name: 'Run' })).toBeTruthy();

    // Mexer de novo tira o "salvo"
    await user.type(screen.getByLabelText('Name'), 's');
    expect(screen.queryByText('Settings saved.')).toBeNull();
  });

  it('does not undo a change made elsewhere to a field it did not touch', async () => {
    const { user, writes, habits, queryClient } = await openSettings();

    // Outra aba renomeia o hábito; esta busca o hábito de novo
    habits[0].name = 'Morning run';
    await queryClient.invalidateQueries({ queryKey: habitKeys.all });
    const count = screen.getByLabelText('How many times');
    await user.clear(count);
    await user.type(count, '4');
    await user.click(save());

    await waitFor(() => expect(writesOf(writes, 'PATCH')).toHaveLength(1));
    expect(writesOf(writes, 'PATCH')[0].body).toEqual({ goal_count: 4 });
  });

  it('removes the cost limit together with its period', async () => {
    const { user, writes } = await openSettings({
      cost_enabled: true,
      cost_cents: 800,
      cost_limit_cents: 10000,
      cost_limit_period: 'month',
    });

    expect(screen.getByLabelText('Limit amount').value).toBe('100.00');
    await user.selectOptions(screen.getByLabelText('Spending limit'), '');
    expect(screen.queryByLabelText('Limit amount')).toBeNull();
    await user.click(save());

    await waitFor(() => expect(writesOf(writes, 'PATCH')).toHaveLength(1));
    expect(writesOf(writes, 'PATCH')[0].body).toEqual({ cost_limit_cents: null, cost_limit_period: null });
  });

  it('does not call the API when nothing changed', async () => {
    const { user, writes } = await openSettings();

    await user.click(save());

    expect(screen.getByText('Nothing changed to save.')).toBeTruthy();
    expect(writesOf(writes, 'PATCH')).toEqual([]);
  });

  it('warns that turning a feature off keeps its data, and sends only the switch', async () => {
    const { user, writes } = await openSettings({
      duration_enabled: true,
      duration_minutes: 40,
      score_enabled: true,
      reward: 'Pizza',
    });
    const kept = 'The minutes of the habit and of the marks are kept and come back when you turn this back on.';

    expect(screen.queryByText(kept)).toBeNull();
    await user.click(screen.getByRole('switch', { name: 'Duration' }));
    expect(screen.getByText(kept)).toBeTruthy();
    expect(screen.queryByLabelText('Default duration (minutes)')).toBeNull();

    await user.click(screen.getByRole('switch', { name: 'Score' }));
    expect(
      screen.getByText('The threshold, the reward and the punishment are kept and come back when you turn this back on.'),
    ).toBeTruthy();
    expect(screen.queryByLabelText('Reward (optional)')).toBeNull();

    // Religar mostra os valores guardados de novo, sem aviso
    await user.click(screen.getByRole('switch', { name: 'Duration' }));
    expect(screen.getByLabelText('Default duration (minutes)').value).toBe('40');
    expect(screen.queryByText(kept)).toBeNull();
    await user.click(screen.getByRole('switch', { name: 'Duration' }));

    await user.click(save());

    await waitFor(() => expect(writesOf(writes, 'PATCH')).toHaveLength(1));
    expect(writesOf(writes, 'PATCH')[0].body).toEqual({ duration_enabled: false, score_enabled: false });
    // Salvo desligado, o aviso some
    await waitFor(() => expect(screen.queryByText(kept)).toBeNull());
  });

  it('warns that several marks per day back to toggle keeps the extra marks', async () => {
    const { user } = await openSettings({ multi_mark: true, goal_count: 5 });

    await user.click(screen.getByRole('switch', { name: 'Several marks per day' }));

    expect(screen.getByText(/The extra marks are kept/)).toBeTruthy();
  });

  it('shows a 422 from the API under its field', async () => {
    const { user } = await openSettings(
      {},
      { fail: () => HttpResponse.json({ error: 'validation_error', field: 'goal_count' }, { status: 422 }) },
    );
    const count = screen.getByLabelText('How many times');

    await user.clear(count);
    await user.type(count, '5');
    await user.click(save());

    await waitFor(() => expect(count.getAttribute('aria-invalid')).toBe('true'));
    expect(document.activeElement).toBe(count);
    expect(screen.getByText(/This number does not work for this goal/)).toBeTruthy();
  });

  it('shows an error on N when the type changes to at least with N = 0', async () => {
    const { user, writes } = await openSettings({ goal_type: 'max', goal_count: 0 });
    const count = screen.getByLabelText('How many times');

    expect(screen.getByText('zero times a week.')).toBeTruthy();
    await user.selectOptions(screen.getByLabelText('Goal type'), 'min');

    expect(count.getAttribute('aria-invalid')).toBe('true');
    expect(screen.getByText('Use a whole number from 1 to 7.')).toBeTruthy();

    await user.click(save());
    expect(writesOf(writes, 'PATCH')).toEqual([]);
    expect(document.activeElement).toBe(count);
  });

  it('is read-only when the habit is archived', async () => {
    await openSettings({ status: 'archived', archived_at: '2026-03-01T12:00:00Z' });

    expect(screen.getByText(/This habit is archived: its settings are read-only/)).toBeTruthy();
    expect(screen.getByLabelText('Name').matches(':disabled')).toBe(true);
    expect(save().matches(':disabled')).toBe(true);
  });
});

describe('habit settings: status', () => {
  it('pauses and resumes the habit', async () => {
    const { user, writes } = await openSettings();

    expect(screen.getByText('This habit is active.')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Pause' }));

    expect(await screen.findByText('Habit paused.')).toBeTruthy();
    expect(screen.getByText('This habit is paused.')).toBeTruthy();
    const resume = screen.getByRole('button', { name: 'Resume' });
    await waitFor(() => expect(document.activeElement).toBe(resume));

    await user.click(resume);

    expect(await screen.findByText('Habit resumed.')).toBeTruthy();
    expect(writesOf(writes, 'POST').map((request) => request.path)).toEqual([
      '/habits/1/pause',
      '/habits/1/resume',
    ]);
  });

  it('archives the habit, which makes the form read-only', async () => {
    const { user, writes } = await openSettings();

    await user.click(screen.getByRole('button', { name: 'Archive' }));

    expect(await screen.findByText('Habit archived.')).toBeTruthy();
    expect(writesOf(writes, 'POST')[0].path).toBe('/habits/1/archive');
    expect(screen.getByLabelText('Name').matches(':disabled')).toBe(true);
    expect(screen.getByRole('button', { name: 'Unarchive' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull();
  });

  it('shows the habit limit when unarchiving is refused', async () => {
    const { user } = await openSettings(
      { status: 'archived', archived_at: '2026-03-01T12:00:00Z' },
      { fail: () => HttpResponse.json({ error: 'habit_limit_reached', field: null }, { status: 409 }) },
    );

    await user.click(screen.getByRole('button', { name: 'Unarchive' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/reached the limit of active and paused habits/);
    expect(screen.getByText('This habit is archived.')).toBeTruthy();
  });
});

describe('habit settings: delete', () => {
  it('asks for confirmation, warning about the guests marks, before deleting', async () => {
    const { user, writes, router, habits } = await openSettings();

    await user.click(screen.getByRole('button', { name: 'Delete habit' }));

    const panel = screen.getByRole('group', { name: 'Delete RUN?' });
    expect(document.activeElement).toBe(panel);
    expect(within(panel).getByText(/all its marks, including the guests' marks/)).toBeTruthy();
    expect(writesOf(writes, 'DELETE')).toEqual([]);

    await user.click(within(panel).getByRole('button', { name: 'Delete for good' }));

    await waitFor(() => expect(router.state.location.pathname).toBe(BASENAME));
    expect(writesOf(writes, 'DELETE')).toEqual([{ method: 'DELETE', path: '/habits/1', body: null }]);
    expect(habits).toEqual([]);
    expect(await screen.findByText('You do not have any habits yet.')).toBeTruthy();
  });

  it('cancels without deleting and gives the focus back', async () => {
    const { user, writes } = await openSettings();

    await user.click(screen.getByRole('button', { name: 'Delete habit' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('group', { name: 'Delete RUN?' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Delete habit' }));
    expect(writesOf(writes, 'DELETE')).toEqual([]);
  });

  it('shows the error and stays when deleting fails', async () => {
    const { user, router } = await openSettings(
      {},
      { fail: () => HttpResponse.json({ error: 'internal_error', field: null }, { status: 500 }) },
    );

    await user.click(screen.getByRole('button', { name: 'Delete habit' }));
    await user.click(screen.getByRole('button', { name: 'Delete for good' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(router.state.location.pathname).toBe(`${BASENAME}/habits/1/settings`);
  });
});
