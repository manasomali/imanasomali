import { onTestFinished } from 'vitest';
import { HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { API_BASE } from '../lib/api';

/** URL absoluta de um endpoint da API (ex.: api('/me')), para os handlers do MSW. */
export function api(path) {
  return `${window.location.origin}${API_BASE}${path}`;
}

/** Resposta de erro no formato da API: {"error", "field"}. */
export function apiError(status, error, field = null) {
  return HttpResponse.json({ error, field }, { status });
}

/**
 * Registra toda request que chega na API durante o teste: {method, path (sem /api/imago), query,
 * body (JSON ou null)}. Não responde nada: os handlers do teste continuam respondendo.
 */
export function trackRequests() {
  const requests = [];
  const listener = async ({ request }) => {
    const url = new URL(request.url);
    const entry = {
      method: request.method,
      path: url.pathname.slice(API_BASE.length),
      query: Object.fromEntries(url.searchParams),
      body: null,
    };
    requests.push(entry);
    const text = await request.clone().text();
    if (text) entry.body = JSON.parse(text);
  };
  server.events.on('request:start', listener);
  onTestFinished(() => server.events.removeListener('request:start', listener));
  return requests;
}

// Servidor do MSW de todos os testes; cada teste registra os handlers com server.use(...). Nenhuma
// tela busca nada sem login além do GET /me, então não há handler padrão
export const server = setupServer();
