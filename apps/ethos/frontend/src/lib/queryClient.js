// QueryClient do app (TanStack Query) com o tratamento global dos erros da API:
// - 401: a sessão acabou ou não existe; chama onUnauthorized (o app leva para o login);
// - 403 e 429: não repete; a tela mostra a mensagem do código (ex.: "tente mais tarde");
// - rede e 5xx: repete a leitura até 2 vezes. Escritas nunca repetem sozinhas.

import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';
import { ApiError } from './api';

const MAX_RETRIES = 2;

/** Repete só falhas passageiras: sem resposta (status 0) ou 5xx. */
export function shouldRetry(failureCount, error) {
  if (failureCount >= MAX_RETRIES || !(error instanceof ApiError)) return false;
  return error.status === 0 || error.status >= 500;
}

export function createQueryClient({ onUnauthorized } = {}) {
  const onError = (error) => {
    if (error instanceof ApiError && error.status === 401) onUnauthorized?.(error);
  };
  return new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: { retry: shouldRetry, staleTime: 30_000 },
      mutations: { retry: false },
    },
  });
}
