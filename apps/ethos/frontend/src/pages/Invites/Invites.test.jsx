import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { PATHS } from '../../paths';
import { axe } from '../../test/axe';
import { habitFixture, mockHabitsApi } from '../../test/habits';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';
import { mockSharingApi, receivedInviteFixture, writes } from '../../test/sharing';

const READING = receivedInviteFixture();
const YOGA = receivedInviteFixture({
  id: 71,
  habit: { id: 12, name: 'Yoga', color: 'rose' },
  owner: { id: 5, email: 'fabi@example.com' },
  role: 'viewer',
});

function signedIn(overrides = {}) {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture(overrides))));
}

function inviteCard(name) {
  return screen.getByRole('heading', { level: 2, name }).closest('li');
}

/** Link de um hábito nas abas do topo. */
function habitTab(name) {
  return within(screen.getByRole('navigation', { name: 'Habits' })).queryByRole('link', { name });
}

function invitesLink() {
  return within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', {
    name: /^Invites/,
  });
}

describe('pending invites in the menu', () => {
  it('shows how many invites are pending on every screen', async () => {
    signedIn();
    mockHabitsApi({ habits: [] });
    mockSharingApi({ received: [READING, YOGA] });
    const { container } = renderApp('/');

    // O número fica visível; o leitor de tela ouve o texto inteiro
    expect(await screen.findByRole('link', { name: 'Invites 2 pending invites' })).toBeDefined();
    expect(within(invitesLink()).getByText('2').getAttribute('aria-hidden')).toBe('true');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows no count without pending invites', async () => {
    signedIn();
    mockHabitsApi({ habits: [] });
    const { requests } = mockSharingApi({ received: [] });
    renderApp('/');

    await waitFor(() => expect(requests.some((r) => r.path === '/invites')).toBe(true));
    expect(screen.getByRole('link', { name: 'Invites' })).toBeDefined();
    expect(invitesLink().textContent).toBe('Invites');
  });

  it('does not look for invites while the terms are pending', async () => {
    signedIn({ terms_version: null, terms_pending: true });
    mockHabitsApi({ habits: [] });
    const { requests } = mockSharingApi({ received: [READING] });
    renderApp('/');

    await screen.findByRole('navigation', { name: 'Main navigation' });
    await waitFor(() => expect(screen.queryByText('Loading…')).toBeNull());
    expect(requests.some((r) => r.path === '/invites')).toBe(false);
  });
});

describe('invite inbox', () => {
  it('lists the received invites', async () => {
    signedIn();
    mockSharingApi({ received: [READING, YOGA] });
    const { container } = renderApp(PATHS.invites);

    expect(await screen.findByRole('heading', { level: 1, name: 'Invites' })).toBeDefined();
    const card = await waitFor(() => inviteCard('Reading'));
    expect(within(card).getByText('From eva@example.com')).toBeDefined();
    expect(within(card).getByText('Can mark')).toBeDefined();
    expect(within(card).getByText('Received on Mar 1, 2026')).toBeDefined();
    expect(within(inviteCard('Yoga')).getByText('View only')).toBeDefined();
    expect(document.title).toBe('Invites · ethos');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows the empty inbox', async () => {
    signedIn();
    mockSharingApi({ received: [] });
    const { container } = renderApp(PATHS.invites);

    expect(await screen.findByText('You have no pending invites.')).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('accepting makes the habit appear in the habit list', async () => {
    signedIn();
    const habits = [habitFixture()];
    mockHabitsApi({ habits });
    const reading = habitFixture({ id: 9, name: 'Reading', code: null, color: 'indigo', role: 'editor' });
    const { requests } = mockSharingApi({ received: [READING, YOGA], habits, accepted: { 70: reading } });
    const user = userEvent.setup();
    renderApp('/');
    // A lista de hábitos já está no cache antes de aceitar
    await waitFor(() => expect(habitTab('RUN')).not.toBeNull());
    expect(habitTab('Reading')).toBeNull();

    await user.click(await waitFor(() => invitesLink()));
    await waitFor(() => inviteCard('Reading'));
    await user.click(within(inviteCard('Reading')).getByRole('button', { name: 'Accept' }));

    expect(await screen.findByText('You joined “Reading”.')).toBeDefined();
    expect(screen.queryByRole('heading', { level: 2, name: 'Reading' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('heading', { level: 1, name: 'Invites' }));
    expect(writes(requests)).toEqual(['POST /invites/70/accept']);
    // Sobra um convite pendente no menu
    expect(await screen.findByRole('link', { name: 'Invites 1 pending invite' })).toBeDefined();

    await user.click(screen.getByRole('link', { name: 'Open the habit' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Reading' })).toBeDefined();
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', { name: 'Habits' }));
    await waitFor(() => expect(habitTab('Reading')).not.toBeNull());
    expect(habitTab('RUN')).not.toBeNull();
  });

  it('declining removes the invite from the list', async () => {
    signedIn();
    const { requests } = mockSharingApi({ received: [READING, YOGA] });
    const user = userEvent.setup();
    renderApp(PATHS.invites);

    await waitFor(() => inviteCard('Yoga'));
    await user.click(within(inviteCard('Yoga')).getByRole('button', { name: 'Decline' }));

    expect(await screen.findByText('Invite to “Yoga” declined.')).toBeDefined();
    expect(screen.queryByRole('heading', { level: 2, name: 'Yoga' })).toBeNull();
    expect(inviteCard('Reading')).toBeDefined();
    expect(writes(requests)).toEqual(['POST /invites/71/decline']);
    expect(await screen.findByRole('link', { name: 'Invites 1 pending invite' })).toBeDefined();
  });

  it('keeps the invite and explains when the shared habit limit is reached', async () => {
    signedIn();
    mockSharingApi({
      received: [READING],
      fail: { 'POST /invites/70/accept': 'shared_habit_limit_reached' },
    });
    const user = userEvent.setup();
    const { container } = renderApp(PATHS.invites);

    await waitFor(() => inviteCard('Reading'));
    await user.click(within(inviteCard('Reading')).getByRole('button', { name: 'Accept' }));

    expect((await screen.findByRole('alert')).textContent).toContain('limit of habits shared with you');
    expect(inviteCard('Reading')).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('drops an invite that no longer exists', async () => {
    signedIn();
    const state = mockSharingApi({ received: [READING] });
    const user = userEvent.setup();
    renderApp(PATHS.invites);

    await waitFor(() => inviteCard('Reading'));
    // O dono cancelou enquanto a tela estava aberta
    state.received.splice(0);
    await user.click(within(inviteCard('Reading')).getByRole('button', { name: 'Accept' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Not found');
    expect(screen.queryByRole('heading', { level: 2, name: 'Reading' })).toBeNull();
    expect(screen.getByText('You have no pending invites.')).toBeDefined();
  });

  it('shows the error when the inbox does not load', async () => {
    signedIn();
    server.use(http.get(api('/invites'), () => HttpResponse.json({ error: 'forbidden', field: null }, { status: 403 })));
    renderApp(PATHS.invites);

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeDefined();
  });
});
