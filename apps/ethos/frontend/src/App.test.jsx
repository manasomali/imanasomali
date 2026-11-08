import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { page } from './lib/page';
import { browserTimezone } from './lib/time';
import { BASENAME, IMAGO_PATHS, LEGACY_REDIRECTS } from './paths';
import { axe } from './test/axe';
import { createTestI18n } from './test/i18n';
import { meFixture, renderApp } from './test/render';
import { activeBanner, api, receivedInvites, server } from './test/server';

const OTHER_TIMEZONE = browserTimezone() === 'Asia/Tokyo' ? 'Europe/Lisbon' : 'Asia/Tokyo';

/**
 * GET /me devolvendo o usuário dado, sem hábitos, e registrando qualquer outra chamada que chegar
 * na API.
 */
function signedIn(overrides = {}) {
  const writes = [];
  server.use(
    http.get(api('/me'), () => HttpResponse.json(meFixture(overrides))),
    activeBanner(),
    receivedInvites(),
    http.get(api('/habits'), () => HttpResponse.json({ habits: [] })),
    http.all(api('/*'), ({ request }) => {
      writes.push(`${request.method} ${new URL(request.url).pathname}`);
      return HttpResponse.json({ error: 'not_found', field: null }, { status: 404 });
    }),
  );
  return writes;
}

describe('app shell', () => {
  it('renders the home screen inside the layout', async () => {
    signedIn({ timezone: browserTimezone() });
    const { container } = renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Habits' })).toBeDefined();
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeDefined();
    expect(screen.getByRole('link', { name: 'Skip to content' }).getAttribute('href')).toBe('#content');
    expect(document.title).toBe('Habits · ethos');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('links back to the site outside the /ethos basename', async () => {
    signedIn({ timezone: browserTimezone() });
    renderApp('/');
    await screen.findByRole('heading', { level: 1 });

    const links = screen.getAllByRole('link', { name: /manasomali\.com/ });

    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(link.getAttribute('href')).toBe('/');
  });

  it('links to the account, the terms and the privacy of the imago, outside the basename', async () => {
    signedIn({ timezone: browserTimezone() });
    renderApp('/');
    await screen.findByRole('heading', { level: 1 });

    expect(screen.getByRole('link', { name: 'Account' }).getAttribute('href')).toBe('/imago/');
    const footer = screen.getByRole('navigation', { name: 'Legal texts' });
    expect(within(footer).getByRole('link', { name: 'Terms of use' }).getAttribute('href')).toBe('/imago/termos');
    expect(within(footer).getByRole('link', { name: 'Privacy policy' }).getAttribute('href')).toBe(
      '/imago/privacidade',
    );
    // Sem "Sair" no ethos: sair fica na conta do imago
    expect(screen.queryByRole('button', { name: /Sign out/ })).toBeNull();
  });

  it('opens and closes the menu on small screens', async () => {
    signedIn({ timezone: browserTimezone() });
    const user = userEvent.setup();
    renderApp('/');
    await screen.findByRole('heading', { level: 1 });

    const toggle = screen.getByRole('button', { name: 'Open menu' });
    await user.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(toggle.getAttribute('aria-label')).toBe('Close menu');

    await user.keyboard('{Escape}');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
  });

  it('shows a not found page for unknown routes', async () => {
    const { container } = renderApp('/nada-aqui');

    expect(await screen.findByRole('heading', { level: 1, name: 'Page not found' })).toBeDefined();
    expect(screen.getByRole('link', { name: 'Back to habits' }).getAttribute('href')).toBe(BASENAME);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('theme and language', () => {
  it('starts with the theme saved by the site and toggles it in the shared key', async () => {
    window.localStorage.setItem('theme', 'dark');
    document.documentElement.dataset.theme = 'dark';
    signedIn({ timezone: browserTimezone() });
    const user = userEvent.setup();
    renderApp('/');
    await screen.findByRole('heading', { level: 1 });

    await user.click(screen.getByRole('button', { name: 'Use light theme' }));

    expect(window.localStorage.getItem('theme')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(screen.getByRole('button', { name: 'Use dark theme' })).toBeDefined();
  });

  it('switches the language and saves it in the shared key', async () => {
    signedIn({ timezone: browserTimezone() });
    const user = userEvent.setup();
    const { container } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Habits' });

    const languages = screen.getByRole('group', { name: 'Language' });
    await user.click(within(languages).getByRole('button', { name: 'pt' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Hábitos' })).toBeDefined();
    expect(window.localStorage.getItem('i18nextLng')).toBe('pt');
    expect(document.documentElement.lang).toBe('pt');
    expect(within(languages).getByRole('button', { name: 'pt' }).getAttribute('aria-pressed')).toBe('true');
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('API errors', () => {
  it('sends a 401 to the imago login, with the page in next', async () => {
    server.use(
      http.get(api('/me'), () =>
        HttpResponse.json({ error: 'not_authenticated', field: null }, { status: 401 }),
      ),
    );
    const { container } = renderApp('/relatorio?from=2026-01-01#fim');

    await waitFor(() => {
      expect(page.assign).toHaveBeenCalledExactlyOnceWith(
        `/imago/entrar?next=${encodeURIComponent('/ethos/relatorio?from=2026-01-01#fim')}`,
      );
    });
    // Nada da tela aparece (nem um erro)
    expect(screen.queryByRole('alert')).toBeNull();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows "try again later" on 429', async () => {
    server.use(
      http.get(api('/me'), () =>
        HttpResponse.html('<html>429 Too Many Requests</html>', { status: 429 }),
      ),
    );
    const { container } = renderApp('/');

    const alert = await screen.findByRole('alert');

    expect(alert.textContent).toContain('Too many attempts. Please try again later.');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('translates 403 by its code and shows a generic message for an unknown code', async () => {
    let code = 'forbidden';
    server.use(
      http.get(api('/me'), () => HttpResponse.json({ error: code, field: null }, { status: 403 })),
    );
    const user = userEvent.setup();
    renderApp('/');

    expect((await screen.findByRole('alert')).textContent).toContain(
      'You do not have permission to do this.',
    );

    code = 'brand_new_code';
    await user.click(screen.getByRole('button', { name: 'Try again' }));

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('Something went wrong. Try again.');
    });
  });

  it('shows the error in Portuguese too', async () => {
    window.localStorage.setItem('i18nextLng', 'pt');
    createTestI18n();
    server.use(
      http.get(api('/me'), () =>
        HttpResponse.json({ error: 'rate_limited', field: null }, { status: 429 }),
      ),
    );
    renderApp('/');

    expect((await screen.findByRole('alert')).textContent).toContain('Tente mais tarde.');
  });
});

describe('time zone notice', () => {
  it('suggests changing the account time zone when the browser is elsewhere', async () => {
    const writes = signedIn({ timezone: OTHER_TIMEZONE });
    const { router, container } = renderApp('/');

    const notice = await screen.findByRole('region', { name: 'Time zone notice' });

    expect(notice.textContent).toContain(OTHER_TIMEZONE);
    expect(notice.textContent).toContain(browserTimezone());
    expect(await axe(container)).toHaveNoViolations();

    // A troca é na conta do imago: link comum, fora do app
    expect(within(notice).getByRole('link', { name: 'Change in account' }).getAttribute('href')).toBe(
      IMAGO_PATHS.account,
    );
    expect(router.state.location.pathname).toBe(`${BASENAME}/`);
    // Só sugere: o fuso da conta não muda sozinho
    expect(writes).toEqual([]);
  });

  it('does not show the notice when the time zones match', async () => {
    const writes = signedIn({ timezone: browserTimezone() });
    renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Habits' });

    expect(screen.queryByRole('region', { name: 'Time zone notice' })).toBeNull();
    expect(writes).toEqual([]);
  });

  it('"not now" hides the notice for that pair of time zones', async () => {
    signedIn({ timezone: OTHER_TIMEZONE });
    const user = userEvent.setup();
    renderApp('/');
    const notice = await screen.findByRole('region', { name: 'Time zone notice' });

    await user.click(within(notice).getByRole('button', { name: 'Not now' }));

    expect(screen.queryByRole('region', { name: 'Time zone notice' })).toBeNull();
    expect(window.localStorage.getItem('ethos:timezone-notice-dismissed')).toBe(
      `${OTHER_TIMEZONE}|${browserTimezone()}`,
    );
  });
});

describe('routes of the login of before the imago', () => {
  it.each(Object.entries(LEGACY_REDIRECTS))('sends %s to %s in the imago', async (path, to) => {
    const { container } = renderApp(path);

    expect((await screen.findByRole('link', { name: 'Going to your manasomali.com account…' })).getAttribute('href')).toBe(to);
    await waitFor(() => expect(page.replace).toHaveBeenCalledExactlyOnceWith(to));
    expect(page.assign).not.toHaveBeenCalled();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('covers the old login, terms, privacy and account', () => {
    expect(LEGACY_REDIRECTS).toEqual({
      '/entrar': '/imago/entrar',
      '/termos': '/imago/termos',
      '/privacidade': '/imago/privacidade',
      '/conta': '/imago/',
    });
  });
});
