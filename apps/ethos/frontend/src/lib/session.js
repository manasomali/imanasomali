// O que fazer quando a API responde 401: ir para o login, guardando onde a pessoa estava. O
// destino vai no state do histórico (nunca na URL), então a tela de login só volta para um
// caminho do próprio app

import { BASENAME, PATHS } from '../paths';

// router.state.location traz o caminho com o basename ("/ethos/conta"); as rotas e o navigate
// usam sem ("/conta")
function withoutBasename(pathname) {
  if (pathname === BASENAME) return '/';
  return pathname.startsWith(`${BASENAME}/`) ? pathname.slice(BASENAME.length) : pathname;
}

/** `router` é o data router do app (createApp em src/bootstrap.js, basename /ethos). */
export function redirectToLogin(router) {
  const { search, hash } = router.state.location;
  const pathname = withoutBasename(router.state.location.pathname);
  if (pathname === PATHS.login) return;
  router.navigate(PATHS.login, { replace: true, state: { from: `${pathname}${search}${hash}` } });
}

/** Caminho para onde voltar depois do login (state.from), ou a tela inicial. */
export function returnPath(location) {
  const from = location?.state?.from;
  // Só caminho interno: começa com uma barra só (o navegador lê "/\" como "//"), e nunca a
  // própria tela de login
  if (
    typeof from !== 'string'
    || !from.startsWith('/')
    || from.startsWith('//')
    || from.includes('\\')
  ) {
    return PATHS.home;
  }
  if (from === PATHS.login || from.startsWith(`${PATHS.login}?`) || from.startsWith(`${PATHS.login}#`)) {
    return PATHS.home;
  }
  return from;
}
