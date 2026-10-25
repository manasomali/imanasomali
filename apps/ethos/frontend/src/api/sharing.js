// Compartilhamento (app/sharing/routes.py): membros e convites de um hábito, e a caixa de convites
// recebidos. Papéis: só o dono convida, cancela, troca papel e remove; todo membro vê a lista de
// membros; editor e viewer podem sair. O backend é quem garante (403/404)
//
// Cache da caixa de recebidos (o menu mostra quantos estão pendentes em toda tela com sessão):
// sem polling. A lista vale por RECEIVED_STALE_TIME e é buscada de novo ao voltar para a aba do
// navegador (refetchOnWindowFocus, só se já passou desse tempo), ao abrir a tela de convites e
// depois de aceitar ou recusar. Um convite novo aparece, no pior caso, quando a pessoa volta para
// a aba depois de alguns minutos ou abre a tela de convites

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';

export const RECEIVED_STALE_TIME = 5 * 60_000;

export const sharingKeys = Object.freeze({
  all: ['sharing'],
  habit: (habitId) => ['sharing', 'habit', habitId],
  members: (habitId) => ['sharing', 'habit', habitId, 'members'],
  invites: (habitId) => ['sharing', 'habit', habitId, 'invites'],
  received: ['sharing', 'received'],
});

/** `{members: [{user: {id, email}, role, joined_at}], guest_limit}`, o dono primeiro. */
export function useMembers(habitId) {
  return useQuery({
    queryKey: sharingKeys.members(habitId),
    queryFn: ({ signal }) => apiFetch(`/habits/${habitId}/members`, { signal }),
  });
}

/** Convites pendentes do hábito (`data` é o array). Só o dono pode ver: passe `enabled`. */
export function useHabitInvites(habitId, { enabled = true } = {}) {
  return useQuery({
    queryKey: sharingKeys.invites(habitId),
    queryFn: ({ signal }) => apiFetch(`/habits/${habitId}/invites`, { signal }),
    select: (data) => data.invites,
    enabled,
  });
}

/**
 * Convites recebidos e pendentes (`data` é o array de `{id, habit: {id, name, color}, owner:
 * {id, email}, role, created_at}`). `enabled: false` no menu enquanto não há sessão; `fresh`
 * busca de novo ao montar mesmo dentro do RECEIVED_STALE_TIME (a tela de convites).
 */
export function useReceivedInvites({ enabled = true, fresh = false } = {}) {
  return useQuery({
    queryKey: sharingKeys.received,
    queryFn: ({ signal }) => apiFetch('/invites', { signal }),
    select: (data) => data.invites,
    staleTime: RECEIVED_STALE_TIME,
    refetchOnMount: fresh ? 'always' : true,
    enabled,
  });
}

/** `{email, role}`; a resposta é sempre a mesma (`{status: "sent"}`), com ou sem conta. */
export function sendInvite(habitId, { email, role }) {
  return apiFetch(`/habits/${habitId}/invites`, { method: 'POST', body: { email, role } });
}

export function cancelInvite(habitId, inviteId) {
  return apiFetch(`/habits/${habitId}/invites/${inviteId}`, { method: 'DELETE' });
}

/** Devolve o membro com o papel novo. */
export function changeMemberRole(habitId, userId, role) {
  return apiFetch(`/habits/${habitId}/members/${userId}`, { method: 'PATCH', body: { role } });
}

export function removeMember(habitId, userId) {
  return apiFetch(`/habits/${habitId}/members/${userId}`, { method: 'DELETE' });
}

export function leaveHabit(habitId) {
  return apiFetch(`/habits/${habitId}/leave`, { method: 'POST' });
}

/** Devolve o hábito (como no GET /habits/{id}), com o papel oferecido no convite. */
export function acceptInvite(inviteId) {
  return apiFetch(`/invites/${inviteId}/accept`, { method: 'POST' });
}

export function declineInvite(inviteId) {
  return apiFetch(`/invites/${inviteId}/decline`, { method: 'POST' });
}
