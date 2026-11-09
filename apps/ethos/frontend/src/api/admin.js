// Endpoints de /admin (app/admin/routes.py). O backend é quem garante o acesso (AdminUser, pelo
// X-User-Admin do imago): sem admin, 403. Listas paginadas por cursor (next_cursor), 50 por página.
// As contas (bloquear, trocar email, excluir) são do imago (/imago/admin)

import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';

export const adminKeys = Object.freeze({
  all: ['admin'],
  users: ['admin', 'users'],
  usersPage: (query) => ['admin', 'users', query],
  userHabits: (userId) => ['admin', 'user-habits', userId],
  userHabitsPage: (userId, habitId) => ['admin', 'user-habits', userId, habitId ?? null],
  banners: ['admin', 'banners'],
});

const pages = {
  initialPageParam: null,
  getNextPageParam: (last) => last.next_cursor ?? undefined,
};

/** Quem usa o ethos, com os filtros de `userQuery` (src/lib/admin.js): páginas de {users, next_cursor}. */
export function useAppUsers(query) {
  return useInfiniteQuery({
    queryKey: adminKeys.usersPage(query),
    queryFn: ({ pageParam, signal }) =>
      apiFetch('/admin/users', { query: { ...query, cursor: pageParam }, signal }),
    placeholderData: keepPreviousData,
    ...pages,
  });
}

/**
 * Conteúdo dos hábitos de uma pessoa: páginas de {user, habits, marks, next_cursor}. Cada chamada
 * grava `admin_viewed_habits` na auditoria, então nada busca de novo sozinho (foco na janela,
 * reconexão, dado "velho"): só ao montar (a tela monta depois do clique do admin), trocar o
 * filtro ou carregar mais.
 */
export function useUserHabits(userId, habitId) {
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
