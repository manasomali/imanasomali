// Endpoints de /auth usados pela base. O fuso e o idioma do navegador só vão para a API no
// primeiro acesso (POST /auth/code/verify); depois, só PATCH /auth/me pela tela de conta, por
// escolha da pessoa

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';
import { browserTimezone } from '../lib/time';

export const meQueryKey = ['auth', 'me'];

/** {id, email, timezone, locale, is_admin, terms_version, current_terms_version, terms_pending} */
export function fetchMe({ signal } = {}) {
  return apiFetch('/auth/me', { signal });
}

export function useMe() {
  return useQuery({ queryKey: meQueryKey, queryFn: fetchMe });
}

/** Idioma da API ("pt" ou "en") a partir do idioma da tela (que pode vir como "pt-BR"). */
export function apiLocale(language) {
  return typeof language === 'string' && language.toLowerCase().startsWith('pt') ? 'pt' : 'en';
}

/** Confirma o código. Numa conta nova, o fuso e o idioma do navegador viram os da conta. */
export function verifyCode({ email, code, language }) {
  return apiFetch('/auth/code/verify', {
    method: 'POST',
    body: { email, code, timezone: browserTimezone(), locale: apiLocale(language) },
  });
}
