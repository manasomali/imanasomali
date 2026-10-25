import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { PATHS } from '../../paths';
import { adminRequests, bannerFixture, signedIn, trackRequests } from '../../test/admin';
import { axe } from '../../test/axe';
import { renderApp } from '../../test/render';
import { activeBanner, api, server } from '../../test/server';

const LIVE = bannerFixture();
const SCHEDULED = bannerFixture({
  id: 6,
  text_pt: 'Novidade em breve.',
  text_en: 'News soon.',
  starts_at: '2099-01-01T12:00:00Z',
  ends_at: '2099-02-01T12:00:00Z',
});
const ENDED = bannerFixture({
  id: 4,
  text_pt: 'Aviso antigo.',
  text_en: 'Old notice.',
  starts_at: '2026-01-01T12:00:00Z',
  ends_at: '2026-01-02T12:00:00Z',
});
const HIDDEN = bannerFixture({
  id: 3,
  text_pt: 'Atrás do outro.',
  text_en: 'Behind the other.',
  starts_at: '2026-01-01T12:00:00Z',
});

/** GET /admin/banners com a lista dada (mutável) e o banner público `live`. */
function banners(list, live = LIVE) {
  server.use(
    http.get(api('/admin/banners'), () => HttpResponse.json({ banners: list, next_cursor: null })),
    activeBanner(live),
  );
}

function card(id) {
  return screen.getByRole('heading', { level: 3, name: new RegExp(`Banner ${id}\\b`) }).closest('li');
}

async function openBanners(list = [SCHEDULED, LIVE, ENDED, HIDDEN]) {
  signedIn();
  banners(list);
  const requests = trackRequests();
  const result = renderApp(PATHS.adminBanners);
  await screen.findByRole('heading', { level: 3, name: new RegExp(`Banner ${list[0].id}\\b`) });
  return { ...result, requests };
}

function newBannerForm() {
  return screen.getByRole('form', { name: 'Create banner' });
}

describe('banner list', () => {
  it('shows each banner with its status and window in the admin time zone', async () => {
    const { container } = await openBanners();

    // O banner público também aparece no topo, para o próprio admin
    expect(screen.getByRole('region', { name: 'Notice' }).textContent).toContain(LIVE.text_en);

    expect(within(card(LIVE.id)).getByText('live')).toBeDefined();
    expect(within(card(SCHEDULED.id)).getByText('scheduled')).toBeDefined();
    expect(within(card(ENDED.id)).getByText('ended')).toBeDefined();
    expect(within(card(HIDDEN.id)).getByText('in its window, behind another')).toBeDefined();
    // 12:00 UTC em São Paulo
    expect(card(ENDED.id).textContent).toContain('9:00');
    expect(within(card(LIVE.id)).getByText(LIVE.text_pt).getAttribute('lang')).toBe('pt');
    expect(within(card(ENDED.id)).queryByRole('button', { name: 'End now' })).toBeNull();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows the empty list', async () => {
    signedIn();
    banners([], null);
    renderApp(PATHS.adminBanners);

    expect(await screen.findByText('No banners yet.')).toBeDefined();
  });
});

describe('create', () => {
  it('counts 280 characters per language and sends the window in UTC', async () => {
    const list = [];
    let body;
    server.use(
      http.post(api('/admin/banners'), async ({ request }) => {
        body = await request.json();
        const created = bannerFixture({ id: 9, ...body });
        list.unshift(created);
        return HttpResponse.json(created, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    signedIn();
    banners(list, null);
    const { container } = renderApp(PATHS.adminBanners);
    await screen.findByText('No banners yet.');
    const form = newBannerForm();

    const pt = within(form).getByLabelText('Text in Portuguese');
    const en = within(form).getByLabelText('Text in English');
    expect(within(form).getAllByText('0/280 characters')).toHaveLength(2);

    await user.type(pt, '  Olá{Enter}<b>todos</b>  ');
    await user.type(en, 'Hi 👋');

    // Quebra de linha vira espaço; o contador ignora os espaços das pontas e conta o emoji como 1
    expect(pt.value).toBe('  Olá <b>todos</b>  ');
    expect(within(form).getByText('16/280 characters')).toBeDefined();
    expect(within(form).getByText('4/280 characters')).toBeDefined();
    expect(pt.getAttribute('aria-describedby')).toContain(within(form).getByText('16/280 characters').id);
    expect(screen.getByText(/Dates and times in your time zone \(America\/Sao_Paulo\)/)).toBeDefined();

    fireEvent.change(within(form).getByLabelText('Start'), { target: { value: '2026-11-01T09:00' } });
    fireEvent.change(within(form).getByLabelText('End'), { target: { value: '2026-11-08T21:30' } });
    expect(await axe(container)).toHaveNoViolations();

    await user.click(within(form).getByRole('button', { name: 'Create banner' }));

    expect(await screen.findByText('Banner 9 created.')).toBeDefined();
    expect(body).toEqual({
      text_pt: 'Olá <b>todos</b>',
      text_en: 'Hi 👋',
      starts_at: '2026-11-01T12:00:00.000Z',
      ends_at: '2026-11-09T00:30:00.000Z',
    });
    // Formulário em branco de novo, e o banner na lista com o HTML como texto
    expect(within(newBannerForm()).getByLabelText('Text in Portuguese').value).toBe('');
    const created = await screen.findByRole('heading', { level: 3, name: /Banner 9\b/ });
    expect(created.closest('li').textContent).toContain('Olá <b>todos</b>');
    expect(created.closest('li').querySelector('b')).toBeNull();
  });

  it('blocks texts over 280 characters, empty fields and an end before the start', async () => {
    const user = userEvent.setup();
    const { requests } = await openBanners([LIVE]);
    const form = newBannerForm();
    const pt = within(form).getByLabelText('Text in Portuguese');

    fireEvent.change(pt, { target: { value: 'x'.repeat(281) } });

    expect(pt.getAttribute('aria-invalid')).toBe('true');
    expect(within(form).getByText('281/280 characters')).toBeDefined();

    fireEvent.change(within(form).getByLabelText('Start'), { target: { value: '2026-11-08T09:00' } });
    fireEvent.change(within(form).getByLabelText('End'), { target: { value: '2026-11-01T09:00' } });
    await user.click(within(form).getByRole('button', { name: 'Create banner' }));

    expect(within(form).getByText('Use at most 280 characters.')).toBeDefined();
    expect(within(form).getByText('Fill in this field.')).toBeDefined();
    expect(within(form).getByText('The end must be after the start.')).toBeDefined();
    expect(within(form).getByLabelText('End').getAttribute('aria-invalid')).toBe('true');
    expect(adminRequests(requests).filter((request) => request.method !== 'GET')).toEqual([]);
  });

  it('shows the field the API refused', async () => {
    server.use(
      http.post(api('/admin/banners'), () =>
        HttpResponse.json({ error: 'validation_error', field: 'text_en' }, { status: 422 }),
      ),
    );
    const user = userEvent.setup();
    await openBanners([LIVE]);
    const form = newBannerForm();

    await user.type(within(form).getByLabelText('Text in Portuguese'), 'Oi');
    await user.type(within(form).getByLabelText('Text in English'), 'Hi');
    fireEvent.change(within(form).getByLabelText('Start'), { target: { value: '2026-11-01T09:00' } });
    fireEvent.change(within(form).getByLabelText('End'), { target: { value: '2026-11-02T09:00' } });
    await user.click(within(form).getByRole('button', { name: 'Create banner' }));

    expect((await within(form).findByRole('alert')).textContent).toContain('Some field is invalid');
    expect(within(form).getByLabelText('Text in English').getAttribute('aria-invalid')).toBe('true');
  });
});

describe('edit and end', () => {
  it('sends only what changed', async () => {
    const list = [{ ...LIVE }];
    let body;
    server.use(
      http.patch(api(`/admin/banners/${LIVE.id}`), async ({ request }) => {
        body = await request.json();
        list[0] = { ...list[0], ...body };
        return HttpResponse.json(list[0]);
      }),
    );
    const user = userEvent.setup();
    const { container, requests } = await openBanners(list);
    const item = card(LIVE.id);

    await user.click(within(item).getByRole('button', { name: 'Edit' }));
    const form = within(item).getByRole('form', { name: 'Save banner' });
    const en = within(form).getByLabelText('Text in English');
    expect(en.value).toBe(LIVE.text_en);
    expect(within(form).getByLabelText('Start').value).toBe('2026-10-20T09:00');
    expect(await axe(container)).toHaveNoViolations();

    // Sem mudança: fecha sem chamar a API
    await user.click(within(form).getByRole('button', { name: 'Save banner' }));
    expect(within(item).queryByRole('form')).toBeNull();
    expect(adminRequests(requests).filter((request) => request.method === 'PATCH')).toEqual([]);

    await user.click(within(item).getByRole('button', { name: 'Edit' }));
    const field = within(item).getByLabelText('Text in English');
    await user.clear(field);
    await user.type(field, 'Maintenance on Sunday.');
    await user.click(within(item).getByRole('button', { name: 'Save banner' }));

    expect(await screen.findByText(`Banner ${LIVE.id} saved.`)).toBeDefined();
    expect(body).toEqual({ text_en: 'Maintenance on Sunday.' });
    expect(await within(card(LIVE.id)).findByText('Maintenance on Sunday.')).toBeDefined();
  });

  it('cancels editing and gives the focus back', async () => {
    const user = userEvent.setup();
    await openBanners([LIVE]);
    const item = card(LIVE.id);
    const edit = within(item).getByRole('button', { name: 'Edit' });

    await user.click(edit);
    expect(edit.getAttribute('aria-expanded')).toBe('true');
    await user.click(within(item).getByRole('button', { name: 'Cancel' }));

    expect(within(item).queryByRole('form')).toBeNull();
    expect(document.activeElement).toBe(edit);
  });

  it('ends a banner now and refreshes the public one', async () => {
    const list = [{ ...LIVE }];
    let live = LIVE;
    server.use(
      http.post(api(`/admin/banners/${LIVE.id}/end`), () => {
        list[0] = { ...LIVE, ends_at: '2026-10-24T12:00:00Z' };
        live = null;
        return HttpResponse.json(list[0]);
      }),
    );
    const user = userEvent.setup();
    await openBanners(list);
    // Depois do openBanners, que registra o banner público fixo
    server.use(http.get(api('/banners/active'), () => HttpResponse.json({ banner: live })));
    expect(await screen.findByRole('region', { name: 'Notice' })).toBeDefined();

    await user.click(within(card(LIVE.id)).getByRole('button', { name: 'End now' }));

    expect(await screen.findByText(`Banner ${LIVE.id} ended.`)).toBeDefined();
    expect(await within(card(LIVE.id)).findByText('ended')).toBeDefined();
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Notice' })).toBeNull());
  });

  it('shows the error of an end that fails', async () => {
    server.use(
      http.post(api(`/admin/banners/${LIVE.id}/end`), () =>
        HttpResponse.json({ error: 'not_found', field: null }, { status: 404 }),
      ),
    );
    const user = userEvent.setup();
    await openBanners([LIVE]);

    await user.click(within(card(LIVE.id)).getByRole('button', { name: 'End now' }));

    expect((await within(card(LIVE.id)).findByRole('alert')).textContent).toContain('Not found.');
  });
});
