// Endpoints de /auth. O fuso e o idioma do navegador só vão para a API no primeiro acesso
// (POST /auth/code/verify); depois, só PATCH /auth/me pela tela de conta, por escolha da pessoa

import { useCallback, useSyncExternalStore } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { apiFetch } from '../lib/api';
import { TERMS_VERSION } from '../lib/legal';
import { browserTimezone } from '../lib/time';
import { PATHS } from '../paths';

export const meQueryKey = ['auth', 'me'];

/** {id, email, timezone, locale, is_admin, terms_version, current_terms_version, terms_pending} */
export function fetchMe({ signal } = {}) {
  return apiFetch('/auth/me', { signal });
}

export function useMe() {
  return useQuery({ queryKey: meQueryKey, queryFn: fetchMe });
}

/**
 * O usuário que o RequireSession já carregou, sem buscar (undefined antes disso e depois de sair).
 * Para o que aparece também nas telas públicas, como o menu: buscar ali levaria um 401 para o
 * login. Lê o cache direto (e não por um useQuery desligado), porque o queryClient.clear() do
 * sair não avisa os observadores das consultas apagadas.
 */
export function useCachedMe() {
  const queryClient = useQueryClient();
  const subscribe = useCallback(
    (onChange) => queryClient.getQueryCache().subscribe(onChange),
    [queryClient],
  );
  return useSyncExternalStore(subscribe, () => queryClient.getQueryData(meQueryKey));
}

/** Idioma da API ("pt" ou "en") a partir do idioma da tela (que pode vir como "pt-BR"). */
export function apiLocale(language) {
  return typeof language === 'string' && language.toLowerCase().startsWith('pt') ? 'pt' : 'en';
}

/**
 * Pede o código de login. A API responde 202 igual para qualquer email (não revela se a conta
 * existe); 429 rate_limited quando o email ou o serviço passou do limite de envios.
 */
export function requestCode({ email }) {
  return apiFetch('/auth/code/request', { method: 'POST', body: { email } });
}

/** Confirma o código. Numa conta nova, o fuso e o idioma do navegador viram os da conta. */
export function verifyCode({ email, code, language }) {
  return apiFetch('/auth/code/verify', {
    method: 'POST',
    body: { email, code, timezone: browserTimezone(), locale: apiLocale(language) },
  });
}

/**
 * Aceita os termos na versão que esta aba mostra (TERMS_VERSION do build). Se o backend já estiver
 * noutra versão, 409 conflict: a tela recarrega o /me e pede para recarregar os textos.
 */
export function acceptTerms() {
  return apiFetch('/auth/me/terms', { method: 'POST', body: { terms_version: TERMS_VERSION } });
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
 * Muda o fuso e/ou o idioma da conta (`{timezone, locale}`; campo ausente não muda) e devolve o
 * /me novo. Fuso desconhecido: 422 `invalid_timezone` (field `timezone`). Só a tela de conta chama.
 */
export function updateMe(changes) {
  return apiFetch('/auth/me', { method: 'PATCH', body: changes });
}

/**
 * Salva `{timezone}` e/ou `{locale}` da conta. Guarda o /me da resposta e busca de novo (duas
 * mudanças cruzadas podem responder fora de ordem). Fuso novo: tudo o que já foi buscado fica
 * velho (dias, pontuações, relatório e histórico dependem dele). Idioma novo: vira também o da
 * tela, gravado pelo i18n na chave i18nextLng compartilhada com o site.
 */
export function useUpdateMe() {
  const queryClient = useQueryClient();
  const { i18n } = useTranslation();
  return useMutation({
    mutationFn: updateMe,
    onSuccess: (me, changes) => {
      queryClient.setQueryData(meQueryKey, me);
      void queryClient.invalidateQueries({ queryKey: meQueryKey });
      if (changes.timezone !== undefined) {
        void queryClient.invalidateQueries({
          predicate: (query) => query.queryKey[0] !== meQueryKey[0],
        });
      }
      if (changes.locale !== undefined) void i18n.changeLanguage(me.locale);
    },
  });
}

/**
 * Manda o código de exclusão para o email da conta (202). Último admin ativo: 409 `last_admin`;
 * limite de envios: 429 `rate_limited`.
 */
export function requestAccountDeletion() {
  return apiFetch('/auth/me/delete/request', { method: 'POST' });
}

/** Apaga a conta (204, sem o cookie). Código recusado: 400 `invalid_code` (field `code`). */
export function deleteAccount({ code }) {
  return apiFetch('/auth/me', { method: 'DELETE', body: { code } });
}

// State do login depois de excluir a conta (a tela de login mostra o aviso)
export const ACCOUNT_DELETED_STATE = Object.freeze({ accountDeleted: true });

/**
 * Mutação que termina a sessão (`mutationFn`) e, se der certo, vai para o login (com `state`) e só
 * então limpa o cache: antes, a tela que ainda está montada buscaria o /me de novo. Sem sessão
 * (401), o QueryClient já leva para o login.
 */
function useEndSession(mutationFn, state) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      await navigate(PATHS.login, { replace: true, state });
      queryClient.clear();
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

/** Excluir a conta: `mutate({code})`. Depois, o mesmo caminho do sair, com o aviso no login. */
export function useDeleteAccount() {
  return useEndSession(deleteAccount, ACCOUNT_DELETED_STATE);
}
