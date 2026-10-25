import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { TERMS_VERSION } from '../../lib/legal';
import { browserTimezone } from '../../lib/time';
import { BASENAME, PATHS } from '../../paths';
import { axe } from '../../test/axe';
import { meFixture, renderApp } from '../../test/render';
import { activeBanner, api, server } from '../../test/server';

const PENDING = { terms_version: '2025-01-01', terms_pending: true, timezone: browserTimezone() };

/** /auth/me com termos por aceitar; registra as chamadas. `accept` decide a resposta do aceite. */
function pendingTerms({ accept, me = PENDING } = {}) {
  const calls = { accepted: [], logout: 0, other: [] };
  let current = meFixture(me);
  server.use(
    http.get(api('/auth/me'), () => HttpResponse.json(current)),
    http.post(api('/auth/me/terms'), async ({ request }) => {
      const body = await request.json();
      calls.accepted.push(body);
      const response = accept?.(body);
      if (response) {
        if (response.me) current = response.me;
        return response.http;
      }
      current = meFixture({ ...me, terms_version: body.terms_version, terms_pending: false });
      return HttpResponse.json(current);
    }),
    http.post(api('/auth/logout'), () => {
      calls.logout += 1;
      return new HttpResponse(null, { status: 204 });
    }),
    // O banner é público e fica no Layout, fora da tela bloqueada
    activeBanner(),
    // Qualquer outra chamada seria da tela bloqueada
    http.all(api('/*'), ({ request }) => {
      calls.other.push(`${request.method} ${new URL(request.url).pathname}`);
      return HttpResponse.json({ error: 'terms_not_accepted', field: null }, { status: 403 });
    }),
  );
  return calls;
}

describe('terms acceptance', () => {
  it('blocks the app until the new terms are accepted', async () => {
    const calls = pendingTerms();
    const user = userEvent.setup();
    const { container } = renderApp('/');

    const dialog = await screen.findByRole('dialog', { name: 'New terms of use' });

    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(dialog.textContent).toContain('read and accept the new version');
    expect(dialog.textContent).toContain(TERMS_VERSION);
    expect(document.activeElement).toBe(dialog);
    // A tela por trás não é montada e o resto da página fica inerte
    expect(screen.queryByRole('heading', { name: 'Habits' })).toBeNull();
    expect(container.hasAttribute('inert')).toBe(true);
    expect(await axe(document.body)).toHaveNoViolations();

    // Links para os textos, em outra aba
    const terms = within(dialog).getByRole('link', { name: 'Terms of use' });
    const privacy = within(dialog).getByRole('link', { name: 'Privacy policy' });
    expect(terms.getAttribute('href')).toBe(`${BASENAME}${PATHS.terms}`);
    expect(privacy.getAttribute('href')).toBe(`${BASENAME}${PATHS.privacy}`);
    expect(terms.getAttribute('target')).toBe('_blank');
    // Enquanto o modal está aberto, a tela não chama a API
    expect(calls.other).toEqual([]);

    await user.click(within(dialog).getByRole('button', { name: 'Accept and continue' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Habits' })).toBeDefined();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(container.hasAttribute('inert')).toBe(false);
    expect(calls.accepted).toEqual([{ terms_version: TERMS_VERSION }]);
  });

  it('keeps the focus inside the dialog', async () => {
    pendingTerms();
    const user = userEvent.setup();
    renderApp('/');

    const dialog = await screen.findByRole('dialog');
    const focusable = [
      within(dialog).getByRole('link', { name: 'Terms of use' }),
      within(dialog).getByRole('link', { name: 'Privacy policy' }),
      within(dialog).getByRole('button', { name: 'Accept and continue' }),
      within(dialog).getByRole('button', { name: 'Sign out' }),
      within(dialog).getByRole('button', { name: 'pt' }),
      within(dialog).getByRole('button', { name: 'en' }),
    ];

    for (const element of focusable) {
      await user.tab();
      expect(document.activeElement).toBe(element);
    }
    // Do último volta para o primeiro, e o contrário
    await user.tab();
    expect(document.activeElement).toBe(focusable[0]);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(focusable.at(-1));

    // Escape não fecha
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBe(dialog);

    // Foco que sai (ex.: clique fora) volta para o diálogo
    document.body.focus();
    screen.getByRole('link', { name: 'Skip to content' }).focus();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('reloads the account and asks for a page reload when the terms changed again (409)', async () => {
    const calls = pendingTerms({
      accept: () => ({
        http: HttpResponse.json({ error: 'conflict', field: 'terms_version' }, { status: 409 }),
        me: meFixture({ ...PENDING, current_terms_version: '2099-01-01' }),
      }),
    });
    const user = userEvent.setup();
    renderApp('/');

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Accept and continue' }));

    expect(
      await within(dialog).findByText(/A newer version of the terms was published/),
    ).toBeDefined();
    expect(within(dialog).getByRole('button', { name: 'Reload page' })).toBeDefined();
    expect(within(dialog).queryByRole('button', { name: 'Accept and continue' })).toBeNull();
    expect(within(dialog).getByRole('button', { name: 'Sign out' })).toBeDefined();
    expect(calls.accepted).toHaveLength(1);
    expect(await axe(document.body)).toHaveNoViolations();
  });

  it('shows the conflict when the account still has the same version', async () => {
    pendingTerms({
      accept: () => ({
        http: HttpResponse.json({ error: 'conflict', field: 'terms_version' }, { status: 409 }),
      }),
    });
    const user = userEvent.setup();
    renderApp('/');

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Accept and continue' }));

    expect((await within(dialog).findByRole('alert')).textContent).toContain(
      'This conflicts with another change.',
    );
    expect(within(dialog).getByRole('button', { name: 'Accept and continue' })).toBeDefined();
  });

  it('lets the person sign out instead of accepting', async () => {
    const calls = pendingTerms();
    const user = userEvent.setup();
    const { router, container } = renderApp('/');

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Sign out' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeDefined();
    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.login}`);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(container.hasAttribute('inert')).toBe(false);
    expect(calls.logout).toBe(1);
    expect(calls.accepted).toEqual([]);
  });

  it('shows a failed sign out', async () => {
    pendingTerms();
    server.use(http.post(api('/auth/logout'), () => HttpResponse.error()));
    const user = userEvent.setup();
    renderApp('/');

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Sign out' }));

    expect((await within(dialog).findByRole('alert')).textContent).toContain('No connection');
  });

  it('switches the language inside the dialog', async () => {
    pendingTerms();
    const user = userEvent.setup();
    renderApp('/');

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'pt' }));

    await waitFor(() => expect(screen.getByRole('dialog', { name: 'Novos termos de uso' })).toBe(dialog));
    expect(within(dialog).getByRole('button', { name: 'Aceitar e continuar' })).toBeDefined();
  });

  it('does not show the dialog when the terms are up to date', async () => {
    server.use(
      http.get(api('/auth/me'), () => HttpResponse.json(meFixture({ timezone: browserTimezone() }))),
    );
    renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Habits' })).toBeDefined();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
