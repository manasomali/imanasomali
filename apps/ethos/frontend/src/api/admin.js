// Endpoints de /admin (app/admin/routes.py). O backend é quem garante o acesso (AdminUser): sem
// is_admin, 403. Listas paginadas por cursor (next_cursor), 50 por página

import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';

export const adminKeys = Object.freeze({
  all: ['admin'],
  users: ['admin', 'users'],
  accounts: (query) => ['admin', 'users', query],
  userHabits: (userId) => ['admin', 'user-habits', userId],
  userHabitsPage: (userId, habitId) => ['admin', 'user-habits', userId, habitId ?? null],
  banners: ['admin', 'banners'],
});

const pages = {
  initialPageParam: null,
  getNextPageParam: (last) => last.next_cursor ?? undefined,
};

/** Contas com os filtros de `accountQuery` (src/lib/admin.js): páginas de {users, next_cursor}. */
export function useAccounts(query) {
  return useInfiniteQuery({
    queryKey: adminKeys.accounts(query),
    queryFn: ({ pageParam, signal }) =>
      apiFetch('/admin/users', { query: { ...query, cursor: pageParam }, signal }),
    placeholderData: keepPreviousData,
    ...pages,
  });
}

/**
 * Conteúdo dos hábitos de uma conta: páginas de {user, habits, marks, next_cursor}. Cada chamada
 * grava `admin_viewed_habits` na auditoria, então nada busca de novo sozinho (foco na janela,
 * reconexão, dado "velho"): só ao montar (a tela monta depois do clique do admin), trocar o
 * filtro ou carregar mais.
 */
export function useAccountHabits(userId, habitId) {
  return useInfiniteQuery({
    queryKey: adminKeys.userHabitsPage(userId, habitId),
    // Sem o `signal`: cancelar no cliente não desfaz o registro no servidor, e com ele o React
    // Query cancela e busca de novo quando a tela remonta (StrictMode), gravando dois acessos
    queryFn: ({ pageParam }) =>
      apiFetch(`/admin/users/${userId}/habits`, { query: { habit_id: habitId, cursor: pageParam } }),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    placeholderData: keepPreviousData,
    ...pages,
  });
}

export function blockAccount(userId) {
  return apiFetch(`/admin/users/${userId}/block`, { method: 'POST' });
}

export function unblockAccount(userId) {
  return apiFetch(`/admin/users/${userId}/unblock`, { method: 'POST' });
}

/** 409 `email_in_use` (field new_email) quando o email já tem conta. */
export function changeAccountEmail(userId, newEmail) {
  return apiFetch(`/admin/users/${userId}/email`, {
    method: 'PATCH',
    body: { new_email: newEmail },
  });
}

/** 409 `last_admin` para a última conta de admin ativa. */
export function deleteAccount(userId) {
  return apiFetch(`/admin/users/${userId}`, { method: 'DELETE' });
}

/** Todos os banners, dos criados por último aos primeiros: páginas de {banners, next_cursor}. */
export function useBanners() {
  return useInfiniteQuery({
    queryKey: adminKeys.banners,
    queryFn: ({ pageParam, signal }) =>
      apiFetch('/admin/banners', { query: { cursor: pageParam }, signal }),
    ...pages,
  });
}

/** `values`: {text_pt, text_en, starts_at, ends_at}, datas em ISO 8601 com fuso. */
export function createBanner(values) {
  return apiFetch('/admin/banners', { method: 'POST', body: values });
}

/** Só os campos que mudam (ausente não muda; null é recusado). */
export function updateBanner(bannerId, values) {
  return apiFetch(`/admin/banners/${bannerId}`, { method: 'PATCH', body: values });
}

export function endBanner(bannerId) {
  return apiFetch(`/admin/banners/${bannerId}/end`, { method: 'POST' });
}
