// O que fazer quando a API do imago responde 401: ir para a tela de entrar com o caminho atual no
// `next`, do mesmo jeito que as aplicações fazem (`/imago/entrar?next=<caminho>`)

import { BASENAME, PATHS } from '../paths';

/**
 * Código só do front (traduzido em errors.<codigo>): o código de login foi aceito, mas o GET /me
 * seguinte continua sem sessão, porque o navegador não guardou o cookie (ex.: cookies bloqueados).
 */
export const SESSION_NOT_SAVED = 'session_not_saved';

/**
 * Caminho (relativo ao basename) da tela de entrar com o destino `next`, um caminho completo da
 * origem (ex.: "/imago/admin"). As barras ficam legíveis ("?next=/imago/"); o resto é codificado.
 */
export function loginPath(next) {
  if (!next) return PATHS.login;
  return `${PATHS.login}?next=${encodeURIComponent(next).replaceAll('%2F', '/')}`;
}

// router.state.location pode trazer o caminho com ou sem o basename; as rotas usam sem
function withoutBasename(pathname) {
  if (pathname === BASENAME) return '/';
  return pathname.startsWith(`${BASENAME}/`) ? pathname.slice(BASENAME.length) : pathname;
}

/** `router` é o data router do app (createApp em src/bootstrap.js, basename /imago). */
export function redirectToLogin(router) {
  const { search, hash } = router.state.location;
  const route = withoutBasename(router.state.location.pathname);
  if (route.replace(/\/+$/, '').toLowerCase() === PATHS.login) return;
  router.navigate(loginPath(`${BASENAME}${route}${search}${hash}`), { replace: true });
}
