// Hábitos (GET /habits e GET /habits/{id}). Cada hábito é o HabitOut da API: configuração,
// `label` (a sigla, ou o nome), `role` de quem pede (owner, editor, viewer), `status` (active,
// paused, archived) e, só com a pontuação ligada, `score: {value, success}` (value null: "sem
// dados")

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';

// Chaves do cache. Invalide `habitKeys.all` depois de mudar a configuração de um hábito (ETH-33),
// e `habitKeys.lists()` + `habitKeys.detail(id)` quando a pontuação pode mudar (marcações)
export const habitKeys = Object.freeze({
  all: ['habits'],
  lists: () => ['habits', 'list'],
  list: ({ archived = false } = {}) => ['habits', 'list', { archived }],
  detail: (id) => ['habits', 'detail', id],
});

/** `{habits: [...]}`: ativos e pausados, ou só os arquivados com `archived`. */
export function fetchHabits({ archived = false, signal } = {}) {
  return apiFetch('/habits', { query: archived ? { archived: true } : undefined, signal });
}

export function fetchHabit(id, { signal } = {}) {
  return apiFetch(`/habits/${id}`, { signal });
}

/** Lista de hábitos (`data` é o array). `enabled: false` adia a busca (ex.: arquivados). */
export function useHabits({ archived = false, enabled = true } = {}) {
  return useQuery({
    queryKey: habitKeys.list({ archived }),
    queryFn: ({ signal }) => fetchHabits({ archived, signal }),
    select: (data) => data.habits,
    enabled,
  });
}

/** Um hábito. Enquanto busca, mostra o que já veio na lista (sem piscar ao abrir a aba). */
export function useHabit(id) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: habitKeys.detail(id),
    queryFn: ({ signal }) => fetchHabit(id, { signal }),
    placeholderData: () => {
      for (const [, data] of queryClient.getQueriesData({ queryKey: habitKeys.lists() })) {
        const habit = data?.habits?.find((item) => item.id === id);
        if (habit) return habit;
      }
      return undefined;
    },
  });
}

/** Dono e editor marcam; arquivado é só leitura (a API responde 403 e 409 `habit_archived`). */
export function canMark(habit) {
  return habit.role !== 'viewer' && habit.status !== 'archived';
}
