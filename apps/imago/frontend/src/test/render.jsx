import { render } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { createMemoryRouter } from 'react-router';
import App from '../App';
import { createApp } from '../bootstrap';
import { TERMS_VERSION } from '../lib/legal';
import { BASENAME } from '../paths';
import { api, apiError, server } from './server';

/** Monta o app inteiro (rotas, QueryClient e tratamento do 401) em `path` (ex.: "/admin"). */
export function renderApp(path = '/') {
  const { router, queryClient } = createApp({
    createRouter: createMemoryRouter,
    routerOptions: { initialEntries: [`${BASENAME}${path}`] },
  });
  const result = render(<App router={router} queryClient={queryClient} />);
  return { router, queryClient, ...result };
}

/** Resposta do GET /me: a conta 101 do seed (ana@example.com), com os termos em dia. */
export function meFixture(overrides = {}) {
  return {
    id: 101,
    email: 'ana@example.com',
    timezone: 'America/Sao_Paulo',
    locale: 'pt',
    is_admin: false,
    terms_version: TERMS_VERSION,
    current_terms_version: TERMS_VERSION,
    terms_pending: false,
    apps: ['ethos'],
    support_email: 'suporte@manasomali.com',
    ...overrides,
  };
}

/** GET /me com o usuário dado (ou o meFixture com `overrides`). */
export function signedIn(me = meFixture()) {
  server.use(http.get(api('/me'), () => HttpResponse.json(me)));
}

/** GET /me sem sessão (401). */
export function signedOut() {
  server.use(http.get(api('/me'), () => apiError(401, 'unauthorized')));
}
