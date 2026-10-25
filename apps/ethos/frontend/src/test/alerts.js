import { HttpResponse, http } from 'msw';
import { api, server } from './server';

/** Um AlertOut da API: sem nada salvo, a configuração padrão (desligada, 20h, diário). */
export function alertFixture(overrides = {}) {
  return {
    goal_enabled: false,
    cost_enabled: false,
    hour: 20,
    frequency: 'daily',
    weekday: null,
    last_sent_at: null,
    ...overrides,
  };
}

/**
 * API falsa dos alertas: GET e PUT /habits/{id}/alerts sobre `alerts` (objeto id → AlertOut; sem
 * entrada, a padrão). O PUT troca tudo e mantém o `last_sent_at`, como a API. `fail({method, id,
 * body})` pode devolver uma resposta de erro no lugar da de sucesso. Devolve `requests`, com cada
 * chamada (`{method, path, body}`; body null sem corpo).
 */
export function mockAlertsApi({ alerts = {}, fail } = {}) {
  const requests = [];
  const record = async (request, params) => {
    const text = await request.text();
    const entry = {
      method: request.method,
      path: new URL(request.url).pathname.replace(/^\/api\/ethos/, ''),
      body: text ? JSON.parse(text) : null,
    };
    requests.push(entry);
    return { ...entry, id: Number(params.id) };
  };

  server.use(
    http.get(api('/habits/:id/alerts'), async ({ request, params }) => {
      const entry = await record(request, params);
      const failure = fail?.(entry);
      if (failure) return failure;
      return HttpResponse.json(alerts[entry.id] ?? alertFixture());
    }),
    http.put(api('/habits/:id/alerts'), async ({ request, params }) => {
      const entry = await record(request, params);
      const failure = fail?.(entry);
      if (failure) return failure;
      const saved = { ...entry.body, last_sent_at: alerts[entry.id]?.last_sent_at ?? null };
      alerts[entry.id] = saved;
      return HttpResponse.json(saved);
    }),
  );
  return { requests, alerts };
}
