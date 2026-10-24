// Chave de tradução de um erro: errors.<codigo> dos translation.json, ou errors.unknown para um
// código sem tradução (ex.: código novo da API antes de o front ser atualizado) e para erros que
// não vieram da API

import { ApiError } from './api';

export const UNKNOWN_ERROR_KEY = 'errors.unknown';

/** `exists(key)` diz se a chave tem tradução (passe i18n.exists). */
export function errorKey(error, exists) {
  if (!(error instanceof ApiError)) return UNKNOWN_ERROR_KEY;
  const key = `errors.${error.code}`;
  return exists(key) ? key : UNKNOWN_ERROR_KEY;
}
