// O que fazer quando a API responde 401: ir para o login do imago (a conta única do
// manasomali.com), com o caminho atual em `next`, para voltar para cá depois de entrar. O imago só
// aceita um `next` da mesma origem (imago-plan.md, "fluxo")

import { BASENAME, IMAGO_PATHS } from '../paths';
import { page } from './page';

/**
 * O endereço do login do imago que volta para `location` ({pathname, search, hash} do router, com
 * o basename, ex.: "/ethos/relatorio"). Caminho fora do basename (não acontece no app) volta para
 * a tela inicial do ethos.
 */
export function loginUrl(location) {
  const { pathname, search = '', hash = '' } = location;
  const inside = pathname === BASENAME || pathname.startsWith(`${BASENAME}/`);
  const next = inside ? `${pathname}${search}${hash}` : `${BASENAME}/`;
  return `${IMAGO_PATHS.login}?${new URLSearchParams({ next })}`;
}

/**
 * Vai para o login do imago guardando onde a pessoa estava. `router` é o data router do app
 * (createApp em src/bootstrap.js, basename /ethos). Sai do app: o login é outra aplicação.
 */
export function redirectToLogin(router) {
  page.assign(loginUrl(router.state.location));
}
