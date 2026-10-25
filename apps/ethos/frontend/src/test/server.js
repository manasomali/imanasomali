import { HttpResponse, http } from 'msw';
import { setupServer } from 'msw/node';
import { API_BASE } from '../lib/api';

/** URL absoluta de um endpoint da API (ex.: api('/auth/me')), para os handlers do MSW. */
export function api(path) {
  return `${window.location.origin}${API_BASE}${path}`;
}

/** Handler do GET /banners/active com o banner dado (null: nenhum no ar). */
export function activeBanner(banner = null) {
  return http.get(api('/banners/active'), () => HttpResponse.json({ banner }));
}

// Servidor do MSW de todos os testes; cada teste registra os handlers com server.use(...), que
// passam na frente destes padrões. O Layout busca o banner em toda tela: sem banner, por padrão
export const server = setupServer(activeBanner());
