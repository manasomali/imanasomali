import { describe, expect, it } from 'vitest';
import { DEFAULT_NEXT, appRoute, resolveNext, sameOriginPath } from './next';

const ORIGIN = 'https://manasomali.com';

/** O `next` como a tela de entrar recebe: a query da URL decodificada pelo URLSearchParams. */
function fromQuery(rawQuery) {
  return new URLSearchParams(rawQuery).get('next');
}

describe('resolveNext', () => {
  it.each([
    ['/ethos/', '/ethos/'],
    ['/ethos/habits/3?day=2026-03-04#notes', '/ethos/habits/3?day=2026-03-04#notes'],
    ['/imago/admin', '/imago/admin'],
    ['/imago/', '/imago/'],
    ['/', '/'],
    // Mesma origem escrita por inteiro, e caminhos que a URL normaliza
    ['https://manasomali.com/ethos/relatorio', '/ethos/relatorio'],
    ['/imago/../ethos/', '/ethos/'],
    ['ethos', '/ethos'],
  ])('keeps the same-origin path %s', (next, expected) => {
    expect(resolveNext(next, ORIGIN)).toBe(expected);
  });

  // Os casos da ETH-31, como chegam na query (o %09 é um tab)
  it.each([
    ['next=//evil.com'],
    ['next=https://evil.com'],
    ['next=/\\evil.com'],
    ['next=/%09/evil.com'],
    ['next=/imago/entrar'],
  ])('sends %s to /imago/', (query) => {
    expect(resolveNext(fromQuery(query), ORIGIN)).toBe('/imago/');
  });

  it.each([
    [null],
    [undefined],
    [''],
    [42],
    ['http://manasomali.com/ethos/'],
    ['https://manasomali.com.evil.com/'],
    ['https://manasomali.com@evil.com/'],
    ['///evil.com'],
    ['\\\\evil.com'],
    ['/ethos\\..\\..\\evil.com'],
    ['javascript:alert(1)'],
    ['data:text/html,<script>alert(1)</script>'],
    ['/\nevil.com'],
    ['/\r//evil.com'],
    ['/ethos/\u0000'],
    ['/ethos/\u007f'],
    ['/ethos/\u0085'],
    ['https://[::1'],
    // A própria tela de entrar, em qualquer grafia que o router aceita
    ['/imago/entrar/'],
    ['/IMAGO/ENTRAR'],
    ['/imago/%65ntrar'],
    ['/imago/entrar?next=/ethos/'],
    ['/imago/entrar#x'],
    ['https://manasomali.com/imago/entrar'],
    // Segmentos de ponto que deixam o pathname resolvido começando com "//" (outro host para o
    // navegador), inclusive com o ponto codificado e em maiúsculas
    ['/.//evil.com'],
    ['/..//evil.com'],
    ['/imago/..//evil.com'],
    ['/IMAGO/..//EVIL.COM'],
    ['/ethos/habits/../..//evil.com/x?y=1#z'],
    ['/%2e//evil.com'],
    ['/%2E//evil.com'],
    ['/%2e%2e//evil.com'],
    ['/%2E%2E//evil.com'],
    ['/.%2E//evil.com'],
    ['/%2e.//evil.com'],
    ['/.///evil.com'],
    ['/.//manasomali.com/ethos/'],
    ['/.//%2fevil.com'],
    ['/.//%5cevil.com'],
    ['/.//['],
    ['https://manasomali.com/.//evil.com'],
  ])('sends %j to the default', (next) => {
    expect(resolveNext(next, ORIGIN)).toBe(DEFAULT_NEXT);
  });

  // Como chegam na query: o URLSearchParams decodifica uma vez, e um %25 vira o "%" de um ponto
  // ou de uma barra codificados
  it.each([
    ['next=/%2e//evil.com'],
    ['next=/%2E%2E//evil.com'],
    ['next=/%252e//evil.com'],
    ['next=/%252E%252E//evil.com'],
    ['next=/%2e%2f/evil.com'],
    ['next=/%2E%2F%2Fevil.com'],
    ['next=/%2f/evil.com'],
    ['next=/%2F%2Fevil.com'],
    ['next=/%5c/evil.com'],
    ['next=/%5C%5Cevil.com'],
    ['next=/.%5c/evil.com'],
    ['next=/imago/..%2f%2fevil.com'],
  ])('sends %s to /imago/', (query) => {
    expect(resolveNext(fromQuery(query), ORIGIN)).toBe('/imago/');
  });

  // Barra e contrabarra codificadas no próprio `next` ficam no caminho (o navegador não as
  // decodifica no pathname): continuam na mesma origem
  it.each([
    ['/%2f/evil.com', '/%2f/evil.com'],
    ['/%2F%2Fevil.com', '/%2F%2Fevil.com'],
    ['/./%2f/evil.com', '/%2f/evil.com'],
    ['/%5c/evil.com', '/%5c/evil.com'],
    ['/.%5C/evil.com', '/.%5C/evil.com'],
    ['/imago/../%2e/ethos/', '/ethos/'],
  ])('keeps %s on the same origin as %s', (next, expected) => {
    const path = resolveNext(next, ORIGIN);

    expect(path).toBe(expected);
    expect(new URL(path, ORIGIN).origin).toBe(ORIGIN);
  });

  it('uses the page origin by default', () => {
    expect(resolveNext(`${window.location.origin}/ethos/`)).toBe('/ethos/');
    expect(resolveNext('https://evil.com/')).toBe(DEFAULT_NEXT);
  });

  it('defaults to the account page', () => {
    expect(DEFAULT_NEXT).toBe('/imago/');
  });
});

describe('sameOriginPath', () => {
  it('returns the path, query and hash of a same-origin URL', () => {
    expect(sameOriginPath('/a/b?c=1#d', ORIGIN)).toBe('/a/b?c=1#d');
    expect(sameOriginPath('https://evil.com/a', ORIGIN)).toBeNull();
  });

  it('refuses a path that resolves to one starting with "//"', () => {
    expect(new URL('/.//evil.com', ORIGIN).pathname).toBe('//evil.com');
    expect(sameOriginPath('/.//evil.com', ORIGIN)).toBeNull();
    expect(sameOriginPath('/%2E%2E//evil.com', ORIGIN)).toBeNull();
  });

  it('does not treat a decoding error as a login path', () => {
    expect(resolveNext('/imago/%E0%A4%A', ORIGIN)).toBe('/imago/%E0%A4%A');
  });
});

describe('appRoute', () => {
  it.each([
    ['/imago/', '/'],
    ['/imago', '/'],
    ['/imago/admin', '/admin'],
    ['/imago/admin?x=1#y', '/admin?x=1#y'],
    ['/imago?x=1', '/?x=1'],
    ['/imago#x', '/#x'],
  ])('routes %s inside the app as %s', (path, route) => {
    expect(appRoute(path)).toBe(route);
  });

  it.each(['/', '/ethos/', '/imagoX', '/imago-old/', '/api/imago/me'])('leaves %s to a full page navigation', (path) => {
    expect(appRoute(path)).toBeNull();
  });
});
