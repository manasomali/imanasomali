// Rotas do app, relativas ao basename (/ethos). Use estas constantes em vez de escrever o caminho

export const BASENAME = '/ethos';

export const PATHS = Object.freeze({
  home: '/',
  login: '/entrar',
  account: '/conta',
  admin: '/admin',
  adminUser: '/admin/contas/:userId',
  adminBanners: '/admin/banners',
});

/** Tela do conteúdo dos hábitos de uma conta, no painel de admin. */
export function adminUserPath(userId) {
  return PATHS.adminUser.replace(':userId', encodeURIComponent(String(userId)));
}
