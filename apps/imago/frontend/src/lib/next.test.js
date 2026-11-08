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
  ])('sends %j to the default', (next) => {
    expect(resolveNext(next, ORIGIN)).toBe(DEFAULT_NEXT);
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
