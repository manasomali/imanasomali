import { describe, expect, it, vi } from 'vitest';
import { configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { BASENAME, PATHS } from '../../paths';
import { alertFixture, mockAlertsApi } from '../../test/alerts';
import { axe } from '../../test/axe';
import { habitFixture, mockHabitsApi } from '../../test/habits';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

vi.setConfig({ testTimeout: 15_000 });
configure({ asyncUtilTimeout: 5_000 });

const ALERTS_PATH = '/habits/1/alerts';
// Criado há tempo: o período da criação já passou (sem o aviso de "só a partir de")
const OLD = '2020-01-06T12:00:00Z';

function signedIn(overrides = {}) {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture(overrides))));
}

/** Tela de alertas do hábito 1 com a API falsa. */
async function openAlerts(habit = {}, { alert, fail, me } = {}) {
  signedIn(me);
  mockHabitsApi({ habits: [habitFixture({ created_at: OLD, ...habit })], marks: {} });
  const alerts = mockAlertsApi({ alerts: alert ? { 1: alertFixture(alert) } : {}, fail });
  const user = userEvent.setup();
  const view = renderApp(ALERTS_PATH);
  await screen.findByRole('form', { name: 'Save alerts' });
  return { ...view, user, alerts };
}

function puts(alerts) {
  return alerts.requests.filter((request) => request.method === 'PUT');
}

function save() {
  return screen.getByRole('button', { name: 'Save alerts' });
}

describe('habit alerts: access', () => {
  it.each(['owner', 'editor'])('appears in the habit menu for the %s', async (role) => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture({ role })], marks: {} });
    renderApp('/habits/1');

    const nav = await screen.findByRole('navigation', { name: 'Habit sections' });
    expect(within(nav).getByRole('link', { name: 'Alerts' }).getAttribute('href')).toBe(
      `${BASENAME}${ALERTS_PATH}`,
    );
  });

  it('hides the shortcut from the viewer and shows no permission at the address', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture({ role: 'viewer' })], marks: {} });
    const alerts = mockAlertsApi();
    const { container } = renderApp(ALERTS_PATH);

    expect(
      await screen.findByText('No permission: people who can only view the habit do not set up or receive alerts.'),
    ).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Alerts' })).toBeTruthy();
    const nav = screen.getByRole('navigation', { name: 'Habit sections' });
    expect(within(nav).queryByRole('link', { name: 'Alerts' })).toBeNull();
    expect(screen.queryByRole('form', { name: 'Save alerts' })).toBeNull();
    // A tela nem pergunta à API (que responderia 403)
    expect(alerts.requests).toEqual([]);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('comes back to the alerts after the login (link of the email)', async () => {
    let session = false;
    server.use(
      http.get(api('/auth/me'), () =>
        session
          ? HttpResponse.json(meFixture())
          : HttpResponse.json({ error: 'unauthorized', field: null }, { status: 401 }),
      ),
      http.post(api('/auth/code/request'), () => HttpResponse.json({ status: 'accepted' }, { status: 202 })),
      http.post(api('/auth/code/verify'), () => {
        session = true;
        return HttpResponse.json({ new_account: false });
      }),
    );
    mockHabitsApi({ habits: [habitFixture({ created_at: OLD })], marks: {} });
    mockAlertsApi();
    const user = userEvent.setup();
    const { router } = renderApp(ALERTS_PATH);

    // Sem sessão: o login, guardando a tela de alertas
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeTruthy();
    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.login}`);
    await user.type(screen.getByLabelText('Email'), 'ana@example.com');
    await user.click(screen.getByRole('button', { name: 'Send code' }));
    await user.type(await screen.findByLabelText('6-digit code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('form', { name: 'Save alerts' })).toBeTruthy();
    expect(router.state.location.pathname).toBe(`${BASENAME}${ALERTS_PATH}`);
  });
});

describe('habit alerts: form', () => {
  it('has no accessibility violations', async () => {
    const { container, user } = await openAlerts(
      { cost_enabled: true, cost_cents: 800, cost_limit_cents: 10000, cost_limit_period: 'month' },
      { alert: { goal_enabled: true, last_sent_at: '2026-03-04T23:00:00Z' } },
    );
    expect(await axe(container)).toHaveNoViolations();

    // Com o dia da semana e o erro dele à mostra
    await user.click(screen.getByRole('radio', { name: 'Once a week' }));
    await user.click(save());
    expect(await axe(container)).toHaveNoViolations();
  });

  it('starts from the defaults when nothing was saved', async () => {
    await openAlerts();

    expect(screen.getByRole('switch', { name: 'Goal alert' }).checked).toBe(false);
    expect(screen.getByLabelText('Hour').value).toBe('20');
    expect(screen.getByRole('option', { name: '8:00 PM' }).selected).toBe(true);
    expect(screen.getByRole('radio', { name: 'Every day' }).checked).toBe(true);
    expect(screen.queryByLabelText('Weekday')).toBeNull();
    expect(screen.getByText('No alert email sent yet.')).toBeTruthy();
  });

  it('shows the hour in the time zone of the account', async () => {
    await openAlerts({}, { me: { timezone: 'Asia/Tokyo' }, alert: { last_sent_at: '2026-03-04T23:00:00Z' } });

    const hint = screen.getByText(/In your time zone, Asia\/Tokyo\./);
    expect(within(hint).getByRole('link', { name: 'your account' }).getAttribute('href')).toBe(
      `${BASENAME}${PATHS.account}`,
    );
    expect(screen.getByLabelText('Hour').getAttribute('aria-describedby')).toContain(hint.id);
    // 23:00 UTC = 08:00 do dia seguinte em Tóquio
    expect(screen.getByText('Last alert email: Mar 5, 2026, 8:00 AM.')).toBeTruthy();
  });

  it('saves the whole configuration with the right values', async () => {
    const { user, alerts } = await openAlerts({}, { alert: { last_sent_at: '2026-03-04T23:00:00Z' } });

    await user.click(screen.getByRole('switch', { name: 'Goal alert' }));
    await user.selectOptions(screen.getByLabelText('Hour'), '7:00 AM');
    await user.click(screen.getByRole('radio', { name: 'Once a week' }));
    await user.selectOptions(screen.getByLabelText('Weekday'), 'Wednesday');
    await user.click(save());

    expect(await screen.findByText('Alerts saved.')).toBeTruthy();
    expect(puts(alerts)).toEqual([
      {
        method: 'PUT',
        path: ALERTS_PATH,
        body: { goal_enabled: true, cost_enabled: false, hour: 7, frequency: 'weekly', weekday: 2 },
      },
    ]);

    // Voltar ao diário manda o dia vazio, e mexer tira o "salvo"
    await user.click(screen.getByRole('radio', { name: 'Every day' }));
    expect(screen.queryByText('Alerts saved.')).toBeNull();
    expect(screen.queryByLabelText('Weekday')).toBeNull();
    await user.click(save());

    await waitFor(() => expect(puts(alerts)).toHaveLength(2));
    expect(puts(alerts)[1].body).toEqual({
      goal_enabled: true,
      cost_enabled: false,
      hour: 7,
      frequency: 'daily',
      weekday: null,
    });
  });

  it('requires the weekday in the weekly mode', async () => {
    const { user, alerts } = await openAlerts({}, { alert: { goal_enabled: true } });

    await user.click(screen.getByRole('radio', { name: 'Once a week' }));
    const weekday = screen.getByLabelText('Weekday');
    expect(weekday.value).toBe('');
    await user.click(save());

    const error = screen.getByText('Choose the weekday of the weekly alert.');
    expect(weekday.getAttribute('aria-invalid')).toBe('true');
    expect(weekday.getAttribute('aria-describedby')).toContain(error.id);
    expect(document.activeElement).toBe(weekday);
    expect(puts(alerts)).toEqual([]);

    await user.selectOptions(weekday, 'Sunday');
    expect(screen.queryByText('Choose the weekday of the weekly alert.')).toBeNull();
    await user.click(save());
    await waitFor(() => expect(puts(alerts)).toHaveLength(1));
    expect(puts(alerts)[0].body).toMatchObject({ frequency: 'weekly', weekday: 6 });
  });

  it('starts the weekly mode from the saved weekday', async () => {
    await openAlerts({}, { alert: { frequency: 'weekly', weekday: 4, hour: 9 } });

    expect(screen.getByRole('radio', { name: 'Once a week' }).checked).toBe(true);
    expect(screen.getByRole('option', { name: 'Friday' }).selected).toBe(true);
    expect(screen.getByRole('option', { name: '9:00 AM' }).selected).toBe(true);
  });

  it('shows the error of the API and focuses the field it points to', async () => {
    const { user } = await openAlerts({}, {
      alert: { frequency: 'weekly', weekday: 1 },
      fail: ({ method }) =>
        method === 'PUT'
          ? HttpResponse.json({ error: 'validation_error', field: 'weekday' }, { status: 422 })
          : null,
    });

    await user.click(save());

    expect((await screen.findByRole('alert')).textContent).toContain('Some field is invalid.');
    const weekday = screen.getByLabelText('Weekday');
    expect(weekday.getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(weekday);
  });

  it('shows a load error with a retry', async () => {
    let failures = 1;
    signedIn();
    mockHabitsApi({ habits: [habitFixture({ created_at: OLD })], marks: {} });
    mockAlertsApi({
      fail: () => {
        if (failures === 0) return null;
        failures -= 1;
        return HttpResponse.json({ error: 'forbidden', field: null }, { status: 403 });
      },
    });
    const user = userEvent.setup();
    renderApp(ALERTS_PATH);

    expect((await screen.findByRole('alert')).textContent).toContain('You do not have permission');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('form', { name: 'Save alerts' })).toBeTruthy();
  });
});

describe('habit alerts: cost', () => {
  it('offers the cost alert only when the habit has a cost with a limit', async () => {
    await openAlerts({ cost_enabled: true, cost_cents: 800, cost_limit_cents: null, cost_limit_period: null });

    expect(screen.queryByRole('switch', { name: 'Cost alert' })).toBeNull();
  });

  it('explains the 80% warning and saves the cost switch', async () => {
    const { user, alerts } = await openAlerts({
      cost_enabled: true,
      cost_cents: 800,
      cost_limit_cents: 123450,
      cost_limit_period: 'week',
    });

    const toggle = screen.getByRole('switch', { name: 'Cost alert' });
    const rule = screen.getByText(
      "Warns when this week's spending reaches 80% of the limit (1,234.50), and again when it goes over.",
    );
    expect(toggle.getAttribute('aria-describedby')).toContain(rule.parentElement.id);
    await user.click(toggle);
    await user.click(save());

    await waitFor(() => expect(puts(alerts)).toHaveLength(1));
    expect(puts(alerts)[0].body).toEqual({
      goal_enabled: false,
      cost_enabled: true,
      hour: 20,
      frequency: 'daily',
      weekday: null,
    });
  });

  it('keeps a saved cost switch when the limit is gone', async () => {
    const { user, alerts } = await openAlerts({}, { alert: { cost_enabled: true } });

    await user.click(save());

    await waitFor(() => expect(puts(alerts)).toHaveLength(1));
    expect(puts(alerts)[0].body.cost_enabled).toBe(true);
  });
});

describe('habit alerts: when it fires', () => {
  it('explains the pace of an "at least" goal with the example of the week', async () => {
    await openAlerts({ goal_type: 'min', goal_count: 3, goal_period: 'week' });

    expect(screen.getByText('at least 3 times a week.')).toBeTruthy();
    expect(screen.getByText(/^Fires when the habit falls behind the pace of the week:/)).toBeTruthy();
    expect(
      screen.getByText(
        'Example: in a week with no marks, the habit falls behind from Wednesday at 8:00 AM, and the alert goes out at the first check after that.',
      ),
    ).toBeTruthy();
  });

  it('uses the half rule outside the week and counts minutes with the duration', async () => {
    await openAlerts({
      goal_type: 'exact',
      goal_count: 4,
      goal_period: 'month',
      duration_enabled: true,
      duration_minutes: 30,
    });

    expect(
      screen.getByText(/^Fires when the habit goes over the goal of the month or falls behind the pace:/),
    ).toBeTruthy();
    expect(screen.getByText(/exactly 120 min a month\.$/)).toBeTruthy();
    expect(screen.getByText(/^Example: halfway through the period/)).toBeTruthy();
  });

  it.each([
    [{ goal_type: 'max', goal_count: 2 }, 'Fires when the habit reaches or goes over the goal of the week.'],
    [{ goal_type: 'max', goal_count: 0 }, 'Fires on the first mark of the week.'],
    [
      { goal_type: 'min', goal_count: 1 },
      'With this goal, the pace only asks for the mark at the end of the period, so this alert never fires.',
    ],
    [
      { goal_type: 'exact', goal_count: 1, goal_period: 'year' },
      'Fires when the habit goes over the goal of the year. With this goal, the pace only asks for the mark at the end of the period, so falling behind does not fire it.',
    ],
  ])('explains the goal %o', async (goal, text) => {
    await openAlerts(goal);

    const rule = screen.getByText(text);
    expect(screen.getByRole('switch', { name: 'Goal alert' }).getAttribute('aria-describedby')).toContain(
      rule.parentElement.id,
    );
  });

  it('warns about the creation period, one email a day and saving after the hour', async () => {
    await openAlerts({
      created_at: new Date().toISOString(),
      cost_enabled: true,
      cost_cents: 800,
      cost_limit_cents: 10000,
      cost_limit_period: 'year',
    });

    expect(screen.getByText(/^This habit was created this week: this alert can only fire from /)).toBeTruthy();
    expect(screen.getByText(/^This habit was created this year: this alert can only fire from Jan 1, /)).toBeTruthy();
    expect(screen.getByText(/^No alert fires in the period \(week, month or year\) in which the habit was created/)).toBeTruthy();
    expect(screen.getByText('At most 1 email a day goes out for this habit, joining goal and cost.')).toBeTruthy();
    expect(screen.getByText(/^If you save after the chosen hour, today's check does not happen/)).toBeTruthy();
  });

  it('does not repeat the creation warning after that period', async () => {
    await openAlerts();

    expect(screen.queryByText(/^This habit was created this/)).toBeNull();
  });
});

describe('habit alerts: status of the habit', () => {
  it('shows the archived habit read-only', async () => {
    const { container } = await openAlerts(
      { status: 'archived', archived_at: '2026-03-10T15:00:00Z' },
      { alert: { goal_enabled: true } },
    );

    expect(screen.getByText(/^This habit is archived: no alert fires/)).toBeTruthy();
    expect(screen.getByRole('switch', { name: 'Goal alert' }).matches(':disabled')).toBe(true);
    expect(screen.getByLabelText('Hour').matches(':disabled')).toBe(true);
    expect(save().matches(':disabled')).toBe(true);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('says that a paused habit fires nothing', async () => {
    await openAlerts({ status: 'paused' });

    expect(screen.getByText(/^This habit is paused: no alert fires while it is paused/)).toBeTruthy();
    expect(save().matches(':disabled')).toBe(false);
  });

  it('refreshes the habit when the API says it was archived meanwhile', async () => {
    const habits = [habitFixture({ created_at: OLD })];
    signedIn();
    const reads = mockHabitsApi({ habits, marks: {} });
    mockAlertsApi({
      fail: ({ method }) =>
        method === 'PUT' ? HttpResponse.json({ error: 'habit_archived', field: null }, { status: 409 }) : null,
    });
    const user = userEvent.setup();
    renderApp(ALERTS_PATH);
    await screen.findByRole('form', { name: 'Save alerts' });

    habits[0].status = 'archived';
    habits[0].archived_at = '2026-03-10T15:00:00Z';
    const before = reads.requests.length;
    await user.click(save());

    expect((await screen.findByRole('alert')).textContent).toContain('This habit is archived and read-only.');
    await waitFor(() => expect(reads.requests.length).toBeGreaterThan(before));
    expect(await screen.findByText(/^This habit is archived: no alert fires/)).toBeTruthy();
  });
});
