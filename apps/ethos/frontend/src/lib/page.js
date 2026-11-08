// Navegação da página inteira, para fora do app: as telas do imago (login, conta, termos) são outra
// aplicação na mesma origem, fora do basename do router. Num objeto, para os testes trocarem os
// métodos (vi.spyOn(page, 'assign')): o jsdom não navega. O setup dos testes já os troca por mocks.

export const page = {
  /** Vai para `url`, com uma entrada nova no histórico. */
  assign(url) {
    window.location.assign(url);
  },
  /** Vai para `url` no lugar da entrada atual do histórico (o voltar não cai de novo aqui). */
  replace(url) {
    window.location.replace(url);
  },
};
