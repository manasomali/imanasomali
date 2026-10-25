// Hábitos (GET /habits e GET /habits/{id}). Cada hábito é o HabitOut da API: configuração,
// `label` (a sigla, ou o nome), `role` de quem pede (owner, editor, viewer), `status` (active,
// paused, archived) e, só com a pontuação ligada, `score: {value, success}` (value null: "sem
// dados"). Também as escritas do dono: criar, editar, pausar, retomar, arquivar, desarquivar e
// apagar

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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

/** POST /habits: o hábito criado (HabitOut). 409 `habit_limit_reached` no limite de hábitos. */
export function createHabit(values) {
  return apiFetch('/habits', { method: 'POST', body: values });
}

/** PATCH /habits/{id} com só os campos que mudaram: o hábito salvo. */
export function updateHabit(id, values) {
  return apiFetch(`/habits/${id}`, { method: 'PATCH', body: values });
}

/** Ações de status, cada uma um POST sem corpo que devolve o hábito. */
export const HABIT_STATUS_ACTIONS = Object.freeze(['pause', 'resume', 'archive', 'unarchive']);

export function changeHabitStatus(id, action) {
  if (!HABIT_STATUS_ACTIONS.includes(action)) throw new RangeError(`ação desconhecida: ${action}`);
  return apiFetch(`/habits/${id}/${action}`, { method: 'POST' });
}

export function deleteHabit(id) {
  return apiFetch(`/habits/${id}`, { method: 'DELETE' });
}

/**
 * Depois de uma escrita que devolve o hábito: guarda a resposta no detalhe (a tela muda sem
 * esperar) e invalida o resto dos hábitos (listas, abas, pontuação). As marcações não mudam. A
 * escrita termina sem esperar essas buscas.
 */
export function habitSaved(queryClient, habit) {
  queryClient.setQueryData(habitKeys.detail(habit.id), habit);
  queryClient.invalidateQueries({ queryKey: habitKeys.all });
}

/** Criar um hábito: `mutate(values)`. */
export function useCreateHabit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createHabit,
    onSuccess: (habit) => habitSaved(queryClient, habit),
  });
}

/** Editar o hábito `id`: `mutate(values)` com só os campos que mudaram. */
export function useUpdateHabit(id) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (values) => updateHabit(id, values),
    onSuccess: (habit) => habitSaved(queryClient, habit),
  });
}

/** Pausar, retomar, arquivar ou desarquivar o hábito `id`: `mutate(action)`. */
export function useHabitStatus(id) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action) => changeHabitStatus(id, action),
    onSuccess: (habit) => habitSaved(queryClient, habit),
  });
}

/**
 * Apagar o hábito `id`. Quem chama sai da aba do hábito no `onSuccess` do `mutate` e só depois
 * chama `forgetHabit`, para a aba não buscar de novo um hábito que não existe mais (404).
 */
export function useDeleteHabit(id) {
  return useMutation({ mutationFn: () => deleteHabit(id) });
}

/**
 * Tira o hábito apagado do cache e atualiza o resto sob `habitKeys.all` (listas e relatório),
 * menos o detalhe dele, que daria 404.
 */
export function forgetHabit(queryClient, id) {
  const detail = habitKeys.detail(id);
  queryClient.removeQueries({ queryKey: detail, type: 'inactive' });
  queryClient.invalidateQueries({
    queryKey: habitKeys.all,
    predicate: (query) => !detail.every((part, index) => query.queryKey[index] === part),
  });
}
