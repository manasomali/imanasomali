import { onTestFinished } from 'vitest';
import { HttpResponse, http } from 'msw';
import { API_BASE } from '../lib/api';
import { meFixture } from './render';
import { api, server } from './server';

/** O admin dos testes do painel (fuso de São Paulo, UTC-3 sem horário de verão). */
export const ADMIN = meFixture({ id: 1, email: 'ana@example.com', is_admin: true });

/** GET /auth/me com o usuário dado (por padrão, o admin). */
export function signedIn(me = ADMIN) {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(me)));
}

/** Uma conta como no GET /admin/users. */
export function accountFixture(overrides = {}) {
  return {
    id: 2,
    email: 'bia@example.com',
    is_active: true,
    is_admin: false,
    timezone: 'Europe/Lisbon',
    locale: 'pt',
    created_at: '2026-10-01T12:00:00Z',
    last_login_at: '2026-10-20T15:30:00Z',
    habit_count: 3,
    mark_count: 42,
    ...overrides,
  };
}

/** Um banner como no GET /admin/banners. */
export function bannerFixture(overrides = {}) {
  return {
    id: 5,
    text_pt: 'Manutenção no sábado.',
    text_en: 'Maintenance on Saturday.',
    starts_at: '2026-10-20T12:00:00Z',
    ends_at: '2099-11-20T12:00:00Z',
    created_by: 1,
    created_at: '2026-10-19T12:00:00Z',
    updated_at: '2026-10-19T12:00:00Z',
    ...overrides,
  };
}

/**
 * Registra toda request que chega na API durante o teste: {method, path (sem /api/ethos),
 * query}. Não responde nada: os handlers do teste continuam respondendo.
 */
export function trackRequests() {
  const requests = [];
  const listener = ({ request }) => {
    const url = new URL(request.url);
    requests.push({
      method: request.method,
      path: url.pathname.slice(API_BASE.length),
      query: Object.fromEntries(url.searchParams),
    });
  };
  server.events.on('request:start', listener);
  onTestFinished(() => server.events.removeListener('request:start', listener));
  return requests;
}

/** Só as requests de /admin/... */
export function adminRequests(requests) {
  return requests.filter((request) => request.path.startsWith('/admin'));
}
