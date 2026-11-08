// Endpoints de /admin (app/admin/router.py). O backend é quem garante o acesso (require_admin):
// sem is_admin, 403. A lista de contas é paginada por cursor (next_cursor), 50 por página, das
// mais novas para as mais antigas

import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { accountApiPath } from '../lib/admin';
import { apiFetch } from '../lib/api';

export const adminKeys = Object.freeze({
  all: ['admin'],
  users: ['admin', 'users'],
  accounts: (query) => ['admin', 'users', query],
  mail: ['admin', 'mail'],
});

/** Contas com os filtros de `accountQuery` (src/lib/admin.js): páginas de {users, next_cursor}. */
export function useAccounts(query) {
  return useInfiniteQuery({
    queryKey: adminKeys.accounts(query),
    queryFn: ({ pageParam, signal }) =>
      apiFetch('/admin/users', { query: { ...query, cursor: pageParam }, signal }),
    placeholderData: keepPreviousData,
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/**
 * Bloqueia (`false`, apaga as sessões da conta) ou desbloqueia (`true`). Devolve o AdminUser.
 * 409 `cannot_block_self` para a própria conta e `last_admin` para o último admin ativo.
 */
export function setAccountActive(userId, isActive) {
  return apiFetch(accountApiPath(userId), { method: 'PATCH', body: { is_active: isActive } });
}

/** Troca o email (só pelo suporte). 409 `email_in_use` (field `new_email`) se o email já tem conta. */
export function changeAccountEmail(userId, newEmail) {
  return apiFetch(accountApiPath(userId, '/email'), {
    method: 'PATCH',
    body: { new_email: newEmail },
  });
}

/** Exclui a conta em todas as aplicações (204). 409 `last_admin` para o último admin ativo. */
export function deleteAccount(userId) {
  return apiFetch(accountApiPath(userId), { method: 'DELETE' });
}

/** Envios de email das últimas 24 h por aplicação e tipo, e as janelas do teto (MailStats). */
export function useMailStats() {
  return useQuery({
    queryKey: adminKeys.mail,
    queryFn: ({ signal }) => apiFetch('/admin/mail', { signal }),
  });
}
