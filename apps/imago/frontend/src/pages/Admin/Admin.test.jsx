import { describe, expect, it, vi } from 'vitest';
import { configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { BASENAME, PATHS } from '../../paths';
import { ADMIN, accountFixture, mailFixture } from '../../test/admin';
import { axe } from '../../test/axe';
import { meFixture, renderApp, signedIn } from '../../test/render';
import { api, apiError, server, trackRequests } from '../../test/server';

vi.setConfig({ testTimeout: 15_000 });

configure({ asyncUtilTimeout: 5_000 });

const BIA = accountFixture();
const CAIO = accountFixture({
  id: 103,
  email: 'caio@example.com',
  is_active: false,
  timezone: 'Europe/Lisbon',
  locale: 'en',
  last_login_at: null,
});

/**
 * API do admin: GET /admin/users devolve `pages` (uma lista de {users, next_cursor}, pelo cursor
 * "p<n>") e GET /admin/mail, `mail`. `write` responde as escritas (por padrão, o AdminUser alterado
 * ou 204).
 */
function adminApi({ me = ADMIN, pages = [{ users: [BIA, CAIO], next_cursor: null }], mail = mailFixture(), write } = {}) {
  signedIn(me);
  server.use(
    http.get(api('/admin/users'), ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      return HttpResponse.json(pages[cursor ? Number(cursor.slice(1)) : 0]);
    }),
    http.get(api('/admin/mail'), () => HttpResponse.json(mail)),
    http.patch(api('/admin/users/:id'), async ({ request, params }) => {
      const body = await request.json();
      return write?.(request, body) ?? HttpResponse.json({ ...accountFixture({ id: Number(params.id) }), ...body });
    }),
    http.patch(api('/admin/users/:id/email'), async ({ request, params }) => {
      const body = await request.json();
      return (
        write?.(request, body) ??
        HttpResponse.json(accountFixture({ id: Number(params.id), email: body.new_email }))
      );
    }),
    http.delete(api('/admin/users/:id'), ({ request }) => write?.(request, null) ?? new HttpResponse(null, { status: 204 })),
  );
}

async function openAdmin(options) {
  adminApi(options);
  const rendered = renderApp(PATHS.admin);
  await screen.findByRole('heading', { level: 1, name: 'Admin' });
  return rendered;
}

/** O cartão da conta com o email dado, na lista. */
async function card(email) {
  const list = await screen.findByRole('list', { name: 'Accounts found' });
  return within(list).getByText(email).closest('li');
}

function writes(requests) {
  return requests
    .filter((request) => request.method !== 'GET')
    .map(({ method, path, body }) => ({ method, path, body }));
}

describe('access', () => {
  it('sends a person who is not an admin back to the account page, without calling /admin', async () => {
    const requests = trackRequests();
    signedIn(meFixture());
    const { router } = renderApp(PATHS.admin);

    expect(await screen.findByRole('heading', { level: 1, name: 'Account' })).toBeDefined();
    expect(router.state.location.pathname).toMatch(/^\/imago\/?$/);
    expect(requests.filter((request) => request.path.startsWith('/admin'))).toEqual([]);
    expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull();
  });

  it('sends an admin with pending terms to the acceptance, back here afterwards', async () => {
    const requests = trackRequests();
    signedIn({ ...ADMIN, terms_pending: true, terms_version: '2026-01-01' });
    const { router } = renderApp(PATHS.admin);

    expect(await screen.findByRole('heading', { level: 1, name: 'New terms of use' })).toBeDefined();
    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.login}`);
    expect(new URLSearchParams(router.state.location.search).get('next')).toBe('/imago/admin');
    expect(requests.filter((request) => request.path.startsWith('/admin'))).toEqual([]);
  });

  it('shows the error when the API refuses (403)', async () => {
    adminApi();
    server.use(http.get(api('/admin/users'), () => apiError(403, 'forbidden')));
    renderApp(PATHS.admin);

    expect((await screen.findAllByRole('alert'))[0].textContent).toContain('You do not have permission to do this.');
  });

  it('shows the admin link in the menu', async () => {
    await openAdmin();

    const navigation = screen.getByRole('navigation', { name: 'Main navigation' });

    expect(within(navigation).getByRole('link', { name: 'Admin' }).getAttribute('href')).toBe(`${BASENAME}${PATHS.admin}`);
  });
});

describe('accounts', () => {
  it('lists the accounts with status, dates in the admin time zone and badges', async () => {
    const { container } = await openAdmin({
      pages: [{ users: [accountFixture({ ...ADMIN, id: 101, email: ADMIN.email, is_admin: true }), BIA, CAIO], next_cursor: null }],
    });

    const bia = await card('bia@example.com');
    expect(bia.textContent).toContain('Active');
    // 15:30 UTC é 12:30 em São Paulo, o fuso do admin (o ICU separa o "PM" com um espaço estreito)
    expect(bia.textContent.replace(/\s/g, ' ')).toContain('Last sign-in10/20/26, 12:30 PM');
    expect(bia.textContent).toContain('America/Sao_Paulo');

    const caio = await card('caio@example.com');
    expect(caio.textContent).toContain('Blocked');
    expect(caio.textContent).toContain('Never signed in');

    const self = await card('ana@example.com');
    expect(self.textContent).toContain('admin');
    expect(self.textContent).toContain('you');
    // O admin não bloqueia a própria conta
    expect(within(self).queryByRole('button', { name: 'Block' })).toBeNull();

    expect(screen.getByText('Newest accounts first. Dates in your time zone (America/Sao_Paulo).')).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('searches by part of the email and by status', async () => {
    const requests = trackRequests();
    const user = userEvent.setup();
    await openAdmin();
    await card('bia@example.com');

    await user.type(screen.getByLabelText('Email contains'), '  bia@ ');
    await user.selectOptions(screen.getByLabelText('Status'), 'deleting');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() =>
      expect(requests.filter((request) => request.path === '/admin/users').at(-1).query).toEqual({
        email: 'bia@',
        status: 'deleting',
      }),
    );

    // Limpar volta para a lista sem filtros (já em cache, sem buscar de novo)
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));

    expect(screen.getByLabelText('Email contains').value).toBe('');
    expect(screen.getByLabelText('Status').value).toBe('');
    expect(await card('caio@example.com')).toBeDefined();
  });

  it('loads more pages by the cursor', async () => {
    const requests = trackRequests();
    const user = userEvent.setup();
    await openAdmin({
      pages: [
        { users: [BIA], next_cursor: 'p1' },
        { users: [CAIO], next_cursor: null },
      ],
    });
    await card('bia@example.com');

    await user.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await card('caio@example.com')).toBeDefined();
    expect(await card('bia@example.com')).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
    expect(requests.filter((request) => request.path === '/admin/users').map((request) => request.query)).toEqual([
      {},
      { cursor: 'p1' },
    ]);
  });

  it('says when no account matches', async () => {
    await openAdmin({ pages: [{ users: [], next_cursor: null }] });

    expect(await screen.findByText('No accounts found.')).toBeDefined();
  });

  it('blocks only after the account email is typed', async () => {
    const requests = trackRequests();
    const user = userEvent.setup();
    const { container } = await openAdmin();
    const bia = await card('bia@example.com');

    await user.click(within(bia).getByRole('button', { name: 'Block' }));
    const confirm = within(bia).getByRole('button', { name: 'Block the account' });
    expect(confirm.disabled).toBe(true);
    expect(document.activeElement).toBe(within(bia).getByLabelText(/To confirm, type the account email/));
    expect(await axe(container)).toHaveNoViolations();

    await user.type(within(bia).getByLabelText(/To confirm, type the account email/), 'bia@example');
    expect(confirm.disabled).toBe(true);
    await user.type(within(bia).getByLabelText(/To confirm, type the account email/), '.COM');
    expect(confirm.disabled).toBe(false);
    await user.click(confirm);

    expect(await screen.findByText('Account bia@example.com blocked.')).toBeDefined();
    expect(writes(requests)).toEqual([{ method: 'PATCH', path: '/admin/users/102', body: { is_active: false } }]);
  });

  it('unblocks without a confirmation', async () => {
    const requests = trackRequests();
    const user = userEvent.setup();
    await openAdmin();
    const caio = await card('caio@example.com');

    await user.click(within(caio).getByRole('button', { name: 'Unblock' }));

    expect(await screen.findByText('Account caio@example.com unblocked.')).toBeDefined();
    expect(writes(requests)).toEqual([{ method: 'PATCH', path: '/admin/users/103', body: { is_active: true } }]);
  });

  it('changes the email', async () => {
    const requests = trackRequests();
    const user = userEvent.setup();
    await openAdmin();
    const bia = await card('bia@example.com');

    await user.click(within(bia).getByRole('button', { name: 'Change email' }));
    expect(document.activeElement).toBe(within(bia).getByLabelText('New email'));
    await user.type(within(bia).getByLabelText('New email'), ' bia@novo.example ');
    await user.type(within(bia).getByLabelText(/To confirm, type the account email/), 'bia@example.com');
    await user.click(within(bia).getByRole('button', { name: 'Change the email' }));

    expect(await screen.findByText('Email changed from bia@example.com to bia@novo.example.')).toBeDefined();
    expect(writes(requests)).toEqual([
      { method: 'PATCH', path: '/admin/users/102/email', body: { new_email: 'bia@novo.example' } },
    ]);
  });

  it('shows the 409 of an email that already has an account, changing nothing', async () => {
    const user = userEvent.setup();
    const { container } = await openAdmin({ write: () => apiError(409, 'email_in_use', 'new_email') });
    const bia = await card('bia@example.com');

    await user.click(within(bia).getByRole('button', { name: 'Change email' }));
    await user.type(within(bia).getByLabelText('New email'), 'caio@example.com');
    await user.type(within(bia).getByLabelText(/To confirm, type the account email/), 'bia@example.com');
    await user.click(within(bia).getByRole('button', { name: 'Change the email' }));

    const alert = await within(bia).findByRole('alert');
    expect(alert.textContent).toContain('This email already belongs to an account.');
    const field = within(bia).getByLabelText('New email');
    expect(field.getAttribute('aria-invalid')).toBe('true');
    expect(field.getAttribute('aria-describedby')).toBe(alert.parentElement.id);
    expect(within(bia).getByText('bia@example.com')).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();

    // Mudar o email digitado tira o erro
    await user.type(field, 'x');
    expect(within(bia).queryByRole('alert')).toBeNull();
  });

  it('deletes only after the account email is typed, and refreshes the list', async () => {
    const requests = trackRequests();
    const user = userEvent.setup();
    await openAdmin();
    const bia = await card('bia@example.com');
    const listCalls = () => requests.filter((request) => request.path === '/admin/users').length;
    const before = listCalls();

    await user.click(within(bia).getByRole('button', { name: 'Delete' }));
    await user.type(within(bia).getByLabelText(/To confirm, type the account email/), 'bia@example.com');
    await user.click(within(bia).getByRole('button', { name: 'Delete the account' }));

    const status = await screen.findByText(/Account bia@example\.com deleted\./);
    expect(writes(requests)).toEqual([{ method: 'DELETE', path: '/admin/users/102', body: null }]);
    await waitFor(() => expect(listCalls()).toBeGreaterThan(before));
    expect(document.activeElement).toBe(status);
  });

  it('shows the last admin block on delete', async () => {
    const user = userEvent.setup();
    await openAdmin({ write: () => apiError(409, 'last_admin') });
    const bia = await card('bia@example.com');

    await user.click(within(bia).getByRole('button', { name: 'Delete' }));
    await user.type(within(bia).getByLabelText(/To confirm, type the account email/), 'bia@example.com');
    await user.click(within(bia).getByRole('button', { name: 'Delete the account' }));

    expect((await within(bia).findByRole('alert')).textContent).toContain('This is the last active administrator account');
  });

  it('closes the panel and returns the focus to the button', async () => {
    const user = userEvent.setup();
    await openAdmin();
    const bia = await card('bia@example.com');
    const button = within(bia).getByRole('button', { name: 'Delete' });

    await user.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    await user.click(within(bia).getByRole('button', { name: 'Cancel' }));

    expect(within(bia).queryByLabelText(/To confirm/)).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it('has no actions for an account being deleted', async () => {
    await openAdmin({ pages: [{ users: [accountFixture({ status: 'deleting' })], next_cursor: null }] });
    const bia = await card('bia@example.com');

    expect(bia.textContent).toContain('Being deleted');
    expect(bia.textContent).toContain('Deletion in progress in the applications.');
    expect(within(bia).queryByRole('button')).toBeNull();
  });
});

describe('emails sent', () => {
  it('shows what each application sent in 24 hours, by type, and what is left before the cap', async () => {
    const { container } = await openAdmin();

    const mail = screen.getByRole('region', { name: 'Emails sent' });
    const table = await within(mail).findByRole('table', { name: 'Emails sent in the last 24 hours, by application and type' });
    const rows = within(table)
      .getAllByRole('row')
      .map((row) => [...row.querySelectorAll('th, td')].map((cell) => cell.textContent));

    expect(rows).toEqual([
      ['Application', 'Codes', 'Account', 'Notifications', 'Total'],
      ['imago', '12', '1', '0', '13'],
      ['ethos', '0', '0', '30', '30'],
      ['Total', '12', '1', '30', '43'],
    ]);
    expect(mail.textContent).toContain('43 of 275 sent; 232 left before the cap.');
    expect(mail.textContent).toContain('Notifications stop at 215 (172 left).');
    expect(mail.textContent).toContain('5 of 60 sent; 55 left before the cap.');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('says when notifications stopped or the cap was reached', async () => {
    await openAdmin({
      mail: mailFixture({
        by_app: [],
        day: { sent: 275, limit: 275, notification_limit: 215 },
        hour: { sent: 50, limit: 60, notification_limit: 45 },
      }),
    });

    const mail = screen.getByRole('region', { name: 'Emails sent' });

    expect(await within(mail).findByText('Cap reached: no email goes out until the window moves.')).toBeDefined();
    expect(within(mail).getByText('Notifications stopped: only codes and account emails go out.')).toBeDefined();
    expect(within(mail).getByText('No emails sent in the last 24 hours.')).toBeDefined();
  });

  it('shows the error with a retry', async () => {
    adminApi();
    let fail = true;
    server.use(http.get(api('/admin/mail'), () => (fail ? apiError(503, 'service_unavailable') : HttpResponse.json(mailFixture()))));
    const user = userEvent.setup();
    renderApp(PATHS.admin);

    const mail = await screen.findByRole('region', { name: 'Emails sent' });
    expect((await within(mail).findByRole('alert', {}, { timeout: 10_000 })).textContent).toContain(
      'The service is unavailable right now.',
    );

    fail = false;
    await user.click(within(mail).getByRole('button', { name: 'Try again' }));

    expect(await within(mail).findByRole('table')).toBeDefined();
  });
});
