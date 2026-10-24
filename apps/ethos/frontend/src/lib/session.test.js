import { describe, expect, it } from 'vitest';
import { createMemoryRouter } from 'react-router';
import { BASENAME, PATHS } from '../paths';
import { redirectToLogin, returnPath } from './session';

function routerAt(path) {
  const routes = [{ path: '*', element: null }];
  return createMemoryRouter(routes, { basename: BASENAME, initialEntries: [path] });
}

describe('redirectToLogin', () => {
  it('goes to the login keeping where the person was', async () => {
    const router = routerAt(`${BASENAME}/conta?tab=1#fuso`);

    redirectToLogin(router);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(router.state.location.pathname).toBe(`${BASENAME}${PATHS.login}`);
    expect(router.state.location.state).toEqual({ from: '/conta?tab=1#fuso' });
    expect(router.state.historyAction).toBe('REPLACE');
  });

  it('does nothing on the login itself', () => {
    const router = routerAt(`${BASENAME}${PATHS.login}`);
    const before = router.state.location;

    redirectToLogin(router);

    expect(router.state.location).toBe(before);
  });

  it('keeps the home path when the session ends there', async () => {
    const router = routerAt(BASENAME);

    redirectToLogin(router);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(router.state.location.state).toEqual({ from: '/' });
  });

  it('keeps a path outside the basename as is', async () => {
    const router = routerAt('/outro');

    redirectToLogin(router);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(router.state.location.state).toEqual({ from: '/outro' });
  });
});

describe('returnPath', () => {
  it('returns the saved internal path', () => {
    expect(returnPath({ state: { from: '/habitos/3/alertas?x=1' } })).toBe('/habitos/3/alertas?x=1');
  });

  it.each([
    undefined,
    null,
    {},
    { state: null },
    { state: { from: 42 } },
    { state: { from: 'https://evil.example' } },
    { state: { from: '//evil.example' } },
    { state: { from: '/\\evil.example' } },
    { state: { from: 'conta' } },
    { state: { from: PATHS.login } },
    { state: { from: `${PATHS.login}?x=1` } },
    { state: { from: `${PATHS.login}#y` } },
  ])('falls back to home for %j', (location) => {
    expect(returnPath(location)).toBe(PATHS.home);
  });
});
