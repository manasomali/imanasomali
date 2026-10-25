import { HttpResponse, http } from 'msw';
import { API_BASE } from '../lib/api';
import { api, server } from './server';

/** Um membro como no GET /habits/{id}/members. */
export function memberFixture(id, email, role, joinedAt = '2026-02-01T12:00:00Z') {
  return { user: { id, email }, role, joined_at: joinedAt };
}

/** Um convite pendente como no GET /habits/{id}/invites. */
export function pendingInviteFixture(overrides = {}) {
  return {
    id: 50,
    email: 'dora@example.com',
    role: 'viewer',
    created_at: '2026-03-01T12:00:00Z',
    ...overrides,
  };
}

/** Um convite recebido como no GET /invites. */
export function receivedInviteFixture(overrides = {}) {
  return {
    id: 70,
    habit: { id: 9, name: 'Reading', color: 'indigo' },
    owner: { id: 4, email: 'eva@example.com' },
    role: 'editor',
    created_at: '2026-03-01T12:00:00Z',
    ...overrides,
  };
}

/**
 * API falsa do compartilhamento, com estado: `members` e `invites` (do hábito, por id), `received`
 * (do usuário) mudam como na API. Convidar responde sempre 202 `{status: "sent"}` e só cria o
 * pendente se o email ainda não é membro nem tem convite. Aceitar põe o hábito de `accepted` (id do
 * convite → HabitOut) em `habits` (o array do mockHabitsApi), como o GET /habits passaria a
 * devolver. `fail` (ex.: `{'POST /habits/1/invites': 'guest_limit_reached'}`) responde 409 com o
 * código. Devolve `requests` (`{method, path, body}`) e o estado.
 */
export function mockSharingApi({
  members = {},
  invites = {},
  received = [],
  guestLimit = 5,
  habits = [],
  accepted = {},
  fail = {},
} = {}) {
  const requests = [];
  let nextInvite = 1000;

  const handle = (respond) => async ({ request, params }) => {
    const url = new URL(request.url);
    const path = url.pathname.slice(API_BASE.length);
    const text = await request.text();
    const body = text ? JSON.parse(text) : null;
    requests.push({ method: request.method, path, body });
    const code = fail[`${request.method} ${path}`];
    if (code) return HttpResponse.json({ error: code, field: null }, { status: 409 });
    return respond({ params, body });
  };
  const noContent = () => new HttpResponse(null, { status: 204 });
  const removeFrom = (list, match) => {
    const index = list.findIndex(match);
    if (index >= 0) list.splice(index, 1);
    return index >= 0;
  };
  const notFound = () => HttpResponse.json({ error: 'not_found', field: null }, { status: 404 });

  server.use(
    http.get(api('/habits/:id/members'), handle(({ params }) =>
      HttpResponse.json({ members: members[params.id] ?? [], guest_limit: guestLimit }),
    )),
    http.get(api('/habits/:id/invites'), handle(({ params }) =>
      HttpResponse.json({ invites: invites[params.id] ?? [] }),
    )),
    http.post(api('/habits/:id/invites'), handle(({ params, body }) => {
      const list = (invites[params.id] ??= []);
      const known = (members[params.id] ?? []).some((member) => member.user.email === body.email)
        || list.some((invite) => invite.email === body.email);
      if (!known) {
        list.push(pendingInviteFixture({ id: nextInvite++, email: body.email, role: body.role }));
      }
      return HttpResponse.json({ status: 'sent' }, { status: 202 });
    })),
    http.delete(api('/habits/:id/invites/:inviteId'), handle(({ params }) =>
      removeFrom(invites[params.id] ?? [], (invite) => invite.id === Number(params.inviteId))
        ? noContent()
        : notFound(),
    )),
    http.patch(api('/habits/:id/members/:userId'), handle(({ params, body }) => {
      const member = (members[params.id] ?? []).find((item) => item.user.id === Number(params.userId));
      if (!member) return notFound();
      member.role = body.role;
      return HttpResponse.json(member);
    })),
    http.delete(api('/habits/:id/members/:userId'), handle(({ params }) =>
      removeFrom(members[params.id] ?? [], (item) => item.user.id === Number(params.userId))
        ? noContent()
        : notFound(),
    )),
    http.post(api('/habits/:id/leave'), handle(({ params }) => {
      removeFrom(habits, (habit) => habit.id === Number(params.id));
      return noContent();
    })),
    http.get(api('/invites'), handle(() => HttpResponse.json({ invites: received }))),
    http.post(api('/invites/:inviteId/accept'), handle(({ params }) => {
      if (!removeFrom(received, (invite) => invite.id === Number(params.inviteId))) return notFound();
      const habit = accepted[params.inviteId];
      habits.push(habit);
      return HttpResponse.json(habit);
    })),
    http.post(api('/invites/:inviteId/decline'), handle(({ params }) =>
      removeFrom(received, (invite) => invite.id === Number(params.inviteId)) ? noContent() : notFound(),
    )),
  );
  return { requests, members, invites, received };
}

/** As escritas (fora de GET) que chegaram, como "MÉTODO caminho". */
export function writes(requests) {
  return requests.filter((request) => request.method !== 'GET').map((r) => `${r.method} ${r.path}`);
}
