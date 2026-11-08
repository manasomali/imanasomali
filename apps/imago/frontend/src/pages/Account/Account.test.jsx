import { describe, expect, it, vi } from 'vitest';
import { configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { browserTimezone } from '../../lib/time';
import { BASENAME, PATHS } from '../../paths';
import { axe } from '../../test/axe';
import { createTestI18n, translations } from '../../test/i18n';
import { meFixture, renderApp } from '../../test/render';
import { api, apiError, server, trackRequests } from '../../test/server';

// A lista de fusos tem centenas de opções: a tela demora mais que os 5 s padrão com cobertura
vi.setConfig({ testTimeout: 20_000 });

configure({ asyncUtilTimeout: 5_000 });

// Um fuso diferente do do navegador, para o aviso de fuso aparecer (ou não) de propósito
const OTHER_TIMEZONE = browserTimezone() === 'Asia/Tokyo' ? 'Europe/Lisbon' : 'Asia/Tokyo';

const NO_CONTENT = () => new HttpResponse(null, { status: 204 });
const ACCEPTED = () => HttpResponse.json({ status: 'accepted' }, { status: 202 });

/**
 * O /me da conta (com o fuso do navegador, por padrão) e a API de sair: depois de sair, o /me
 * responde 401, como a API de verdade.
 */
function account(overrides = {}) {
  let session = true;
  let me = meFixture({ timezone: browserTimezone(), ...overrides });
  const end = () => {
    session = false;
    return NO_CONTENT();
  };
  server.use(
    http.get(api('/me'), () => (session ? HttpResponse.json(me) : apiError(401, 'unauthorized'))),
    http.post(api('/auth/logout'), end),
    http.post(api('/auth/logout-all'), end),
    http.patch(api('/me'), async ({ request }) => {
      me = { ...me, ...(await request.json()) };
      return HttpResponse.json(me);
    }),
  );
  return { end };
}

async function openAccount(overrides) {
  account(overrides);
  const rendered = renderApp('/');
  await screen.findByRole('heading', { level: 1, name: 'Account' });
  return rendered;
}

function section(name) {
  return screen.getByRole('region', { name });
}

describe('account page', () => {
  it('shows the email, read only, with how to change it through support', async () => {
    const { container } = await openAccount({ support_email: 'ajuda@example.com' });

    const email = section('Email');

    expect(within(email).getByText('ana@example.com')).toBeDefined();
    expect(within(email).queryByRole('textbox')).toBeNull();
    expect(email.textContent).toContain('from the account\'s current email');
    expect(within(email).getByRole('link', { name: 'ajuda@example.com' }).getAttribute('href')).toBe(
      'mailto:ajuda@example.com',
    );
    expect(document.title).toBe('Account · imago');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('lists the applications of GET /me, each with its link and description', async () => {
    await openAccount({ apps: ['ethos', 'engrafi', '../evil'] });

    const apps = section('Your applications');
    const links = within(apps).getAllByRole('link');

    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['ethos', '/ethos/'],
      // Aplicação sem textos no translation.json: o nome cru
      ['engrafi', '/engrafi/'],
    ]);
    expect(apps.textContent).toContain(translations.en.apps.ethos.description);
  });

  it('sends a person without a session to sign in, back here afterwards', async () => {
    server.use(http.get(api('/me'), () => apiError(401, 'unauthorized')));
    const { router, container } = renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeDefined();
    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.login}`);
    expect(router.state.location.search).toBe('?next=/imago/');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows "try again later" when GET /me answers 429', async () => {
    server.use(http.get(api('/me'), () => HttpResponse.html('<html>429</html>', { status: 429 })));
    renderApp('/');

    expect((await screen.findByRole('alert')).textContent).toContain('Too many attempts. Please try again later.');
  });

  it('shows the error in Portuguese too, with a retry', async () => {
    window.localStorage.setItem('i18nextLng', 'pt');
    createTestI18n();
    let fail = true;
    server.use(
      http.get(api('/me'), () => (fail ? apiError(429, 'rate_limited') : HttpResponse.json(meFixture()))),
    );
    const user = userEvent.setup();
    renderApp('/');

    expect((await screen.findByRole('alert')).textContent).toContain('Tente mais tarde.');

    fail = false;
    await user.click(screen.getByRole('button', { name: 'Tentar de novo' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Conta' })).toBeDefined();
  });
});

describe('language and time zone', () => {
  it('saves the language in the account and in the key shared with the site', async () => {
    const requests = trackRequests();
    const user = userEvent.setup();
    const { container } = await openAccount({ locale: 'en' });

    await user.click(within(section('Language')).getByRole('radio', { name: 'Português' }));
    await user.click(screen.getByRole('button', { name: 'Save language' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Conta' })).toBeDefined();
    expect(requests.filter((request) => request.method === 'PATCH')).toEqual([
      { method: 'PATCH', path: '/me', query: {}, body: { locale: 'pt' } },
    ]);
    expect(window.localStorage.getItem('i18nextLng')).toBe('pt');
    expect(document.documentElement.lang).toBe('pt');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('saves the time zone chosen in the searchable IANA list', async () => {
    const requests = trackRequests();
    const user = userEvent.setup();
    await openAccount();

    const timezone = section('Time zone');
    await user.type(within(timezone).getByLabelText('Search time zone (city, region or UTC-03)'), 'lisbon');

    const list = within(timezone).getByLabelText('Time zones');
    expect(within(list).getAllByRole('option').map((option) => option.value)).toContain('Europe/Lisbon');
    await user.selectOptions(list, 'Europe/Lisbon');
    await user.click(within(timezone).getByRole('button', { name: 'Save time zone' }));

    expect(await within(timezone).findByText('Time zone saved.')).toBeDefined();
    expect(requests.filter((request) => request.method === 'PATCH')).toEqual([
      { method: 'PATCH', path: '/me', query: {}, body: { timezone: 'Europe/Lisbon' } },
    ]);
    expect(timezone.textContent).toContain('Current account time zone: Europe/Lisbon');
  });

  it('offers the time zone of the device when it differs from the account', async () => {
    const requests = trackRequests();
    const user = userEvent.setup();
    const { container } = await openAccount({ timezone: OTHER_TIMEZONE });

    const timezone = section('Time zone');
    expect(timezone.textContent).toContain(`This device is in another time zone: ${browserTimezone().replaceAll('_', ' ')}`);
    expect(await axe(container)).toHaveNoViolations();

    await user.click(within(timezone).getByRole('button', { name: "Select this device's time zone" }));
    // Só escolhe: o fuso da conta muda ao salvar
    expect(requests.filter((request) => request.method === 'PATCH')).toEqual([]);
    await user.click(within(timezone).getByRole('button', { name: 'Save time zone' }));

    await waitFor(() =>
      expect(requests.filter((request) => request.method === 'PATCH')).toEqual([
        { method: 'PATCH', path: '/me', query: {}, body: { timezone: browserTimezone() } },
      ]),
    );
  });

  it('does not offer the device time zone when it is the account one', async () => {
    await openAccount();

    expect(within(section('Time zone')).queryByRole('button', { name: "Select this device's time zone" })).toBeNull();
  });

  it('shows the error of an unknown time zone on the list', async () => {
    const user = userEvent.setup();
    await openAccount();
    // Registrado depois: passa na frente do PATCH de account()
    server.use(http.patch(api('/me'), () => apiError(422, 'invalid_timezone', 'timezone')));

    const timezone = section('Time zone');
    await user.click(within(timezone).getByRole('button', { name: 'Save time zone' }));

    expect((await within(timezone).findByRole('alert')).textContent).toContain('Unknown time zone.');
    expect(within(timezone).getByLabelText('Time zones').getAttribute('aria-invalid')).toBe('true');
  });
});

describe('sessions', () => {
  it.each([
    ['Sign out', '/auth/logout'],
    ['Sign out of all devices', '/auth/logout-all'],
  ])('"%s" calls the API and goes back to sign in', async (name, path) => {
    const requests = trackRequests();
    const user = userEvent.setup();
    const { router } = await openAccount();

    await user.click(within(section('Sessions')).getByRole('button', { name }));

    expect(await screen.findByLabelText('Email')).toBeDefined();
    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.login}`);
    expect(requests.filter((request) => request.method === 'POST').map((request) => request.path)).toEqual([path]);
  });
});

describe('account deletion', () => {
  /** API da exclusão: `request` e `remove` decidem as respostas; guarda as chamadas. */
  function deletionApi({ request = ACCEPTED, remove } = {}) {
    const { end } = account();
    const calls = { request: 0, remove: [] };
    server.use(
      http.post(api('/me/delete/request'), () => {
        calls.request += 1;
        return request(calls.request);
      }),
      http.delete(api('/me'), async ({ request: req }) => {
        const body = await req.json();
        calls.remove.push(body);
        return remove ? remove(body) : end();
      }),
    );
    return calls;
  }

  async function startDeletion(user) {
    renderApp('/');
    const deletion = await screen.findByRole('region', { name: 'Delete account' });
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account…' }));
    return deletion;
  }

  async function goToCode(user) {
    const deletion = await startDeletion(user);
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Send code' }));
    await within(deletion).findByLabelText('6-digit code');
    return deletion;
  }

  it('goes from the warning to the exports, the code and the final confirmation', async () => {
    const calls = deletionApi();
    const user = userEvent.setup();
    const { container } = renderApp('/');

    const deletion = await screen.findByRole('region', { name: 'Delete account' });
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account…' }));

    // 1. O que some, em cada aplicação
    expect(within(deletion).getByRole('heading', { name: 'What goes away with the account' })).toBe(document.activeElement);
    expect(deletion.textContent).toContain('your manasomali.com account');
    expect(deletion.textContent).toContain(translations.en.apps.ethos.deletion);
    expect(within(deletion).getByRole('link', { name: 'privacy policy' }).getAttribute('href')).toBe(
      `${BASENAME}${PATHS.privacy}#deletion`,
    );
    expect(await axe(container)).toHaveNoViolations();
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));

    // 2. O export de cada aplicação, em outra aba
    const exportLink = within(deletion).getByRole('link', { name: translations.en.apps.ethos.export_label });
    expect(exportLink.getAttribute('href')).toBe('/ethos/relatorio');
    expect(exportLink.getAttribute('target')).toBe('_blank');
    expect(await axe(container)).toHaveNoViolations();
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));

    // 3. O código vai para o email da conta
    expect(deletion.textContent).toContain('We will send a 6-digit code to ana@example.com');
    await user.click(within(deletion).getByRole('button', { name: 'Send code' }));

    // 4. Código e confirmação final
    const codeInput = await within(deletion).findByLabelText('6-digit code');
    expect(document.activeElement).toBe(codeInput);
    expect(codeInput.getAttribute('inputmode')).toBe('numeric');
    expect(codeInput.getAttribute('autocomplete')).toBe('one-time-code');
    expect(await axe(container)).toHaveNoViolations();
    await user.type(codeInput, '123456');
    await user.click(within(deletion).getByRole('checkbox'));
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account' }));

    // Sessão limpa e de volta à tela de entrar, com o aviso
    expect(await screen.findByText(/Your account was deleted from every application/)).toBeDefined();
    expect(screen.getByLabelText('Email')).toBeDefined();
    expect(calls).toEqual({ request: 1, remove: [{ code: '123456' }] });
    expect(await axe(container)).toHaveNoViolations();
  });

  it('keeps the person on the screen with a wrong code', async () => {
    const calls = deletionApi({ remove: () => apiError(400, 'invalid_code', 'code') });
    const user = userEvent.setup();
    const deletion = await goToCode(user);

    const codeInput = within(deletion).getByLabelText('6-digit code');
    await user.type(codeInput, '000000');
    await user.click(within(deletion).getByRole('checkbox'));
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account' }));

    expect((await within(deletion).findByRole('alert')).textContent).toContain('Invalid or expired code.');
    expect(codeInput.value).toBe('000000');
    expect(codeInput.getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(codeInput);
    expect(screen.getByRole('heading', { level: 1, name: 'Account' })).toBeDefined();
    expect(calls.remove).toEqual([{ code: '000000' }]);
  });

  it('does not send without the code and the final confirmation', async () => {
    const calls = deletionApi();
    const user = userEvent.setup();
    const deletion = await goToCode(user);

    await user.click(within(deletion).getByRole('button', { name: 'Delete my account' }));
    await user.type(within(deletion).getByLabelText('6-digit code'), '123456');
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account' }));

    expect(calls.remove).toEqual([]);
  });

  it('shows the last admin block and hides the send button', async () => {
    deletionApi({ request: () => apiError(409, 'last_admin') });
    const user = userEvent.setup();
    const { container } = renderApp('/');
    const deletion = await screen.findByRole('region', { name: 'Delete account' });
    await user.click(within(deletion).getByRole('button', { name: 'Delete my account…' }));
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Send code' }));

    expect((await within(deletion).findByRole('alert')).textContent).toContain(
      'This is the last active administrator account',
    );
    expect(within(deletion).queryByRole('button', { name: 'Send code' })).toBeNull();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('lets the person use a code already received after a 429', async () => {
    deletionApi({ request: () => apiError(429, 'rate_limited') });
    const user = userEvent.setup();
    const deletion = await startDeletion(user);
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Send code' }));

    expect((await within(deletion).findByRole('alert')).textContent).toContain('Please try again later.');
    await user.click(within(deletion).getByRole('button', { name: 'I already have a code' }));

    expect(within(deletion).getByLabelText('6-digit code')).toBe(document.activeElement);
  });

  it('goes back and cancels, returning the focus to the start button', async () => {
    deletionApi();
    const user = userEvent.setup();
    const deletion = await startDeletion(user);

    await user.click(within(deletion).getByRole('button', { name: 'Continue' }));
    await user.click(within(deletion).getByRole('button', { name: 'Back' }));
    expect(within(deletion).getByRole('heading', { name: 'What goes away with the account' })).toBeDefined();

    await user.click(within(deletion).getByRole('button', { name: 'Cancel' }));

    expect(within(deletion).getByRole('button', { name: 'Delete my account…' })).toBe(document.activeElement);
  });
});

describe('pending terms', () => {
  it('asks for the acceptance and keeps only what works without it', async () => {
    const { container } = await openAccount({ terms_version: '2026-01-01', terms_pending: true });

    const notice = screen.getByRole('region', { name: 'New terms of use' });
    expect(within(notice).getByRole('link', { name: 'Read and accept' }).getAttribute('href')).toBe(
      `${BASENAME}${PATHS.login}?next=/imago/`,
    );
    // PATCH /me responderia 403 terms_not_accepted: sem idioma e fuso
    expect(screen.queryByRole('region', { name: 'Language' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Time zone' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Your applications' })).toBeNull();
    // Sair e excluir a conta funcionam sem o aceite
    expect(section('Sessions')).toBeDefined();
    expect(section('Delete account')).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();
  });
});
