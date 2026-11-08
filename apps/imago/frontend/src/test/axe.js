import { configureAxe } from 'vitest-axe';

// O jsdom não calcula layout nem tem canvas, então o color-contrast do axe não
// consegue avaliar nada aqui (e tenta usar canvas). Contraste precisa de teste
// próprio sobre as cores, fora dos testes de tela
export const axe = configureAxe({
  rules: { 'color-contrast': { enabled: false } },
});
