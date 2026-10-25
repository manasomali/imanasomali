import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { BASENAME, PATHS } from '../../paths';
import { ADMIN, accountFixture, adminRequests, signedIn, trackRequests } from '../../test/admin';
import { axe } from '../../test/axe';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

const BIA = accountFixture();
const CAIO = accountFixture({
  id: 3,
  email: 'caio@example.com',
  is_active: false,
  last_login_at: null,
  habit_count: 0,
  mark_count: 0,
});
const SELF = accountFixture({ id: ADMIN.id, email: ADMIN.email, is_admin: true });

/**
 * GET /admin/users devolvendo `users` (lista mutável: as ações mudam o que a próxima busca vê),
 * filtrados pelo trecho do email como na API.
 */
function listing(users) {
  server.use(
    http.get(api('/admin/users'), ({ request }) => {
      const email = new URL(request.url).searchParams.get('email') ?? '';
      return HttpResponse.json({
        users: users.filter((account) => account.email.includes(email)),
        next_cursor: null,
      });
    }),
  );
}

function card(email) {
  return screen.getByRole('heading', { level: 3, name: new RegExp(email) }).closest('li');
}

async function openAccounts(users = [BIA, CAIO, SELF]) {
  signedIn();
  listing(users);
  const requests = trackRequests();
  const result = renderApp(PATHS.admin);
  await screen.findByRole('heading', { level: 3, name: new RegExp(users[0].email) });
  return { ...result, requests };
}

describe('access', () => {
  it.each([PATHS.admin, PATHS.adminBanners, '/admin/contas/2'])(
    'sends a user who is not an admin from %s to the home, without the menu link',
    async (path) => {
      signedIn(meFixture({ is_admin: false }));
      const requests = trackRequests();
      const { router } = renderApp(path);

      expect(await screen.findByRole('heading', { level: 1, name: 'Habits' })).toBeDefined();
      expect(router.state.location.pathname).toBe(BASENAME);
      expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull();
      expect(adminRequests(requests)).toEqual([]);
    },
  );

  it('shows the menu link to an admin', async () => {
    signedIn();
    listing([BIA]);
    const user = userEvent.setup();
    renderApp(PATHS.home);
    await screen.findByRole('heading', { level: 1, name: 'Habits' });

    const link = screen.getByRole('link', { name: 'Admin' });
    expect(link.getAttribute('href')).toBe(`${BASENAME}${PATHS.admin}`);

    await user.click(link);

    expect(await screen.findByRole('heading', { level: 1, name: 'Accounts' })).toBeDefined();
  });

  it('shows the 403 when the backend refuses', async () => {
    signedIn();
    server.use(
      http.get(api('/admin/users'), () => HttpResponse.json({ error: 'forbidden', field: null }, { status: 403 })),
    );
    renderApp(PATHS.admin);

    expect((await screen.findByRole('alert')).textContent).toContain('You do not have permission to do this.');
  });
});

describe('account list', () => {
  it('shows email, status, dates in the admin time zone and counts', async () => {
    const { container } = await openAccounts();

    const bia = card(BIA.email);
    expect(bia.textContent).toContain('Active');
    // 12:00 UTC e 15:30 UTC em São Paulo (UTC-3)
    expect(bia.textContent).toContain('9:00');
    expect(bia.textContent).toContain('12:30');
    expect(within(bia).getByText('3')).toBeDefined();
    expect(within(bia).getByText('42')).toBeDefined();
    expect(within(bia).getByRole('link', { name: 'View habits' }).getAttribute('href')).toBe(
      `${BASENAME}/admin/contas/2`,
    );

    const caio = card(CAIO.email);
    expect(caio.textContent).toContain('Blocked');
    expect(caio.textContent).toContain('Never signed in');
    expect(within(caio).getByRole('button', { name: 'Unblock' })).toBeDefined();

    expect(screen.getByText(/Dates in your time zone \(America\/Sao_Paulo\)/)).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('does not offer blocking the own account', async () => {
    await openAccounts();

    const self = card(SELF.email);
    expect(self.textContent).toContain('you');
    expect(within(self).queryByRole('button', { name: 'Block' })).toBeNull();
    expect(within(card(BIA.email)).getByRole('button', { name: 'Block' })).toBeDefined();
  });

  it('sends the filters and clears them', async () => {
    const user = userEvent.setup();
    const { requests } = await openAccounts();

    await user.type(screen.getByLabelText('Email contains'), '  bia@ ');
    await user.selectOptions(screen.getByLabelText('Status'), 'Blocked');
    fireEvent.change(screen.getByLabelText('Signed up from'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByLabelText('Last sign-in until'), { target: { value: '2026-02-28' } });
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => {
      expect(adminRequests(requests).at(-1).query).toEqual({
        email: 'bia@',
        status: 'blocked',
        created_from: '2026-01-01',
        last_login_to: '2026-02-28',
      });
    });
    await waitFor(() => expect(screen.queryByRole('heading', { level: 3, name: /caio@/ })).toBeNull());

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));

    expect(screen.getByLabelText('Email contains').value).toBe('');
    expect(screen.getByLabelText('Status').value).toBe('');
    expect(await screen.findByRole('heading', { level: 3, name: /caio@/ })).toBeDefined();
  });

  it('loads the next page with the cursor', async () => {
    signedIn();
    server.use(
      http.get(api('/admin/users'), ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor');
        return cursor === 'next'
          ? HttpResponse.json({ users: [CAIO], next_cursor: null })
          : HttpResponse.json({ users: [BIA], next_cursor: 'next' });
      }),
    );
    const user = userEvent.setup();
    renderApp(PATHS.admin);
    await screen.findByRole('heading', { level: 3, name: new RegExp(BIA.email) });

    await user.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByRole('heading', { level: 3, name: new RegExp(CAIO.email) })).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
  });
});

describe('account actions', () => {
  it('blocks only after the account email is typed', async () => {
    const users = [{ ...BIA }];
    let blocked = 0;
    server.use(
      http.post(api('/admin/users/2/block'), () => {
        blocked += 1;
        users[0] = { ...BIA, is_active: false };
        return HttpResponse.json(users[0]);
      }),
    );
    const user = userEvent.setup();
    const { container } = await openAccounts(users);
    const bia = card(BIA.email);

    await user.click(within(bia).getByRole('button', { name: 'Block' }));

    const form = within(bia).getByRole('form', { name: 'Block the account' });
    const confirm = within(form).getByRole('button', { name: 'Block the account' });
    const input = within(form).getByLabelText(`To confirm, type the account email: ${BIA.email}`);
    expect(document.activeElement).toBe(input);
    expect(confirm.disabled).toBe(true);
    expect(await axe(container)).toHaveNoViolations();

    await user.type(input, 'bia@example');
    expect(confirm.disabled).toBe(true);
    await user.type(input, '{Enter}');
    expect(blocked).toBe(0);

    await user.clear(input);
    await user.type(input, ' BIA@example.com ');
    expect(confirm.disabled).toBe(false);
    await user.click(confirm);

    const status = await screen.findByText('Account bia@example.com blocked.');
    expect(status.getAttribute('role')).toBe('status');
    expect(document.activeElement).toBe(status);
    expect(blocked).toBe(1);
    // A lista busca de novo e mostra a conta bloqueada
    expect(await within(card(BIA.email)).findByRole('button', { name: 'Unblock' })).toBeDefined();
  });

  it('cancels without calling the API and gives the focus back', async () => {
    const user = userEvent.setup();
    const { requests } = await openAccounts();
    const bia = card(BIA.email);
    const open = within(bia).getByRole('button', { name: 'Delete' });

    await user.click(open);
    expect(open.getAttribute('aria-expanded')).toBe('true');
    await user.click(within(bia).getByRole('button', { name: 'Cancel' }));

    expect(within(bia).queryByRole('form')).toBeNull();
    expect(document.activeElement).toBe(open);
    expect(adminRequests(requests).filter((request) => request.method !== 'GET')).toEqual([]);
  });

  it('shows the 409 when the new email already has an account', async () => {
    let body;
    server.use(
      http.patch(api('/admin/users/2/email'), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ error: 'email_in_use', field: 'new_email' }, { status: 409 });
      }),
    );
    const user = userEvent.setup();
    const { container } = await openAccounts();
    const bia = card(BIA.email);

    await user.click(within(bia).getByRole('button', { name: 'Change email' }));
    const form = within(bia).getByRole('form', { name: "Change the account's email" });
    const newEmail = within(form).getByLabelText('New email');
    expect(document.activeElement).toBe(newEmail);

    await user.type(newEmail, ' caio@example.com ');
    await user.type(within(form).getByLabelText(/To confirm, type the account email/), BIA.email);
    await user.click(within(form).getByRole('button', { name: 'Change the email' }));

    const alert = await within(form).findByRole('alert');
    expect(alert.textContent).toContain('This email already belongs to an account. Choose another one.');
    expect(newEmail.getAttribute('aria-invalid')).toBe('true');
    expect(body).toEqual({ new_email: 'caio@example.com' });
    expect(await axe(container)).toHaveNoViolations();
  });

  it('changes the email', async () => {
    const users = [{ ...BIA }];
    server.use(
      http.patch(api('/admin/users/2/email'), async ({ request }) => {
        const { new_email: email } = await request.json();
        users[0] = { ...BIA, email };
        return HttpResponse.json(users[0]);
      }),
    );
    const user = userEvent.setup();
    await openAccounts(users);
    const bia = card(BIA.email);

    await user.click(within(bia).getByRole('button', { name: 'Change email' }));
    await user.type(within(bia).getByLabelText('New email'), 'bia@new.example.com');
    await user.type(within(bia).getByLabelText(/To confirm/), BIA.email);
    await user.click(within(bia).getByRole('button', { name: 'Change the email' }));

    expect(await screen.findByText('Email changed from bia@example.com to bia@new.example.com.')).toBeDefined();
    expect(await screen.findByRole('heading', { level: 3, name: /bia@new\.example\.com/ })).toBeDefined();
  });

  it('shows the 409 for the last admin and deletes another account', async () => {
    const users = [{ ...BIA }, SELF];
    server.use(
      http.delete(api('/admin/users/1'), () =>
        HttpResponse.json({ error: 'last_admin', field: null }, { status: 409 }),
      ),
      http.delete(api('/admin/users/2'), () => {
        users.splice(0, 1);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    await openAccounts(users);

    const self = card(SELF.email);
    await user.click(within(self).getByRole('button', { name: 'Delete' }));
    await user.type(within(self).getByLabelText(/To confirm/), SELF.email);
    await user.click(within(self).getByRole('button', { name: 'Delete the account' }));
    expect((await within(self).findByRole('alert')).textContent).toContain(
      'This is the last active administrator account and cannot be deleted.',
    );

    const bia = card(BIA.email);
    await user.click(within(bia).getByRole('button', { name: 'Delete' }));
    await user.type(within(bia).getByLabelText(/To confirm/), BIA.email);
    await user.click(within(bia).getByRole('button', { name: 'Delete the account' }));

    expect(await screen.findByText('Account bia@example.com deleted.')).toBeDefined();
    await waitFor(() => expect(screen.queryByRole('heading', { level: 3, name: /bia@example\.com/ })).toBeNull());
  });

  it('unblocks without confirmation', async () => {
    const users = [{ ...CAIO }];
    server.use(
      http.post(api('/admin/users/3/unblock'), () => {
        users[0] = { ...CAIO, is_active: true };
        return HttpResponse.json(users[0]);
      }),
    );
    const user = userEvent.setup();
    await openAccounts(users);

    await user.click(within(card(CAIO.email)).getByRole('button', { name: 'Unblock' }));

    expect(await screen.findByText('Account caio@example.com unblocked.')).toBeDefined();
    expect(await within(card(CAIO.email)).findByRole('button', { name: 'Block' })).toBeDefined();
  });

  it('shows the error of an unblock that fails', async () => {
    server.use(
      http.post(api('/admin/users/3/unblock'), () =>
        HttpResponse.json({ error: 'not_found', field: null }, { status: 404 }),
      ),
    );
    const user = userEvent.setup();
    await openAccounts([CAIO]);

    await user.click(within(card(CAIO.email)).getByRole('button', { name: 'Unblock' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Not found.');
  });
});
