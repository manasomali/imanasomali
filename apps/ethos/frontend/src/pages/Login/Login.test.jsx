import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, configure, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { browserTimezone } from '../../lib/time';
import { BASENAME, PATHS } from '../../paths';
import { axe } from '../../test/axe';
import { createTestI18n } from '../../test/i18n';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

// Os testes que entram vão até a tela de conta (com a lista de fusos) ou a de hábitos, que levam
// mais que os 5 s padrão quando a suíte inteira roda junto, com cobertura
vi.setConfig({ testTimeout: 15_000 });

configure({ asyncUtilTimeout: 5_000 });

const UNAUTHORIZED = { error: 'unauthorized', field: null };

/**
 * API de login falsa. `verify` decide a resposta do POST /auth/code/verify; o /auth/me responde
 * 401 até um verify dar certo. Guarda os corpos recebidos.
 */
function loginApi({ request = () => HttpResponse.json({ status: 'accepted' }, { status: 202 }), verify } = {}) {
  const calls = { request: [], verify: [], me: 0 };
  let signedIn = false;
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
      signedIn = true;
      return HttpResponse.json({ new_account: false });
    }),
    http.get(api('/auth/me'), () => {
      calls.me += 1;
      return signedIn
        ? HttpResponse.json(meFixture({ timezone: browserTimezone() }))
        : HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }),
  );
  return calls;
}

async function askForCode(user, email = 'ana@example.com') {
  await user.type(await screen.findByLabelText('Email'), email);
  await user.click(screen.getByRole('button', { name: 'Send code' }));
  return screen.findByLabelText('6-digit code');
}

afterEach(() => {
  vi.useRealTimers();
});

describe('login', () => {
  it('goes from email to code to the app, back to where the person was', async () => {
    const calls = loginApi();
    const user = userEvent.setup();
    const { router, container } = renderApp('/conta');

    // O 401 do /auth/me leva para o login, guardando a tela
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
    const meCallsBefore = calls.me;
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Account' })).toBeDefined();
    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.account}`);
    expect(calls.verify).toEqual([
      { email: 'Ana@Example.com', code: '123456', timezone: browserTimezone(), locale: 'en' },
    ]);
    // O cache da sessão anterior foi limpo: o /me foi buscado de novo
    expect(calls.me).toBeGreaterThan(meCallsBefore);
  });

  it('goes to the habits screen when there is no page to return to', async () => {
    loginApi();
    const user = userEvent.setup();
    const { router } = renderApp(PATHS.login);

    await askForCode(user);
    await user.type(screen.getByLabelText('6-digit code'), '654321');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Habits' })).toBeDefined();
    expect(router.state.location.pathname).toBe(BASENAME);
  });

  it('shows an error for a wrong code and keeps the field', async () => {
    const calls = loginApi({
      verify: () => HttpResponse.json({ error: 'invalid_code', field: 'code' }, { status: 400 }),
    });
    const user = userEvent.setup();
    const { container } = renderApp(PATHS.login);

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
  });

  it('shows a wait message on 429 and lets the person enter a code already received', async () => {
    const calls = loginApi({
      request: () => HttpResponse.json({ error: 'rate_limited', field: null }, { status: 429 }),
    });
    const user = userEvent.setup();
    const { container } = renderApp(PATHS.login);

    await user.type(await screen.findByLabelText('Email'), 'ana@example.com');
    await user.click(screen.getByRole('button', { name: 'Send code' }));

    expect((await screen.findByRole('alert')).textContent).toContain(
      'Too many attempts. Please try again later.',
    );
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

  it('shows the same nginx 429 (HTML) as a wait message', async () => {
    loginApi({ request: () => HttpResponse.html('<html>429</html>', { status: 429 }) });
    const user = userEvent.setup();
    renderApp(PATHS.login);

    await user.type(await screen.findByLabelText('Email'), 'ana@example.com');
    await user.click(screen.getByRole('button', { name: 'Send code' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Please try again later.');
  });

  it('lets the person resend the code only after 60 seconds', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    const calls = loginApi();
    const user = userEvent.setup();
    renderApp(PATHS.login);

    await askForCode(user);

    const resend = screen.getByRole('button', { name: 'Send a new code in 60 s' });
    expect(resend.disabled).toBe(true);

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
        count === 1
          ? HttpResponse.json({ status: 'accepted' }, { status: 202 })
          : HttpResponse.json({ error: 'rate_limited', field: null }, { status: 429 }),
    });
    const user = userEvent.setup();
    renderApp(PATHS.login);

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
    renderApp(PATHS.login);

    await askForCode(user);
    await user.click(screen.getByRole('button', { name: 'Use another email' }));

    const emailInput = screen.getByLabelText('Email');
    expect(document.activeElement).toBe(emailInput);
    expect(emailInput.value).toBe('ana@example.com');
    expect(screen.queryByLabelText('6-digit code')).toBeNull();
  });

  it('links to the terms and the privacy policy, in a new tab', async () => {
    renderApp(PATHS.login);

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
    const user = userEvent.setup();
    renderApp(PATHS.login);

    await user.type(await screen.findByLabelText('Email'), 'ana@example.com');
    await user.click(screen.getByRole('button', { name: 'Enviar código' }));
    await user.type(await screen.findByLabelText('Código de 6 dígitos'), '123456');
    await user.click(screen.getByRole('button', { name: 'Entrar' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Hábitos' })).toBeDefined();
    expect(calls.verify[0].locale).toBe('pt');
  });
});
