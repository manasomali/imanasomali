import { afterAll, afterEach, beforeAll, beforeEach, expect } from 'vitest';
import { cleanup } from '@testing-library/react';
import * as axeMatchers from 'vitest-axe/matchers';
import { createTestI18n } from './i18n';
import { server } from './server';

// expect(await axe(container)).toHaveNoViolations() em todo teste de tela
expect.extend(axeMatchers);

// O jsdom não implementa scrollTo (usado pelo ScrollRestoration do React Router)
window.scrollTo = () => {};

// API falsa (MSW): request sem handler no teste falha, em vez de sair para a rede
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterAll(() => server.close());

// Cada teste começa em inglês (idioma do navegador no jsdom), sem nada salvo e sem tema escolhido
beforeEach(() => {
  createTestI18n();
});

// Sem globals do vitest, o Testing Library não desmonta sozinho entre os testes
afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});
