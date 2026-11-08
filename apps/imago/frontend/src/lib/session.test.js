import { describe, expect, it } from 'vitest';
import { createMemoryRouter } from 'react-router';
import { BASENAME, PATHS } from '../paths';
import { resolveNext } from './next';
import { loginPath, redirectToLogin } from './session';

function routerAt(path) {
  const routes = [{ path: '*', element: null }];
  return createMemoryRouter(routes, { basename: BASENAME, initialEntries: [path] });
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

/** O `next` da tela de entrar onde o router foi parar. */
function nextOf(router) {
  return new URLSearchParams(router.state.location.search).get('next');
}

describe('loginPath', () => {
  it('keeps the slashes readable and encodes the rest', () => {
    expect(loginPath('/imago/')).toBe('/entrar?next=/imago/');
    expect(loginPath('/imago/admin?a=1&b=2#c')).toBe('/entrar?next=/imago/admin%3Fa%3D1%26b%3D2%23c');
    expect(loginPath()).toBe(PATHS.login);
    expect(loginPath('')).toBe(PATHS.login);
  });

  it('round-trips through the query and the validation', () => {
    const next = '/imago/admin?a=1&b=2#c';
    const query = loginPath(next).split('?').slice(1).join('?');

    expect(resolveNext(new URLSearchParams(query).get('next'), 'https://manasomali.com')).toBe(next);
  });
});

describe('redirectToLogin', () => {
  it('goes to the login keeping the full path, with the basename, in `next`', async () => {
    const router = routerAt(`${BASENAME}/admin?status=blocked#lista`);

    redirectToLogin(router);
    await settle();

    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.login}`);
    expect(nextOf(router)).toBe('/imago/admin?status=blocked#lista');
    expect(router.state.historyAction).toBe('REPLACE');
  });

  it('sends the account page as /imago/', async () => {
    const router = routerAt(`${BASENAME}/`);

    redirectToLogin(router);
    await settle();

    expect(router.state.location.search).toBe('?next=/imago/');
  });

  it('does nothing on the login itself', () => {
    for (const path of [PATHS.login, `${PATHS.login}/`, '/ENTRAR']) {
      const router = routerAt(`${BASENAME}${path}?next=/ethos/`);
      const before = router.state.location;

      redirectToLogin(router);

      expect(router.state.location).toBe(before);
    }
  });
});
