import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { BASENAME } from '../../paths';
import { axe } from '../../test/axe';
import { habitFixture, mockHabitsApi } from '../../test/habits';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';
import { memberFixture, mockSharingApi, pendingInviteFixture, writes } from '../../test/sharing';

const ANA = memberFixture(1, 'ana@example.com', 'owner', '2026-01-05T12:00:00Z');
const BIA = memberFixture(2, 'bia@example.com', 'editor', '2026-02-01T12:00:00Z');
const CAIO = memberFixture(3, 'caio@example.com', 'viewer', '2026-02-10T12:00:00Z');
const DORA = pendingInviteFixture({ id: 50, email: 'dora@example.com', role: 'viewer' });

function signedIn(me = meFixture()) {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(me)));
}

/** A aba de compartilhamento do hábito 1, vista por `me` com o papel `role`. */
async function openSharing({ role = 'owner', me, habit = {}, ...sharing } = {}) {
  signedIn(me);
  const habits = [habitFixture({ role, ...habit })];
  mockHabitsApi({ habits });
  const state = mockSharingApi({
    members: { 1: [ANA, { ...BIA }, { ...CAIO }] },
    invites: { 1: [DORA] },
    habits,
    ...sharing,
  });
  const user = userEvent.setup();
  const result = renderApp('/habits/1/sharing');
  await screen.findByRole('heading', { level: 3, name: 'People with access' });
  await screen.findByText('bia@example.com');
  return { ...result, ...state, habits, user };
}

function memberItem(email) {
  return screen.getByText(email).closest('li');
}

function inviteForm() {
  return screen.getByRole('form', { name: 'Invite someone' });
}

describe('sharing: owner', () => {
  it('lists members, pending invites and the free spots', async () => {
    const { container, user } = await openSharing();

    expect(screen.getByRole('heading', { level: 2, name: 'Sharing' })).toBeDefined();
    expect(within(memberItem('ana@example.com')).getByText('Owner')).toBeDefined();
    expect(within(memberItem('ana@example.com')).getByText('You')).toBeDefined();
    expect(within(memberItem('bia@example.com')).getByText('Can mark')).toBeDefined();
    expect(within(memberItem('caio@example.com')).getByText('View only')).toBeDefined();
    // Data no fuso da conta (São Paulo)
    expect(within(memberItem('bia@example.com')).getByText('Since Feb 1, 2026')).toBeDefined();
    // O dono não tem controles sobre si mesmo
    expect(within(memberItem('ana@example.com')).queryByRole('button')).toBeNull();

    const pending = await screen.findByText('dora@example.com');
    expect(within(pending.closest('li')).getByText('Sent on Mar 1, 2026')).toBeDefined();
    // 2 membros + 1 convite, de 5 (guest_limit da API)
    expect(screen.getByText(/3 of 5 spots used/)).toBeDefined();
    expect(screen.getByRole('link', { name: 'Sharing' }).getAttribute('aria-current')).toBe('page');
    expect(screen.queryByRole('button', { name: 'Leave habit' })).toBeNull();
    expect(await axe(container)).toHaveNoViolations();

    // A seção também se abre pelo submenu do hábito
    await user.click(screen.getByRole('link', { name: 'Calendar' }));
    await user.click(await screen.findByRole('link', { name: 'Sharing' }));
    expect(await screen.findByRole('heading', { level: 2, name: 'Sharing' })).toBeDefined();
  });

  it('says "invite sent" for any email, with or without an account or access', async () => {
    const { requests, user } = await openSharing();
    await screen.findByText('dora@example.com');
    const form = inviteForm();
    const email = within(form).getByLabelText('Email');

    // Email novo, como viewer
    await user.type(email, '  Nova@Example.com ');
    await user.click(within(form).getByRole('radio', { name: /View only/ }));
    await user.click(within(form).getByRole('button', { name: 'Send invite' }));
    await waitFor(() => expect(screen.getByText('Invite sent.')).toBeDefined());
    expect(email.value).toBe('');

    // Quem já é membro: a API não muda nada e a tela diz o mesmo (o papel escolhido fica)
    await user.type(email, 'bia@example.com');
    await user.click(within(form).getByRole('button', { name: 'Send invite' }));
    await waitFor(() => expect(email.value).toBe(''));
    expect(screen.getByText('Invite sent.')).toBeDefined();

    const bodies = requests.filter((r) => r.method === 'POST').map((r) => r.body);
    expect(bodies).toEqual([
      { email: 'Nova@Example.com', role: 'viewer' },
      { email: 'bia@example.com', role: 'viewer' },
    ]);
    // O pendente novo aparece na lista e ocupa uma vaga
    expect(await screen.findByText('Nova@Example.com')).toBeDefined();
    expect(screen.getByText(/4 of 5 spots used/)).toBeDefined();
  });

  it('asks for an email before sending', async () => {
    const { requests, user } = await openSharing();
    const form = inviteForm();

    await user.click(within(form).getByRole('button', { name: 'Send invite' }));

    const email = within(form).getByLabelText('Email');
    expect(email.getAttribute('aria-invalid')).toBe('true');
    expect(within(form).getByText('Enter an email address.')).toBeDefined();
    expect(document.activeElement).toBe(email);
    expect(writes(requests)).toEqual([]);
  });

  it('shows the API errors: invalid email and limits', async () => {
    const { container, user } = await openSharing({
      fail: { 'POST /habits/1/invites': 'invite_limit_reached' },
    });
    const form = inviteForm();
    await user.type(within(form).getByLabelText('Email'), 'eva@example.com');
    await user.click(within(form).getByRole('button', { name: 'Send invite' }));

    expect(await within(form).findByRole('alert')).toBeDefined();
    expect(within(form).getByRole('alert').textContent).toContain('daily invite limit');
    expect(screen.queryByText('Invite sent.')).toBeNull();
    expect(await axe(container)).toHaveNoViolations();

    server.use(
      http.post(api('/habits/1/invites'), () =>
        HttpResponse.json({ error: 'validation_error', field: 'email' }, { status: 422 }),
      ),
    );
    await user.click(within(form).getByRole('button', { name: 'Send invite' }));
    expect(await within(form).findByText('Enter a valid email address.')).toBeDefined();
    expect(within(form).getByLabelText('Email').getAttribute('aria-invalid')).toBe('true');
  });

  it('turns sending off when there are no spots left', async () => {
    await openSharing({ guestLimit: 3 });

    await screen.findByText(/3 of 3 spots used/);
    expect(screen.getByText(/Cancel an invite or remove someone/)).toBeDefined();
    expect(within(inviteForm()).getByRole('button', { name: 'Send invite' }).disabled).toBe(true);
  });

  it('shows the guest limit error when another tab used the last spot', async () => {
    const { user } = await openSharing({ fail: { 'POST /habits/1/invites': 'guest_limit_reached' } });
    const form = inviteForm();
    await user.type(within(form).getByLabelText('Email'), 'eva@example.com');
    await user.click(within(form).getByRole('button', { name: 'Send invite' }));

    expect((await within(form).findByRole('alert')).textContent).toContain('guest limit');
  });

  it('cancels a pending invite, which leaves the list', async () => {
    const { requests, user } = await openSharing();

    await user.click(await screen.findByRole('button', { name: 'Cancel invite to dora@example.com' }));

    await waitFor(() => expect(screen.queryByText('dora@example.com')).toBeNull());
    expect(screen.getByText('Invite to dora@example.com canceled.')).toBeDefined();
    expect(screen.getByText('No pending invites.')).toBeDefined();
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Pending invites' }));
    expect(writes(requests)).toEqual(['DELETE /habits/1/invites/50']);
    expect(screen.getByText(/2 of 5 spots used/)).toBeDefined();
  });

  it('changes a member role', async () => {
    const { requests, user } = await openSharing();
    const item = memberItem('bia@example.com');

    await user.click(within(item).getByRole('button', { name: 'Make view only' }));

    await waitFor(() => expect(within(item).getByText('View only')).toBeDefined());
    expect(screen.getByText(/bia@example.com can now only view/)).toBeDefined();
    expect(requests.find((r) => r.method === 'PATCH')).toEqual({
      method: 'PATCH',
      path: '/habits/1/members/2',
      body: { role: 'viewer' },
    });
    await user.click(within(item).getByRole('button', { name: 'Allow marking' }));
    await waitFor(() => expect(within(item).getByText('Can mark')).toBeDefined());
  });

  it('asks for confirmation before removing a member', async () => {
    const { container, requests, user } = await openSharing();
    const item = memberItem('bia@example.com');
    const actions = within(item).getByRole('group', { name: 'Actions for bia@example.com' });

    await user.click(within(actions).getByRole('button', { name: 'Remove' }));
    const panel = within(item).getByRole('group', { name: 'Remove bia@example.com from this habit?' });
    expect(within(panel).getByText(/Their marks stay in the habit/)).toBeDefined();
    expect(document.activeElement).toBe(within(panel).getByRole('button', { name: 'Cancel' }));
    expect(await axe(container)).toHaveNoViolations();

    // Cancelar não chama a API e devolve o foco
    await user.click(within(panel).getByRole('button', { name: 'Cancel' }));
    expect(within(item).queryByRole('group', { name: /from this habit/ })).toBeNull();
    expect(document.activeElement).toBe(within(actions).getByRole('button', { name: 'Remove' }));
    expect(writes(requests)).toEqual([]);

    await user.click(within(actions).getByRole('button', { name: 'Remove' }));
    await user.click(screen.getByRole('button', { name: 'Yes, remove' }));

    await waitFor(() => expect(screen.queryByText('bia@example.com')).toBeNull());
    expect(screen.getByText('bia@example.com no longer has access to this habit.')).toBeDefined();
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'People with access' }));
    expect(writes(requests)).toEqual(['DELETE /habits/1/members/2']);
  });

  it('keeps the member and shows the error when removing fails', async () => {
    const { user } = await openSharing({ fail: { 'DELETE /habits/1/members/2': 'conflict' } });
    const item = memberItem('bia@example.com');

    await user.click(within(item).getByRole('button', { name: 'Remove' }));
    await user.click(within(item).getByRole('button', { name: 'Yes, remove' }));

    expect(await within(item).findByRole('alert')).toBeDefined();
    expect(screen.getByText('bia@example.com')).toBeDefined();
  });

  it('does not take new invites on an archived habit', async () => {
    await openSharing({ habit: { status: 'archived' } });

    expect(screen.getByText(/Archived habits do not take new invites/)).toBeDefined();
    expect(screen.queryByRole('form', { name: 'Invite someone' })).toBeNull();
    // O resto continua: remover e cancelar
    expect(within(memberItem('bia@example.com')).getByRole('button', { name: 'Remove' })).toBeDefined();
    expect(await screen.findByRole('button', { name: 'Cancel invite to dora@example.com' })).toBeDefined();
  });

  it('says when only the owner has access', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    mockSharingApi({ members: { 1: [ANA] }, invites: { 1: [] } });
    renderApp('/habits/1/sharing');

    expect(await screen.findByText('Only you have access to this habit for now.')).toBeDefined();
    expect(await screen.findByText('No pending invites.')).toBeDefined();
    expect(screen.getByText(/0 of 5 spots used/)).toBeDefined();
  });

  it('shows the error when the members do not load', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()] });
    mockSharingApi({ invites: { 1: [] } });
    server.use(
      http.get(api('/habits/1/members'), () =>
        HttpResponse.json({ error: 'not_found', field: null }, { status: 404 }),
      ),
    );
    renderApp('/habits/1/sharing');

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeDefined();
    // Sem a lista de membros, não há contador
    expect(screen.queryByText(/spots used/)).toBeNull();
  });
});

describe.each(['editor', 'viewer'])('sharing: %s', (role) => {
  const me = meFixture({ id: 2, email: 'bia@example.com' });
  const asMember = { role, me, members: { 1: [ANA, { ...BIA, role }, CAIO] } };

  it('sees the members, but none of the owner controls', async () => {
    const { container, requests } = await openSharing(asMember);

    expect(within(memberItem('bia@example.com')).getByText('You')).toBeDefined();
    expect(screen.queryByRole('form', { name: 'Invite someone' })).toBeNull();
    expect(screen.queryByText(/spots used/)).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Pending invites' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Make view only|Allow marking/ })).toBeNull();
    expect(screen.getByRole('button', { name: 'Leave habit' })).toBeDefined();
    // Nem busca os convites do hábito (a API daria 403)
    expect(requests.some((r) => r.path === '/habits/1/invites')).toBe(false);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('leaves the habit after confirming and goes back to the habit list', async () => {
    const { container, requests, router, user } = await openSharing(asMember);

    await user.click(screen.getByRole('button', { name: 'Leave habit' }));
    const panel = screen.getByRole('group', { name: 'Leave “Running”?' });
    expect(await axe(container)).toHaveNoViolations();
    await user.click(within(panel).getByRole('button', { name: 'Cancel' }));
    expect(writes(requests)).toEqual([]);

    await user.click(screen.getByRole('button', { name: 'Leave habit' }));
    await user.click(screen.getByRole('button', { name: 'Yes, leave' }));

    await waitFor(() => expect(router.state.location.pathname).toBe(BASENAME));
    expect(writes(requests)).toEqual(['POST /habits/1/leave']);
    // A lista é buscada de novo: o hábito some das abas
    expect(await screen.findByText('You do not have any habits yet.')).toBeDefined();
    expect(screen.queryByRole('link', { name: 'RUN' })).toBeNull();
  });
});
