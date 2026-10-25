import { describe, expect, it, onTestFinished, vi } from 'vitest';
import { act, configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { meQueryKey } from '../../api/auth';
import { habitKeys } from '../../api/habits';
import { SUPPORT_EMAIL } from '../../lib/legal';
import { browserTimezone } from '../../lib/time';
import { BASENAME, PATHS } from '../../paths';
import { axe } from '../../test/axe';
import { habitFixture, mockHabitsApi } from '../../test/habits';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

// A lista tem todos os fusos do navegador (~400 opções): o axe e a digitação levam mais tempo
vi.setConfig({ testTimeout: 30_000 });

configure({ asyncUtilTimeout: 5_000 });

const UNAUTHORIZED = { error: 'unauthorized', field: null };

// Um fuso diferente do navegador, para o aviso de fuso aparecer
const OTHER_TIMEZONE = browserTimezone() === 'Asia/Tokyo' ? 'Europe/Lisbon' : 'Asia/Tokyo';

/**
 * API da conta falsa: GET /auth/me (401 depois de sair ou excluir), PATCH /auth/me (aplica o
 * corpo, ou a resposta de `patch(body)`), logout, logout-all e a exclusão (`deleteRequest()` e
 * `deleteMe(body)` decidem as respostas). Guarda as chamadas em `calls`.
 */
function accountApi({ me = {}, patch, deleteRequest, deleteMe } = {}) {
  const calls = { patch: [], logout: 0, logoutAll: 0, deleteRequest: 0, deleteMe: [], me: 0 };
  let current = meFixture(me);
  let signedIn = true;
  server.use(
    http.get(api('/auth/me'), () => {
      calls.me += 1;
      return signedIn ? HttpResponse.json(current) : HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }),
    http.patch(api('/auth/me'), async ({ request }) => {
      const body = await request.json();
      calls.patch.push(body);
      const response = patch?.(body);
      if (response) return response;
      current = { ...current, ...body };
      return HttpResponse.json(current);
    }),
    http.post(api('/auth/logout'), () => {
      calls.logout += 1;
      signedIn = false;
      return new HttpResponse(null, { status: 204 });
    }),
    http.post(api('/auth/logout-all'), () => {
      calls.logoutAll += 1;
      signedIn = false;
      return new HttpResponse(null, { status: 204 });
    }),
    http.post(api('/auth/me/delete/request'), () => {
      calls.deleteRequest += 1;
      return (
        deleteRequest?.(calls.deleteRequest)
        ?? HttpResponse.json({ status: 'accepted' }, { status: 202 })
      );
    }),
    http.delete(api('/auth/me'), async ({ request }) => {
      const body = await request.json();
      calls.deleteMe.push(body);
      const response = deleteMe?.(body);
      if (response) return response;
      signedIn = false;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return calls;
}

async function openAccount(path = PATHS.account) {
  const result = renderApp(path);
  await screen.findByRole('heading', { level: 1, name: 'Account' });
  return result;
}

function section(name) {
  return screen.getByRole('region', { name });
}

describe('account screen', () => {
  it('shows the email read-only, with how to change it through support', async () => {
    accountApi();
    const { container } = await openAccount();

    const email = section('Email');
    expect(email.textContent).toContain('ana@example.com');
    expect(within(email).queryByRole('textbox')).toBeNull();
    const mail = within(email).getByRole('link', { name: SUPPORT_EMAIL });
    expect(mail.getAttribute('href')).toBe(`mailto:${SUPPORT_EMAIL}`);
    expect(email.textContent).toContain("from the account's current email");
    expect(email.textContent).toContain('Lost access to the current email?');
    expect(document.title).toBe('Account · ethos');
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('time zone', () => {
  it('searches the IANA list and saves the chosen time zone with PATCH /me', async () => {
    const calls = accountApi({ me: { timezone: 'America/Sao_Paulo' } });
    const user = userEvent.setup();
    const { container, queryClient } = await openAccount();
    const timezone = section('Time zone');
    const list = within(timezone).getByRole('listbox', { name: 'Time zones' });

    // A conta já vem selecionada
    expect(list.value).toBe('America/Sao_Paulo');
    expect(timezone.textContent).toContain('Current account time zone: America/Sao Paulo (UTC-03:00)');

    await user.type(within(timezone).getByRole('searchbox'), 'lisbon');
    expect(within(list).getAllByRole('option').map((option) => option.value)).toEqual([
      'Europe/Lisbon',
    ]);
    expect(within(timezone).getByText('1 time zone found.')).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();

    await user.selectOptions(list, 'Europe/Lisbon');
    expect(timezone.textContent).toContain('Selected: Europe/Lisbon');
    await user.click(within(timezone).getByRole('button', { name: 'Save time zone' }));

    expect(await within(timezone).findByText('Time zone saved.')).toBeDefined();
    expect(calls.patch).toEqual([{ timezone: 'Europe/Lisbon' }]);
    expect(queryClient.getQueryData(meQueryKey).timezone).toBe('Europe/Lisbon');
    expect(timezone.textContent).toContain('Current account time zone: Europe/Lisbon');
  });

  it('says when the search finds nothing', async () => {
    accountApi();
    const user = userEvent.setup();
    await openAccount();
    const timezone = section('Time zone');

    await user.type(within(timezone).getByRole('searchbox'), 'atlantis');

    expect(within(timezone).getByText('0 time zones found.')).toBeDefined();
    expect(within(timezone).queryAllByRole('option')).toEqual([]);
    // O escolhido continua o mesmo, mesmo fora da lista filtrada
    expect(timezone.textContent).toContain('Selected: America/Sao Paulo');
  });

  it('shows invalid_timezone on the field', async () => {
    const calls = accountApi({
      patch: () =>
        HttpResponse.json({ error: 'invalid_timezone', field: 'timezone' }, { status: 422 }),
    });
    const user = userEvent.setup();
    const { container } = await openAccount();
    const timezone = section('Time zone');
    const list = within(timezone).getByRole('listbox', { name: 'Time zones' });

    await user.selectOptions(list, 'UTC');
    await user.click(within(timezone).getByRole('button', { name: 'Save time zone' }));

    const alert = await within(timezone).findByRole('alert');
    expect(alert.textContent).toContain('Unknown time zone. Choose another one.');
    expect(list.getAttribute('aria-invalid')).toBe('true');
    expect(list.getAttribute('aria-describedby')).toContain(alert.parentElement.id);
    expect(calls.patch).toEqual([{ timezone: 'UTC' }]);
    expect(await axe(container)).toHaveNoViolations();

    // Escolher outro tira o erro
    await user.selectOptions(list, 'Europe/Lisbon');
    expect(within(timezone).queryByRole('alert')).toBeNull();
    expect(list.getAttribute('aria-invalid')).toBe('false');
  });

  it('comes from the time zone notice with the browser time zone selected', async () => {
    const calls = accountApi({ me: { timezone: OTHER_TIMEZONE } });
    mockHabitsApi();
    const user = userEvent.setup();
    const { queryClient } = renderApp(PATHS.home);

    const notice = await screen.findByRole('region', { name: 'Time zone notice' });
    await user.click(within(notice).getByRole('link', { name: 'Change in account' }));
    await screen.findByRole('heading', { level: 1, name: 'Account' });
    const timezone = section('Time zone');

    expect(within(timezone).getByRole('listbox', { name: 'Time zones' }).value).toBe(
      browserTimezone(),
    );
    expect(timezone.textContent).toContain("This device's time zone");
    // Só sugere: nada muda até salvar
    expect(calls.patch).toEqual([]);

    await user.click(within(timezone).getByRole('button', { name: 'Save time zone' }));

    await within(timezone).findByText('Time zone saved.');
    expect(calls.patch).toEqual([{ timezone: browserTimezone() }]);
    // O que a tela inicial buscou no fuso antigo fica velho
    expect(queryClient.getQueryState(habitKeys.list({ archived: false })).isInvalidated).toBe(true);
    expect(timezone.textContent).not.toContain("This device's time zone");
  });

  it('ignores an invalid suggested time zone', async () => {
    accountApi();
    const { router } = renderApp(PATHS.home);
    mockHabitsApi();
    await screen.findByRole('heading', { level: 1 });

    await router.navigate(PATHS.account, { state: { suggestedTimezone: 'Nowhere/City' } });
    await screen.findByRole('heading', { level: 1, name: 'Account' });

    expect(screen.getByRole('listbox', { name: 'Time zones' }).value).toBe('America/Sao_Paulo');
  });
});

describe('language', () => {
  it('saves the language with PATCH /me and switches the screen and the shared key', async () => {
    const calls = accountApi({ me: { locale: 'en' } });
    const user = userEvent.setup();
    const { container } = await openAccount();
    const language = section('Language');

    expect(within(language).getByRole('radio', { name: 'English' }).checked).toBe(true);
    expect(await axe(container)).toHaveNoViolations();

    await user.click(within(language).getByRole('radio', { name: 'Português' }));
    await user.click(within(language).getByRole('button', { name: 'Save language' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Conta' })).toBeDefined();
    expect(calls.patch).toEqual([{ locale: 'pt' }]);
    expect(window.localStorage.getItem('i18nextLng')).toBe('pt');
    expect(document.documentElement.lang).toBe('pt');
    expect(screen.getByText('Idioma salvo.')).toBeDefined();
  });

  it('shows the error and keeps the screen language when saving fails', async () => {
    accountApi({
      me: { locale: 'en' },
      patch: () => HttpResponse.json({ error: 'internal_error', field: null }, { status: 500 }),
    });
    const user = userEvent.setup();
    await openAccount();
    const language = section('Language');

    await user.click(within(language).getByRole('radio', { name: 'Português' }));
    await user.click(within(language).getByRole('button', { name: 'Save language' }));

    expect((await within(language).findByRole('alert')).textContent).toContain(
      'Something went wrong on our side.',
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Account' })).toBeDefined();
  });
});

describe('sign out', () => {
  it('"sign out of all devices" calls the API and goes back to the login', async () => {
    const calls = accountApi();
    const user = userEvent.setup();
    const { router, queryClient } = await openAccount();

    await user.click(
      within(section('Sessions')).getByRole('button', { name: 'Sign out of all devices' }),
    );

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeDefined();
    expect(calls.logoutAll).toBe(1);
    expect(calls.logout).toBe(0);
    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.login}`);
    // Sessão limpa: nada da conta no cache, e o menu não oferece mais "Sair"
    expect(queryClient.getQueryData(meQueryKey)).toBeUndefined();
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
  });

  it('signs out of this device only', async () => {
    const calls = accountApi();
    const user = userEvent.setup();
    await openAccount();

    await user.click(within(section('Sessions')).getByRole('button', { name: 'Sign out' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeDefined();
    expect(calls).toMatchObject({ logout: 1, logoutAll: 0 });
  });

  it('shows the error and stays when signing out fails', async () => {
    accountApi();
    server.use(http.post(api('/auth/logout-all'), () => HttpResponse.error()));
    const user = userEvent.setup();
    await openAccount();
    const sessions = section('Sessions');

    await user.click(within(sessions).getByRole('button', { name: 'Sign out of all devices' }));

    expect((await within(sessions).findByRole('alert')).textContent).toContain('No connection');
    expect(screen.getByRole('heading', { level: 1, name: 'Account' })).toBeDefined();
  });

  it('has a "sign out" button in the menu, only with a session', async () => {
    const calls = accountApi();
    const user = userEvent.setup();
    const { container } = await openAccount();
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });

    expect(await axe(container)).toHaveNoViolations();
    await user.click(within(nav).getByRole('button', { name: 'Sign out' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeDefined();
    expect(calls.logout).toBe(1);
    expect(within(nav).queryByRole('button', { name: 'Sign out' })).toBeNull();
  });

  it('changes the menu button when signing out fails', async () => {
    accountApi();
    server.use(http.post(api('/auth/logout'), () => HttpResponse.error()));
    const user = userEvent.setup();
    await openAccount();
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });

    await user.click(within(nav).getByRole('button', { name: 'Sign out' }));

    expect(await within(nav).findByRole('button', { name: 'Sign out (try again)' })).toBeDefined();
    expect(within(nav).getByRole('status').textContent).toBe('Could not sign out. Try again.');
  });
});

describe('account deletion', () => {
  /** Abre a exclusão e anda até a etapa do código, conferindo a acessibilidade de cada etapa. */
  async function goToCode(user) {
    const deletion = section('Delete account');
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account…' }));

    // 1. O que some
    const warning = await within(deletion).findByRole('heading', {
      name: 'What goes away with the account',
    });
    expect(document.activeElement).toBe(warning);
    expect(await axe(deletion)).toHaveNoViolations();
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));

    // 2. Export opcional
    expect(
      within(deletion).getByRole('heading', { name: 'Take a copy of your data' }),
    ).toBeDefined();
    expect(within(deletion).getByRole('button', { name: 'Export everything (JSON)' })).toBeDefined();
    expect(within(deletion).getByRole('button', { name: 'Export everything (CSV)' })).toBeDefined();
    expect(await axe(deletion)).toHaveNoViolations();
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));

    // 3. Pedir o código
    expect(within(deletion).getByText(/We will send a 6-digit code to ana@example\.com/)).toBeDefined();
    expect(await axe(deletion)).toHaveNoViolations();
    await user.click(within(deletion).getByRole('button', { name: 'Send code' }));

    // 4. Código e confirmação final
    const code = await within(deletion).findByLabelText('6-digit code');
    expect(document.activeElement).toBe(code);
    return { deletion, code };
  }

  it('goes through warning, export, code and final confirmation, then to the login', async () => {
    const calls = accountApi({
      deleteMe: ({ code }) =>
        code === '123456'
          ? null
          : HttpResponse.json({ error: 'invalid_code', field: 'code' }, { status: 400 }),
    });
    mockHabitsApi({
      habits: [habitFixture({ id: 1 }), habitFixture({ id: 2, role: 'editor' })],
      archived: [habitFixture({ id: 3, status: 'archived' })],
    });
    const user = userEvent.setup();
    const { container, router, queryClient } = await openAccount();
    const deletion = section('Delete account');

    await user.click(within(deletion).getByRole('button', { name: 'Delete my account…' }));
    // O aviso conta os hábitos próprios (com os arquivados) e as participações
    expect(
      await within(deletion).findByText(
        'You own 2 habits (archived ones included). You take part in 1 habit of someone else.',
      ),
    ).toBeDefined();
    expect(deletion.textContent).toContain('including the ones made by guests');
    expect(deletion.textContent).toContain('“Removed user”');
    expect(
      within(deletion).getByRole('link', { name: 'privacy policy' }).getAttribute('href'),
    ).toBe(`${BASENAME}${PATHS.privacy}#deletion`);
    await user.click(within(deletion).getByRole('button', { name: 'Cancel' }));

    const { code } = await goToCode(user);
    expect(calls.deleteRequest).toBe(1);
    expect(code.getAttribute('inputmode')).toBe('numeric');
    expect(code.getAttribute('autocomplete')).toBe('one-time-code');
    expect(await axe(container)).toHaveNoViolations();

    // Código errado: mesma tela, mesmo valor, campo marcado e com o foco
    await user.type(code, '000000');
    await user.click(within(deletion).getByRole('checkbox', { name: /I understand/ }));
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account' }));
    const alert = await within(deletion).findByRole('alert');
    expect(alert.textContent).toContain('Invalid or expired code.');
    expect(within(deletion).getByLabelText('6-digit code')).toBe(code);
    expect(code.value).toBe('000000');
    expect(code.getAttribute('aria-invalid')).toBe('true');
    expect(code.getAttribute('aria-describedby')).toContain(alert.parentElement.id);
    expect(document.activeElement).toBe(code);
    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.account}`);
    expect(await axe(container)).toHaveNoViolations();

    // Código certo: conta excluída, sessão limpa e login com o aviso
    await user.clear(code);
    await user.type(code, '123456');
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeDefined();
    expect(calls.deleteMe).toEqual([{ code: '000000' }, { code: '123456' }]);
    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.login}`);
    expect(
      screen.getByText('Your account was deleted. We sent a confirmation to your email.')
        .getAttribute('role'),
    ).toBe('status');
    expect(queryClient.getQueryData(meQueryKey)).toBeUndefined();
    expect(queryClient.getQueryData(['habits'])).toBeUndefined();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('needs the final confirmation before deleting', async () => {
    const calls = accountApi();
    mockHabitsApi();
    const user = userEvent.setup();
    await openAccount();
    const { deletion, code } = await goToCode(user);

    await user.type(code, '123456');
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account' }));

    expect(calls.deleteMe).toEqual([]);
    expect(within(deletion).getByRole('checkbox', { name: /I understand/ }).required).toBe(true);
  });

  it('shows the block message to the last admin', async () => {
    const calls = accountApi({
      me: { is_admin: true },
      deleteRequest: () => HttpResponse.json({ error: 'last_admin', field: null }, { status: 409 }),
    });
    mockHabitsApi();
    const user = userEvent.setup();
    const { container } = await openAccount();
    const deletion = section('Delete account');

    await user.click(within(deletion).getByRole('button', { name: 'Delete my account…' }));
    await user.click(await within(deletion).findByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Send code' }));

    expect((await within(deletion).findByRole('alert')).textContent).toContain(
      'This is the last active administrator account and cannot be deleted.',
    );
    expect(within(deletion).queryByRole('button', { name: 'Send code' })).toBeNull();
    expect(within(deletion).queryByLabelText('6-digit code')).toBeNull();
    expect(calls.deleteRequest).toBe(1);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('lets the person enter a code already received when sending hits the limit', async () => {
    const calls = accountApi({
      deleteRequest: () =>
        HttpResponse.json({ error: 'rate_limited', field: null }, { status: 429 }),
    });
    mockHabitsApi();
    const user = userEvent.setup();
    await openAccount();
    const deletion = section('Delete account');

    await user.click(within(deletion).getByRole('button', { name: 'Delete my account…' }));
    await user.click(await within(deletion).findByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Send code' }));

    expect((await within(deletion).findByRole('alert')).textContent).toContain('Too many attempts');
    await user.click(within(deletion).getByRole('button', { name: 'I already have a code' }));

    expect(await within(deletion).findByLabelText('6-digit code')).toBe(document.activeElement);
    expect(calls.deleteRequest).toBe(1);
    // Sem contagem: o reenvio fica liberado
    expect(within(deletion).getByRole('button', { name: 'Send another code' }).disabled).toBe(false);
  });

  it('resends the code only after 60 seconds, and cancel goes back to the start', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    onTestFinished(() => vi.useRealTimers());
    const calls = accountApi();
    mockHabitsApi();
    const user = userEvent.setup();
    await openAccount();
    const { deletion } = await goToCode(user);

    expect(
      within(deletion).getByRole('button', { name: 'Send another code in 60 s' }).disabled,
    ).toBe(true);
    act(() => vi.advanceTimersByTime(60_000));
    await user.click(within(deletion).getByRole('button', { name: 'Send another code' }));

    expect(await within(deletion).findByText('We sent a new code.')).toBeDefined();
    expect(calls.deleteRequest).toBe(2);
    expect(
      within(deletion).getByRole('button', { name: 'Send another code in 60 s' }).disabled,
    ).toBe(true);

    // Cancelar fecha as etapas e devolve o foco ao botão que as abriu
    await user.click(within(deletion).getByRole('button', { name: 'Cancel' }));
    expect(document.activeElement).toBe(
      within(deletion).getByRole('button', { name: 'Delete my account…' }),
    );
    expect(within(deletion).queryByLabelText('6-digit code')).toBeNull();
  });

  it('goes back between steps and cancels', async () => {
    accountApi();
    mockHabitsApi();
    const user = userEvent.setup();
    await openAccount();
    const deletion = section('Delete account');

    await user.click(within(deletion).getByRole('button', { name: 'Delete my account…' }));
    await user.click(await within(deletion).findByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    expect(within(deletion).getByRole('listitem', { current: 'step' }).textContent).toBe('3. Code');

    await user.click(within(deletion).getByRole('button', { name: 'Back' }));
    expect(within(deletion).getByRole('listitem', { current: 'step' }).textContent).toBe(
      '2. Your data',
    );
    await user.click(within(deletion).getByRole('button', { name: 'Back' }));
    expect(within(deletion).getByRole('listitem', { current: 'step' }).textContent).toBe(
      '1. What goes away',
    );

    await user.click(within(deletion).getByRole('button', { name: 'Cancel' }));
    await waitFor(() =>
      expect(within(deletion).queryByRole('heading', { level: 3 })).toBeNull(),
    );
  });
});
