import { describe, expect, it } from 'vitest';
import { createMemoryRouter } from 'react-router';
import { BASENAME } from '../paths';
import { page } from './page';
import { loginUrl, redirectToLogin } from './session';

function routerAt(path) {
  const routes = [{ path: '*', element: null }];
  return createMemoryRouter(routes, { basename: BASENAME, initialEntries: [path] });
}

describe('loginUrl', () => {
  it.each([
    [{ pathname: '/ethos/relatorio', search: '?from=2026-01-01', hash: '#x' }, '/ethos/relatorio?from=2026-01-01#x'],
    [{ pathname: '/ethos' }, '/ethos'],
    [{ pathname: '/ethos/' }, '/ethos/'],
    [{ pathname: '/ethos/habits/3/alerts', search: '', hash: '' }, '/ethos/habits/3/alerts'],
    // Fora do app: volta para a tela inicial
    [{ pathname: '/outro' }, '/ethos/'],
    [{ pathname: '/ethosx/a' }, '/ethos/'],
  ])('goes to the imago login with next for %j', (location, next) => {
    const url = new URL(loginUrl(location), 'https://manasomali.com');

    expect(url.pathname).toBe('/imago/entrar');
    expect([...url.searchParams.keys()]).toEqual(['next']);
    expect(url.searchParams.get('next')).toBe(next);
  });

  it('encodes the next path', () => {
    expect(loginUrl({ pathname: '/ethos/historico', search: '?habit_id=3&event=a b' })).toBe(
      '/imago/entrar?next=%2Fethos%2Fhistorico%3Fhabit_id%3D3%26event%3Da+b',
    );
  });
});

describe('redirectToLogin', () => {
  it('leaves the app for the imago login, keeping where the person was', () => {
    redirectToLogin(routerAt(`${BASENAME}/relatorio?from=2026-01-01#fim`));

    expect(page.assign).toHaveBeenCalledExactlyOnceWith(
      `/imago/entrar?next=${encodeURIComponent('/ethos/relatorio?from=2026-01-01#fim')}`,
    );
  });

  it('comes back to the home screen of the app', () => {
    redirectToLogin(routerAt(BASENAME));

    expect(page.assign).toHaveBeenCalledExactlyOnceWith(`/imago/entrar?next=${encodeURIComponent('/ethos')}`);
  });
});
