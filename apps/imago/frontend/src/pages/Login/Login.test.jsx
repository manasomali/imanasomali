import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, configure, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { TERMS_VERSION } from '../../lib/legal';
import { pageLocation } from '../../lib/location';
import { browserTimezone } from '../../lib/time';
import { BASENAME, PATHS } from '../../paths';
import { axe } from '../../test/axe';
import { createTestI18n } from '../../test/i18n';
import { meFixture, renderApp, signedIn } from '../../test/render';
import { api, apiError, server } from '../../test/server';

// Os testes que entram vão até a tela de conta (com a lista de fusos), que leva mais que os 5 s
// padrão quando a suíte inteira roda junto, com cobertura
vi.setConfig({ testTimeout: 15_000 });

configure({ asyncUtilTimeout: 5_000 });

const NEXT = '/ethos/habits/3?day=2026-03-04';

/**
 * API de login falsa. `verify` e `request` decidem as respostas; o /me responde 401 até um verify
 * dar certo e depois devolve `me` (com termos pendentes, se for o caso). Guarda os corpos recebidos.
 */
function loginApi({
  request = () => HttpResponse.json({ status: 'accepted' }, { status: 202 }),
  verify,
  me = meFixture({ timezone: browserTimezone() }),
} = {}) {
  const calls = { request: [], verify: [], me: 0 };
  let session = false;
  server.use(
    http.post(api('/auth/code/request'), async ({ request: req }) => {
      calls.request.push(await req.json());
      return request(calls.request.length);
    }),
    http.post(api('/auth/code/verify'), async ({ request: req }) => {
      const body = await req.json();
      calls.verify.push(body);
      const response = verify ? verify(body) : null;
      if (response) return response;
      session = true;
      return HttpResponse.json({ new_account: false });
    }),
    http.get(api('/me'), () => {
      calls.me += 1;
      return session ? HttpResponse.json(me) : apiError(401, 'unauthorized');
    }),
  );
  return calls;
}

/** POST /me/terms: guarda os corpos e responde com `respond` (por padrão, o /me com os termos em dia). */
function termsApi(respond = () => HttpResponse.json(meFixture({ timezone: browserTimezone() }))) {
  const bodies = [];
  server.use(
    http.post(api('/me/terms'), async ({ request }) => {
      bodies.push(await request.json());
      return respond(bodies.length);
    }),
  );
  return bodies;
}

/** Troca a navegação de página inteira (o jsdom não navega). */
function mockLeave() {
  return vi.spyOn(pageLocation, 'replace').mockImplementation(() => {});
}

function loginAt(next) {
  return renderApp(next === undefined ? PATHS.login : `${PATHS.login}?next=${encodeURIComponent(next)}`);
}

async function askForCode(user, email = 'ana@example.com') {
  await user.type(await screen.findByLabelText('Email'), email);
  await user.click(screen.getByRole('button', { name: 'Send code' }));
  return screen.findByLabelText('6-digit code');
}

async function signInWithCode(user, code = '123456') {
  await askForCode(user);
  await user.type(screen.getByLabelText('6-digit code'), code);
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
}

afterEach(() => {
  vi.useRealTimers();
});

describe('sign in with a code', () => {
  it('goes from email to code and back to the application in `next`', async () => {
    const calls = loginApi();
    const leave = mockLeave();
    const user = userEvent.setup();
    const { container } = loginAt(NEXT);

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();

    const codeInput = await askForCode(user, '  Ana@Example.com ');

    expect(calls.request).toEqual([{ email: 'Ana@Example.com' }]);
    expect(codeInput.getAttribute('inputmode')).toBe('numeric');
    expect(codeInput.getAttribute('autocomplete')).toBe('one-time-code');
    expect(document.activeElement).toBe(codeInput);
    expect(screen.getByText(/We sent a 6-digit code to Ana@Example\.com/)).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();

    // Colado com espaço: só os dígitos ficam
    await user.click(codeInput);
    await user.paste('123 456');
    expect(codeInput.value).toBe('123456');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => expect(leave).toHaveBeenCalledWith(NEXT));
    expect(leave).toHaveBeenCalledTimes(1);
    // O fuso do navegador e o idioma da tela vão no verify (usados só numa conta nova)
    expect(calls.verify).toEqual([
      { email: 'Ana@Example.com', code: '123456', timezone: browserTimezone(), locale: 'en' },
    ]);
    expect(screen.getByRole('status').textContent).toBe('Taking you back…');
  });

  it('goes to the account page without a `next`', async () => {
    loginApi();
    const leave = mockLeave();
    const user = userEvent.setup();
    const { router } = loginAt();

    await signInWithCode(user);

    await waitFor(() => expect(router.state.location.pathname).toBe(BASENAME));
    expect(router.state.historyAction).toBe('REPLACE');
    expect(leave).not.toHaveBeenCalled();
  });

  it('goes back to a screen of the imago itself without reloading the page', async () => {
    loginApi({ me: meFixture({ timezone: browserTimezone(), is_admin: true }) });
    server.use(
      http.get(api('/admin/users'), () => HttpResponse.json({ users: [], next_cursor: null })),
      http.get(api('/admin/mail'), () => HttpResponse.json({ window_hours: 24, by_app: [], day: {}, hour: {} })),
    );
    const leave = mockLeave();
    const user = userEvent.setup();
    const { router } = loginAt('/imago/admin?status=blocked');

    await signInWithCode(user);

    await waitFor(() => expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.admin}`));
    expect(router.state.location.search).toBe('?status=blocked');
    expect(leave).not.toHaveBeenCalled();
  });

  it('shows an error for a wrong code and keeps the field', async () => {
    const calls = loginApi({ verify: () => apiError(400, 'invalid_code', 'code') });
    const leave = mockLeave();
    const user = userEvent.setup();
    const { container } = loginAt(NEXT);

    const codeInput = await askForCode(user);
    await user.type(codeInput, '000000');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Invalid or expired code. Check the code or request a new one.');
    // Mesma etapa, mesmo valor, marcado como inválido e com o foco para corrigir
    expect(screen.getByLabelText('6-digit code')).toBe(codeInput);
    expect(codeInput.value).toBe('000000');
    expect(codeInput.getAttribute('aria-invalid')).toBe('true');
    expect(codeInput.getAttribute('aria-describedby')).toContain(alert.parentElement.id);
    expect(document.activeElement).toBe(codeInput);
    expect(await axe(container)).toHaveNoViolations();

    // Corrigir o código tira o erro; a segunda tentativa é outra chamada
    await user.clear(codeInput);
    expect(screen.queryByRole('alert')).toBeNull();
    await user.type(codeInput, '111111');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    await screen.findByRole('alert');
    expect(calls.verify.map((body) => body.code)).toEqual(['000000', '111111']);
    expect(leave).not.toHaveBeenCalled();
  });

  it('shows a wait message on 429 and lets the person enter a code already received', async () => {
    const calls = loginApi({ request: () => apiError(429, 'rate_limited') });
    const user = userEvent.setup();
    const { container } = loginAt();

    await user.type(await screen.findByLabelText('Email'), 'ana@example.com');
    await user.click(screen.getByRole('button', { name: 'Send code' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Too many attempts. Please try again later.');
    // O erro não é do email: o campo não fica inválido
    expect(screen.getByLabelText('Email').getAttribute('aria-invalid')).toBe('false');
    expect(await axe(container)).toHaveNoViolations();

    await user.click(screen.getByRole('button', { name: 'I already have a code' }));

    const codeInput = screen.getByLabelText('6-digit code');
    expect(document.activeElement).toBe(codeInput);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('button', { name: /^Send a new code in \d+ s$/ }).disabled).toBe(true);
    expect(calls.request).toHaveLength(1);
  });

  it('shows the nginx 429 (HTML) as a wait message too', async () => {
    loginApi({ request: () => HttpResponse.html('<html>429</html>', { status: 429 }) });
    const user = userEvent.setup();
    loginAt();

    await user.type(await screen.findByLabelText('Email'), 'ana@example.com');
    await user.click(screen.getByRole('button', { name: 'Send code' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Please try again later.');
  });

  it('gives the same answer for any email (no hint that the account exists)', async () => {
    loginApi();
    const user = userEvent.setup();
    loginAt();

    await askForCode(user, 'nobody@example.com');

    expect(screen.getByText(/We sent a 6-digit code to nobody@example\.com/)).toBeDefined();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('lets the person resend the code only after 60 seconds', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    const calls = loginApi();
    const user = userEvent.setup();
    loginAt();

    await askForCode(user);

    expect(screen.getByRole('button', { name: 'Send a new code in 60 s' }).disabled).toBe(true);

    act(() => vi.advanceTimersByTime(59_000));
    expect(screen.getByRole('button', { name: 'Send a new code in 1 s' }).disabled).toBe(true);

    act(() => vi.advanceTimersByTime(1_000));
    const enabled = screen.getByRole('button', { name: 'Send a new code' });
    expect(enabled.disabled).toBe(false);

    await user.click(enabled);

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('We sent a new code.'));
    expect(calls.request).toEqual([{ email: 'ana@example.com' }, { email: 'ana@example.com' }]);
    expect(screen.getByRole('button', { name: 'Send a new code in 60 s' }).disabled).toBe(true);
  });

  it('shows the resend error on the code step', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    loginApi({
      request: (count) =>
        count === 1 ? HttpResponse.json({ status: 'accepted' }, { status: 202 }) : apiError(429, 'rate_limited'),
    });
    const user = userEvent.setup();
    loginAt();

    await askForCode(user);
    act(() => vi.advanceTimersByTime(60_000));
    await user.click(screen.getByRole('button', { name: 'Send a new code' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Please try again later.');
    expect(screen.getByRole('status').textContent).toBe('');
    expect(screen.getByLabelText('6-digit code')).toBeDefined();
  });

  it('goes back to the email to use another one', async () => {
    loginApi();
    const user = userEvent.setup();
    loginAt();

    await askForCode(user);
    await user.click(screen.getByRole('button', { name: 'Use another email' }));

    const emailInput = screen.getByLabelText('Email');
    expect(document.activeElement).toBe(emailInput);
    expect(emailInput.value).toBe('ana@example.com');
    expect(screen.queryByLabelText('6-digit code')).toBeNull();
  });

  it('says that continuing means agreeing to the terms, with links in a new tab', async () => {
    loginApi();
    loginAt();

    const notice = (await screen.findByText(/By continuing, you agree to the/)).closest('p');
    const terms = screen.getByRole('link', { name: 'terms of use' });
    const privacy = screen.getByRole('link', { name: 'privacy policy' });

    expect(notice.contains(terms) && notice.contains(privacy)).toBe(true);
    expect(terms.getAttribute('href')).toBe(`${BASENAME}${PATHS.terms}`);
    expect(privacy.getAttribute('href')).toBe(`${BASENAME}${PATHS.privacy}`);
    for (const link of [terms, privacy]) {
      expect(link.getAttribute('target')).toBe('_blank');
      expect(link.getAttribute('rel')).toBe('noreferrer');
    }
  });

  it('sends the screen language as the locale of a new account', async () => {
    window.localStorage.setItem('i18nextLng', 'pt');
    createTestI18n();
    const calls = loginApi();
    const leave = mockLeave();
    const user = userEvent.setup();
    loginAt(NEXT);

    await user.type(await screen.findByLabelText('Email'), 'ana@example.com');
    await user.click(screen.getByRole('button', { name: 'Enviar código' }));
    await user.type(await screen.findByLabelText('Código de 6 dígitos'), '123456');
    await user.click(screen.getByRole('button', { name: 'Entrar' }));

    await waitFor(() => expect(leave).toHaveBeenCalledWith(NEXT));
    expect(calls.verify[0].locale).toBe('pt');
  });

  it('says so when the browser does not keep the session after the code', async () => {
    const calls = loginApi();
    // O verify dá certo, mas o /me continua sem sessão (cookie não guardado)
    server.use(http.get(api('/me'), () => apiError(401, 'unauthorized')));
    const leave = mockLeave();
    const user = userEvent.setup();
    const { container } = loginAt(NEXT);

    await signInWithCode(user);

    expect((await screen.findByRole('alert')).textContent).toContain('this browser did not keep the session');
    expect(screen.getByLabelText('6-digit code').getAttribute('aria-invalid')).toBe('false');
    expect(screen.getByRole('button', { name: 'Sign in' }).disabled).toBe(false);
    expect(calls.verify).toHaveLength(1);
    expect(leave).not.toHaveBeenCalled();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('does not send an incomplete code', async () => {
    const calls = loginApi();
    const user = userEvent.setup();
    loginAt();

    await askForCode(user);
    await user.type(screen.getByLabelText('6-digit code'), '123');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(calls.verify).toEqual([]);
  });

  it('shows an error with a retry when the session check fails', async () => {
    let fail = true;
    server.use(
      http.get(api('/me'), () => (fail ? HttpResponse.error() : apiError(401, 'unauthorized'))),
    );
    const user = userEvent.setup();
    const { container } = loginAt();

    expect((await screen.findByRole('alert', {}, { timeout: 10_000 })).textContent).toContain(
      'No connection to the server.',
    );
    expect(await axe(container)).toHaveNoViolations();

    fail = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));

    expect(await screen.findByLabelText('Email')).toBeDefined();
  });
});

describe('the `next` parameter', () => {
  // ETH-31: nenhum destes sai do site; todos vão para a tela de conta
  it.each([
    ['//evil.com', 'next=//evil.com'],
    ['https://evil.com', 'next=https://evil.com'],
    ['/\\evil.com', 'next=/\\evil.com'],
    ['/%09/evil.com (tab)', 'next=/%09/evil.com'],
    ['/imago/entrar', 'next=/imago/entrar'],
  ])('sends %s to /imago/', async (_, query) => {
    signedIn(meFixture({ timezone: browserTimezone() }));
    const leave = mockLeave();
    const { router } = renderApp(`${PATHS.login}?${query}`);

    await waitFor(() => expect(router.state.location.pathname).toBe(BASENAME));
    expect(router.state.location.search).toBe('');
    expect(leave).not.toHaveBeenCalled();
  });

  it('sends a signed-in person with the terms up to date straight to `next`, without a code', async () => {
    const calls = loginApi();
    signedIn(meFixture());
    const leave = mockLeave();
    loginAt(NEXT);

    await waitFor(() => expect(leave).toHaveBeenCalledWith(NEXT));
    expect(screen.queryByLabelText('Email')).toBeNull();
    expect(calls.request).toEqual([]);
  });

  it('checks the session again even with a signed-in user in the cache', async () => {
    let session = true;
    server.use(
      http.get(api('/me'), () =>
        session ? HttpResponse.json(meFixture({ timezone: browserTimezone() })) : apiError(401, 'unauthorized'),
      ),
    );
    const leave = mockLeave();
    // Com sessão, a tela de entrar vai para a conta e deixa o /me no cache
    const { router } = loginAt();
    await waitFor(() => expect(router.state.location.pathname).toBe(BASENAME));

    // A sessão acaba; uma ida à tela de entrar não pode voltar para o `next` pelo cache
    session = false;
    await act(() => router.navigate(`${PATHS.login}?next=${encodeURIComponent(NEXT)}`));

    expect(await screen.findByLabelText('Email')).toBeDefined();
    expect(leave).not.toHaveBeenCalled();
  });
});

describe('new terms', () => {
  const pending = meFixture({ terms_version: '2026-01-01', terms_pending: true });

  it('shows only the acceptance to a signed-in person, and goes to `next` after accepting', async () => {
    const calls = loginApi();
    signedIn(pending);
    const bodies = termsApi();
    const leave = mockLeave();
    const user = userEvent.setup();
    const { container } = loginAt(NEXT);

    expect(await screen.findByRole('heading', { level: 1, name: 'New terms of use' })).toBeDefined();
    expect(screen.queryByLabelText('Email')).toBeNull();
    expect(screen.getByText('Signed in as ana@example.com.')).toBeDefined();
    expect(screen.getByText(`Version ${TERMS_VERSION}`)).toBeDefined();
    const texts = screen.getByRole('list', { name: 'Texts (open in a new tab)' });
    expect(texts.textContent).toContain('Terms of use');
    expect(texts.textContent).toContain('Privacy policy');
    expect(await axe(container)).toHaveNoViolations();
    // O aceite bloqueia a volta: nada de navegar antes dele
    expect(leave).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Accept and continue' }));

    await waitFor(() => expect(leave).toHaveBeenCalledWith(NEXT));
    expect(bodies).toEqual([{ terms_version: TERMS_VERSION }]);
    expect(calls.request).toEqual([]);
  });

  it('asks for the acceptance right after the code when the terms are pending', async () => {
    loginApi({ me: pending });
    termsApi();
    const leave = mockLeave();
    const user = userEvent.setup();
    loginAt(NEXT);

    await signInWithCode(user);

    expect(await screen.findByRole('heading', { level: 1, name: 'New terms of use' })).toBeDefined();
    expect(leave).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Accept and continue' }));

    await waitFor(() => expect(leave).toHaveBeenCalledWith(NEXT));
  });

  it('asks to reload when the backend has a newer version (409)', async () => {
    let me = pending;
    server.use(http.get(api('/me'), () => HttpResponse.json(me)));
    termsApi(() => {
      me = { ...pending, current_terms_version: '2099-01-01' };
      return apiError(409, 'conflict', 'terms_version');
    });
    const reload = vi.spyOn(pageLocation, 'reload').mockImplementation(() => {});
    const leave = mockLeave();
    const user = userEvent.setup();
    const { container } = loginAt(NEXT);

    await user.click(await screen.findByRole('button', { name: 'Accept and continue' }));

    expect(await screen.findByText(/A newer version of the terms was published/)).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Accept and continue' })).toBeNull();
    expect(await axe(container)).toHaveNoViolations();

    await user.click(screen.getByRole('button', { name: 'Reload page' }));

    expect(reload).toHaveBeenCalledTimes(1);
    expect(leave).not.toHaveBeenCalled();
  });

  it('signs out from the acceptance, back to the email', async () => {
    let session = true;
    server.use(
      http.get(api('/me'), () => (session ? HttpResponse.json(pending) : apiError(401, 'unauthorized'))),
      http.post(api('/auth/logout'), () => {
        session = false;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    loginAt(NEXT);

    await user.click(await screen.findByRole('button', { name: 'Sign out' }));

    expect(await screen.findByLabelText('Email')).toBeDefined();
    expect(screen.getByRole('heading', { level: 1, name: 'Sign in' })).toBeDefined();
  });

  it('points to the account page to delete the account without accepting', async () => {
    signedIn(pending);
    loginAt(NEXT);

    const link = await screen.findByRole('link', { name: 'account page' });

    expect(link.getAttribute('href')).toBe(BASENAME);
  });
});
