// Navegação de página inteira: o `next` de outra aplicação (ou do site) e a recarga da página. Num
// objeto, para os testes trocarem (o jsdom não navega). `replace` tira a tela de entrar do
// histórico: o "voltar" do navegador não cai nela de novo

export const pageLocation = {
  replace(url) {
    window.location.replace(url);
  },
  reload() {
    window.location.reload();
  },
};
