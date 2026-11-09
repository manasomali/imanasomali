import { render } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import App from '../App';
import { createApp } from '../bootstrap';
import { BASENAME } from '../paths';

/** Monta o app inteiro (rotas, QueryClient e tratamento do 401) em `path` (ex.: "/relatorio"). */
export function renderApp(path = '/') {
  const { router, queryClient } = createApp({
    createRouter: createMemoryRouter,
    routerOptions: { initialEntries: [`${BASENAME}${path}`] },
  });
  const result = render(<App router={router} queryClient={queryClient} />);
  return { router, queryClient, ...result };
}

/** Resposta do GET /me (o usuário que o imago mandou nos headers). */
export function meFixture(overrides = {}) {
  return {
    id: 1,
    email: 'ana@example.com',
    timezone: 'America/Sao_Paulo',
    locale: 'pt',
    is_admin: false,
    ...overrides,
  };
}
