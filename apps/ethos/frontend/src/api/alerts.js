// Alerta do usuário logado num hábito (ETH-26): GET/PUT /habits/{id}/alerts. A resposta é o
// AlertOut `{goal_enabled, cost_enabled, hour, frequency, weekday, last_sent_at}`; sem nada salvo,
// a padrão (tudo desligado, 20h, diário). Viewer recebe 403; hábito arquivado lê, mas salvar dá
// 409 `habit_archived`

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';
import { habitKeys } from './habits';

export const alertKeys = Object.freeze({
  all: ['alerts'],
  detail: (habitId) => ['alerts', habitId],
});

export function fetchAlert(habitId, { signal } = {}) {
  return apiFetch(`/habits/${habitId}/alerts`, { signal });
}

/** PUT: troca a configuração inteira (corpo de `alertPayload`) e devolve a salva. */
export function saveAlert(habitId, values) {
  return apiFetch(`/habits/${habitId}/alerts`, { method: 'PUT', body: values });
}

/** A configuração de alerta do hábito. `enabled: false` não busca (ex.: viewer, que daria 403). */
export function useAlert(habitId, { enabled = true } = {}) {
  return useQuery({
    queryKey: alertKeys.detail(habitId),
    queryFn: ({ signal }) => fetchAlert(habitId, { signal }),
    enabled,
  });
}

// O hábito mudou em outro lugar desde que a aba o carregou: foi arquivado (409), o papel virou
// viewer (403) ou o acesso acabou (404). Buscar o hábito de novo põe a tela no estado certo
const STALE_HABIT_ERRORS = new Set(['habit_archived', 'forbidden', 'not_found']);

export function useSaveAlert(habitId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (values) => saveAlert(habitId, values),
    onSuccess: (alert) => queryClient.setQueryData(alertKeys.detail(habitId), alert),
    onError: (error) => {
      if (STALE_HABIT_ERRORS.has(error?.code)) {
        queryClient.invalidateQueries({ queryKey: habitKeys.all });
      }
    },
  });
}
