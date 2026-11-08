// Destino depois do login (`/imago/entrar?next=<caminho>`, imago-plan.md, "login"). As aplicações
// mandam para cá com o caminho em que a pessoa estava; o imago também, quando a própria API dele
// responde 401. Só vale caminho da mesma origem: a URL é montada com new URL(next, origem), que
// precisa dar a mesma origem, e `next` com caractere de controle ou "\" é recusado (o navegador
// tira tab e quebra de linha da URL, então "/\t/site.com" viraria "//site.com", e lê "/\site.com"
// como "//site.com"). O caminho devolvido também não pode começar com "//": a resolução tira os
// segmentos de ponto, e "/.//site.com" ou "/%2e%2e//site.com" dão a mesma origem com o pathname
// "//site.com", que o navegador leria como o host site.com. Assim a tela de entrar nunca
// redireciona para outro site

import { BASENAME, PATHS } from '../paths';

/** Para onde vai um `next` ausente, inválido ou que aponta para a própria tela de entrar. */
export const DEFAULT_NEXT = `${BASENAME}/`;

const LOGIN_PATH = `${BASENAME}${PATHS.login}`;

// C0 (inclui tab, CR e LF), DEL e C1
function hasControlCharacter(value) {
  for (const char of value) {
    const code = char.codePointAt(0);
    if (code < 0x20 || (code >= 0x7f && code <= 0x9f)) return true;
  }
  return false;
}

function decoded(pathname) {
  try {
    return decodeURIComponent(pathname);
  } catch {
    return pathname;
  }
}

/**
 * `pathname + search + hash` de `value` se ele for da mesma origem que `origin`; null se não for
 * texto, for vazio, tiver caractere de controle ou "\", apontar para outra origem (inclusive
 * "//site.com", "https://site.com" e "javascript:...", cuja origem é "null") ou se o pathname
 * resolvido começar com "//" ("/.//site.com", "/imago/..//site.com", "/%2e//site.com").
 */
export function sameOriginPath(value, origin = window.location.origin) {
  if (typeof value !== 'string' || value === '') return null;
  if (hasControlCharacter(value) || value.includes('\\')) return null;
  let url;
  try {
    url = new URL(value, origin);
  } catch {
    return null;
  }
  if (url.origin !== origin) return null;
  // O pathname serializado de uma URL http(s) sempre começa com "/" e nunca tem "\", espaço nem
  // caractere de controle (viram "/" ou são codificados). Lido de novo pelo navegador, ele só sai
  // da origem se começar com "//", que é um endereço sem esquema ("//site.com/caminho")
  if (url.pathname.startsWith('//')) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Se o caminho é a tela de entrar (o React Router não diferencia maiúsculas nem a barra final). */
function isLoginPath(pathname) {
  return decoded(pathname).replace(/\/+$/, '').toLowerCase() === LOGIN_PATH;
}

/** Destino depois do login: o `next` da URL validado, ou DEFAULT_NEXT. */
export function resolveNext(value, origin = window.location.origin) {
  const path = sameOriginPath(value, origin);
  if (path === null || isLoginPath(new URL(path, origin).pathname)) return DEFAULT_NEXT;
  return path;
}

/**
 * Rota do próprio imago (sem o basename, para o navigate do router) de um caminho que veio de
 * resolveNext; null se o caminho for de fora do imago (outra aplicação ou o site), que precisa de
 * navegação de página inteira.
 */
export function appRoute(path) {
  if (path === BASENAME) return '/';
  if (path.startsWith(`${BASENAME}/`)) return path.slice(BASENAME.length);
  if (path.startsWith(`${BASENAME}?`) || path.startsWith(`${BASENAME}#`)) {
    return `/${path.slice(BASENAME.length)}`;
  }
  return null;
}
