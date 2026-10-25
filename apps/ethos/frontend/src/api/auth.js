// Endpoints de /auth. O fuso e o idioma do navegador só vão para a API no primeiro acesso
// (POST /auth/code/verify); depois, só PATCH /auth/me pela tela de conta, por escolha da pessoa

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
 * O usuário que o RequireSession já carregou, sem buscar (undefined antes disso). Para o que
 * aparece também nas telas públicas, como o menu: buscar ali levaria um 401 para o login.
 */
export function useCachedMe() {
  return useQuery({ queryKey: meQueryKey, queryFn: fetchMe, enabled: false }).data;
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

/**
 * Sair: encerra a sessão, vai para o login e só então limpa o cache (antes, a tela que ainda está
 * montada buscaria o /me de novo). Sem sessão (401), o QueryClient já leva para o login.
 */
export function useLogout() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      await navigate(PATHS.login, { replace: true });
      queryClient.clear();
    },
  });
}
