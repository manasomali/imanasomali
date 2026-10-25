import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { activeBannerQueryKey } from '../../api/banners';
import { DISMISSED_BANNERS_KEY } from '../../lib/banner';
import { axe } from '../../test/axe';
import { createTestI18n } from '../../test/i18n';
import { renderApp } from '../../test/render';
import { activeBanner, api, server } from '../../test/server';

const BANNER = {
  id: 12,
  text_pt: 'Manutenção no sábado às 22h.',
  text_en: 'Maintenance on Saturday at 10 pm.',
  starts_at: '2026-10-20T12:00:00Z',
  ends_at: '2026-11-20T12:00:00Z',
};

// A tela de login é pública: nada ali busca a sessão, só o banner
const PUBLIC_PAGE = '/entrar';

/** Espera a resposta do GET /banners/active chegar (com sucesso ou erro). */
function bannerSettled(queryClient, status = 'success') {
  return waitFor(() => expect(queryClient.getQueryState(activeBannerQueryKey)?.status).toBe(status));
}

describe('active banner', () => {
  it('shows on pages without a session, in the language of the screen', async () => {
    server.use(activeBanner(BANNER));
    const user = userEvent.setup();
    const { container } = renderApp(PUBLIC_PAGE);

    const banner = await screen.findByRole('region', { name: 'Notice' });

    expect(banner.textContent).toContain(BANNER.text_en);
    expect(banner.textContent).not.toContain(BANNER.text_pt);
    expect(await axe(container)).toHaveNoViolations();

    const languages = screen.getByRole('group', { name: 'Language' });
    await user.click(within(languages).getByRole('button', { name: 'pt' }));

    const translated = await screen.findByRole('region', { name: 'Aviso' });
    expect(translated.textContent).toContain(BANNER.text_pt);
    expect(translated.textContent).not.toContain(BANNER.text_en);
  });

  it('starts in Portuguese when that is the saved language', async () => {
    window.localStorage.setItem('i18nextLng', 'pt');
    createTestI18n();
    server.use(activeBanner(BANNER));
    renderApp(PUBLIC_PAGE);

    expect((await screen.findByRole('region', { name: 'Aviso' })).textContent).toContain(BANNER.text_pt);
  });

  it('closes and stays closed in this browser', async () => {
    server.use(activeBanner(BANNER));
    const user = userEvent.setup();
    const first = renderApp(PUBLIC_PAGE);
    const banner = await screen.findByRole('region', { name: 'Notice' });

    await user.click(within(banner).getByRole('button', { name: 'Close notice' }));

    expect(screen.queryByRole('region', { name: 'Notice' })).toBeNull();
    // O botão sumiu: o foco vai para o conteúdo
    expect(document.activeElement).toBe(document.getElementById('content'));
    expect(JSON.parse(window.localStorage.getItem(DISMISSED_BANNERS_KEY))).toEqual([BANNER.id]);

    first.unmount();
    const second = renderApp(PUBLIC_PAGE);
    await screen.findByRole('heading', { level: 1, name: 'Sign in' });
    await bannerSettled(second.queryClient);
    expect(screen.queryByRole('region', { name: 'Notice' })).toBeNull();
  });

  it('shows a new banner after another one was closed', async () => {
    window.localStorage.setItem(DISMISSED_BANNERS_KEY, JSON.stringify([BANNER.id]));
    server.use(activeBanner({ ...BANNER, id: BANNER.id + 1, text_en: 'A new notice.' }));
    renderApp(PUBLIC_PAGE);

    expect((await screen.findByRole('region', { name: 'Notice' })).textContent).toContain('A new notice.');
  });

  it('renders HTML in the text as plain text', async () => {
    server.use(activeBanner({ ...BANNER, text_en: '<b>Bold</b> <img src=x onerror="alert(1)"> &amp;' }));
    const { container } = renderApp(PUBLIC_PAGE);

    const banner = await screen.findByRole('region', { name: 'Notice' });

    expect(banner.textContent).toContain('<b>Bold</b> <img src=x onerror="alert(1)"> &amp;');
    expect(banner.querySelector('b')).toBeNull();
    expect(banner.querySelector('img')).toBeNull();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows nothing when no banner is live', async () => {
    const { queryClient } = renderApp(PUBLIC_PAGE);

    await bannerSettled(queryClient);

    expect(screen.queryByRole('region', { name: 'Notice' })).toBeNull();
  });

  it('shows nothing when the request fails', async () => {
    server.use(
      http.get(api('/banners/active'), () =>
        HttpResponse.json({ error: 'not_found', field: null }, { status: 404 }),
      ),
    );
    const { queryClient } = renderApp(PUBLIC_PAGE);

    await bannerSettled(queryClient, 'error');

    expect(screen.getByRole('heading', { level: 1, name: 'Sign in' })).toBeDefined();
    expect(screen.queryByRole('region', { name: 'Notice' })).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
