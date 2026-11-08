// O usuário do ethos: GET /me. Login, sessão, termos, idioma, fuso e exclusão da conta ficam no
// imago (a conta única do manasomali.com, /imago/): o ethos só lê quem é a pessoa, que o nginx
// manda ao backend a partir do cookie do imago. Sem login, a API responde 401 e o QueryClient
// manda para /imago/entrar (src/lib/session.js)

import { useCallback, useSyncExternalStore } from 'react';
import { hashKey, notifyManager, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';

export const meQueryKey = ['me'];

/** {id, email, timezone, locale, is_admin}, como o imago mandou neste request. */
export function fetchMe({ signal } = {}) {
  return apiFetch('/me', { signal });
}

export function useMe() {
  return useQuery({ queryKey: meQueryKey, queryFn: fetchMe });
}

const meQueryHash = hashKey(meQueryKey);

/**
 * O usuário que o RequireSession já carregou, sem buscar (undefined antes disso). Para o que
 * aparece também nas telas públicas, como o menu: buscar ali levaria um 401 para o login. Lê o
 * cache direto (e não por um useQuery desligado).
 *
 * O cache avisa na hora, inclusive quando uma consulta nova entra nele durante o render de um
 * componente (o useQuery cria a consulta ali). Por isso o aviso passa pelo notifyManager, que o
 * entrega depois do render (como o próprio useQuery faz), e só vale para a consulta do /me:
 * avisar no meio do render dispararia o "Cannot update a component while rendering" do React.
 */
export function useCachedMe() {
  const queryClient = useQueryClient();
  const subscribe = useCallback(
    (onChange) =>
      queryClient.getQueryCache().subscribe(
        notifyManager.batchCalls((event) => {
          if (event.query.queryHash === meQueryHash) onChange();
        }),
      ),
    [queryClient],
  );
  return useSyncExternalStore(subscribe, () => queryClient.getQueryData(meQueryKey));
}
