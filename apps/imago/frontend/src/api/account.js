// Endpoints da conta: /auth (código, sair) e /me. O fuso e o idioma do navegador só vão para a API
// no primeiro acesso (POST /auth/code/verify); depois, só PATCH /me pela tela de conta, por escolha
// da pessoa

import { useCallback, useSyncExternalStore } from 'react';
import { hashKey, notifyManager, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { apiFetch } from '../lib/api';
import { TERMS_VERSION } from '../lib/legal';
import { apiLocale } from '../lib/locale';
import { browserTimezone } from '../lib/time';
import { PATHS } from '../paths';

export const meQueryKey = ['me'];

const meQueryHash = hashKey(meQueryKey);

/**
 * {id, email, timezone, locale, is_admin, terms_version, current_terms_version, terms_pending,
 * apps, support_email}. Funciona com termos pendentes; sem sessão, 401.
 */
export function fetchMe({ signal } = {}) {
  return apiFetch('/me', { signal });
}

/** O usuário logado. `options` acrescenta opções do useQuery (a tela de entrar busca de novo). */
export function useMe(options = {}) {
  return useQuery({ queryKey: meQueryKey, queryFn: fetchMe, ...options });
}

/**
 * O usuário já carregado por outra tela, sem buscar, e só se a última busca deu certo (undefined
 * antes disso, depois de sair e depois de um 401). Para o que aparece também nas telas públicas,
 * como o menu: buscar ali levaria um 401 para a tela de entrar. Lê o estado do cache direto, porque
 * o queryClient.clear() do sair não avisa os observadores das consultas apagadas.
 *
 * O cache avisa na hora, inclusive quando uma consulta nova entra nele durante o render de um
 * componente. Por isso o aviso passa pelo notifyManager, que o entrega depois do render (como o
 * próprio useQuery faz), e só vale para a consulta do /me.
 */
export function useSignedInMe() {
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
  const state = useSyncExternalStore(subscribe, () => queryClient.getQueryState(meQueryKey));
  return state?.status === 'success' ? state.data : undefined;
}

/**
 * Pede o código de login. A API responde 202 igual para qualquer email (não revela se a conta
 * existe); 429 rate_limited quando o email ou o serviço passou do limite de envios.
 */
export function requestCode({ email }) {
  return apiFetch('/auth/code/request', { method: 'POST', body: { email } });
}

/**
 * Confirma o código e cria a sessão (o cookie vem no Set-Cookie). Numa conta nova, o fuso do
 * navegador e o idioma da tela viram os da conta; para quem já tem conta, a API os ignora.
 */
export function verifyCode({ email, code, language }) {
  return apiFetch('/auth/code/verify', {
    method: 'POST',
    body: { email, code, timezone: browserTimezone(), locale: apiLocale(language) },
  });
}

/**
 * Aceita os termos na versão que esta aba mostra (TERMS_VERSION do build) e devolve o /me novo. Se
 * o backend já estiver noutra versão, 409 conflict: a tela busca o /me de novo e pede para
 * recarregar a página, que traz os textos novos.
 */
export function acceptTerms() {
  return apiFetch('/me/terms', { method: 'POST', body: { terms_version: TERMS_VERSION } });
}

/** Encerra a sessão deste aparelho (204; a API apaga o cookie). */
export function logout() {
  return apiFetch('/auth/logout', { method: 'POST' });
}

/** Encerra todas as sessões da conta, inclusive a deste aparelho (204; a API apaga o cookie). */
export function logoutAll() {
  return apiFetch('/auth/logout-all', { method: 'POST' });
}

/**
 * Muda o fuso e/ou o idioma da conta (`{timezone}` ou `{locale}`; campo ausente não muda) e
 * devolve o /me novo. Fuso desconhecido: 422 `invalid_timezone` (field `timezone`). Com termos
 * pendentes, 403 `terms_not_accepted`. Só a tela de conta chama.
 */
export function updateMe(changes) {
  return apiFetch('/me', { method: 'PATCH', body: changes });
}

/**
 * Salva `{timezone}` ou `{locale}` da conta e guarda o /me da resposta. Idioma novo: vira também o
 * da tela, gravado pelo i18n na chave i18nextLng compartilhada com o site e as aplicações.
 */
export function useUpdateMe() {
  const queryClient = useQueryClient();
  const { i18n } = useTranslation();
  return useMutation({
    mutationFn: updateMe,
    onSuccess: (me, changes) => {
      queryClient.setQueryData(meQueryKey, me);
      if (changes.locale !== undefined) void i18n.changeLanguage(me.locale);
    },
  });
}

/**
 * Manda o código de exclusão para o email da conta (202). Último admin ativo: 409 `last_admin`;
 * limite de envios: 429 `rate_limited`.
 */
export function requestAccountDeletion() {
  return apiFetch('/me/delete/request', { method: 'POST' });
}

/**
 * Exclui a conta em todas as aplicações (204, sem o cookie). Código recusado: 400 `invalid_code`
 * (field `code`); último admin ativo: 409 `last_admin`.
 */
export function deleteAccount({ code }) {
  return apiFetch('/me', { method: 'DELETE', body: { code } });
}

// State da tela de entrar depois de excluir a conta (ela mostra o aviso)
export const ACCOUNT_DELETED_STATE = Object.freeze({ accountDeleted: true });

/**
 * Mutação que termina a sessão (`mutationFn`) e, se der certo, limpa o cache e vai para a tela de
 * entrar (com `state`). Limpa antes de navegar: assim a tela de entrar busca o /me do zero. Uma
 * busca que a tela de saída ainda faça recebe 401, e o redirecionamento do 401 não faz nada na
 * tela de entrar. Sem sessão (401), o QueryClient já leva para a tela de entrar.
 */
function useEndSession(mutationFn, state) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      queryClient.clear();
      await navigate(PATHS.login, { replace: true, state });
    },
  });
}

/** Sair deste aparelho. */
export function useLogout() {
  return useEndSession(logout);
}

/** Sair de todos os aparelhos (ex.: um aparelho perdido). */
export function useLogoutAll() {
  return useEndSession(logoutAll);
}

/** Excluir a conta: `mutate({code})`. Depois, o mesmo caminho do sair, com o aviso na tela de entrar. */
export function useDeleteAccount() {
  return useEndSession(deleteAccount, ACCOUNT_DELETED_STATE);
}
