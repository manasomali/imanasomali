import { setupServer } from 'msw/node';
import { API_BASE } from '../lib/api';

// Servidor do MSW de todos os testes; cada teste registra os handlers com server.use(...)
export const server = setupServer();

/** URL absoluta de um endpoint da API (ex.: api('/auth/me')), para os handlers do MSW. */
export function api(path) {
  return `${window.location.origin}${API_BASE}${path}`;
}
