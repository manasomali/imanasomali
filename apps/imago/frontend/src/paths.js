// Rotas do imago, relativas ao basename (/imago). Use estas constantes em vez de escrever o caminho

export const BASENAME = '/imago';

export const PATHS = Object.freeze({
  // Tela de conta, a inicial
  account: '/',
  // Entrar (email → código) e aceite dos termos; recebe o destino em ?next=
  login: '/entrar',
  terms: '/termos',
  privacy: '/privacidade',
  // Admin de contas, só para is_admin
  admin: '/admin',
});
