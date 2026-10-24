// Aplica o tema salvo (localStorage.theme, a mesma chave do site) antes da primeira pintura, para
// não piscar o tema errado. Carregado no <head> do index.html sem defer nem async. É um arquivo,
// e não script inline, porque a CSP do ethos só permite script-src 'self'. Sem escolha salva, o
// CSS segue prefers-color-scheme. A mesma regra vale em src/lib/theme.js
(function () {
  try {
    const theme = window.localStorage.getItem('theme');
    if (theme === 'light' || theme === 'dark') {
      document.documentElement.setAttribute('data-theme', theme);
    }
  } catch {
    // Armazenamento bloqueado: segue o sistema
  }
})();
