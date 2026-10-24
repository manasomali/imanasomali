import { createBrowserRouter } from 'react-router';
import { createQueryClient } from './lib/queryClient';
import { redirectToLogin } from './lib/session';
import { BASENAME } from './paths';
import { routes } from './routes';

/**
 * Router (basename /ethos) e QueryClient ligados: um 401 em qualquer chamada leva para o login.
 * Os testes passam createMemoryRouter e as initialEntries em `routerOptions`.
 */
export function createApp({ createRouter = createBrowserRouter, routerOptions } = {}) {
  const router = createRouter(routes, { basename: BASENAME, ...routerOptions });
  const queryClient = createQueryClient({ onUnauthorized: () => redirectToLogin(router) });
  return { router, queryClient };
}
