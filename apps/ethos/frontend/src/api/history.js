// Histórico (GET /history). Regras de quem vê o quê ficam no backend (app/history/service.py). Os
// membros do hábito do filtro de autor vêm de useMembers (src/api/sharing.js)

import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';

export const historyKeys = Object.freeze({
  all: ['history'],
  // `query`: o resultado de historyQuery (src/lib/history.js), sem o cursor
  list: (query) => ['history', query],
});

/**
 * Páginas do histórico ({events, next_cursor}, 50 eventos por página, do mais recente ao mais
 * antigo) com os filtros de `query`. Trocar os filtros mantém a lista anterior na tela até a nova
 * chegar (`isPlaceholderData`).
 */
export function useHistory(query, { enabled = true } = {}) {
  return useInfiniteQuery({
    queryKey: historyKeys.list(query),
    queryFn: ({ pageParam, signal }) =>
      apiFetch('/history', { query: { ...query, cursor: pageParam }, signal }),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
    enabled,
  });
}

/**
 * Autores ({id, email}) dos eventos de todos os históricos no cache (os filtros já vistos), com
 * repetição; autor null ("usuário removido") fica de fora.
 */
export function seenHistoryAuthors(queryClient) {
  const authors = [];
  for (const [, data] of queryClient.getQueriesData({ queryKey: historyKeys.all })) {
    for (const page of data?.pages ?? []) {
      for (const event of page.events) {
        if (event.author) authors.push(event.author);
      }
    }
  }
  return authors;
}
