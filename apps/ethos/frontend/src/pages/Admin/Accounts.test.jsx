import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { BASENAME, PATHS } from '../../paths';
import { ADMIN, adminRequests, appUserFixture, signedIn, trackRequests } from '../../test/admin';
import { axe } from '../../test/axe';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

const BIA = appUserFixture();
const CAIO = appUserFixture({
  id: 3,
  email: 'caio@example.com',
  first_seen_at: '2026-10-20T15:30:00Z',
  habit_count: 0,
  mark_count: 0,
});
const SELF = appUserFixture({ id: ADMIN.id, email: ADMIN.email });

/** GET /admin/users devolvendo `users`, filtrados pelo trecho do email como na API. */
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

async function openUsers(users = [BIA, CAIO, SELF]) {
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

    expect(await screen.findByRole('heading', { level: 1, name: 'Who uses ethos' })).toBeDefined();
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

describe('list of users', () => {
  it('shows email, first access in the admin time zone and counts, without account actions', async () => {
    const { container } = await openUsers();

    const bia = card(BIA.email);
    // 12:00 UTC em São Paulo (UTC-3)
    expect(bia.textContent).toContain('First access');
    expect(bia.textContent).toContain('9:00');
    expect(within(bia).getByText('3')).toBeDefined();
    expect(within(bia).getByText('42')).toBeDefined();
    expect(within(bia).getByRole('link', { name: 'View habits' }).getAttribute('href')).toBe(
      `${BASENAME}/admin/contas/2`,
    );
    // Bloquear, trocar o email e excluir são do imago
    expect(within(bia).getAllByRole('link')).toHaveLength(1);
    expect(within(bia).queryAllByRole('button')).toEqual([]);
    expect(card(CAIO.email).textContent).toContain('12:30');
    expect(card(SELF.email).textContent).toContain('you');

    expect(screen.getByText(/Dates in your time zone \(America\/Sao_Paulo\)/)).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('links to the accounts panel of the imago', async () => {
    await openUsers();

    expect(screen.getByRole('link', { name: 'manasomali.com accounts' }).getAttribute('href')).toBe(
      '/imago/admin',
    );
  });

  it('sends the filters and clears them', async () => {
    const user = userEvent.setup();
    const { requests } = await openUsers();

    await user.type(screen.getByLabelText('Email contains'), '  bia@ ');
    fireEvent.change(screen.getByLabelText('First access from'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByLabelText('First access until'), { target: { value: '2026-02-28' } });
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => {
      expect(adminRequests(requests).at(-1).query).toEqual({
        email: 'bia@',
        first_seen_from: '2026-01-01',
        first_seen_to: '2026-02-28',
      });
    });
    await waitFor(() => expect(screen.queryByRole('heading', { level: 3, name: /caio@/ })).toBeNull());

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));

    expect(screen.getByLabelText('Email contains').value).toBe('');
    expect(screen.getByLabelText('First access from').value).toBe('');
    expect(await screen.findByRole('heading', { level: 3, name: /caio@/ })).toBeDefined();
  });

  it('shows the empty list', async () => {
    signedIn();
    listing([]);
    renderApp(PATHS.admin);

    expect(await screen.findByText('Nobody found.')).toBeDefined();
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
