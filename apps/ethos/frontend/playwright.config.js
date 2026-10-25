// E2E do ethos (Playwright, só Chromium): `npm run e2e`. Como funciona e como rodar: seção
// "E2E" do apps/ethos/README.md. Os testes ficam em e2e/ e não entram no `npm test` (vitest)
import { defineConfig, devices } from '@playwright/test';
import { API_PORT, API_URL, APP_URL, BACKEND_DIR, FRONT_ORIGIN, MAIL_PORT, STACK_DIR } from './e2e/env.js';

const CI = Boolean(process.env.CI);

// Celular e desktop, tema claro e escuro (prefers-color-scheme; sem escolha salva, o ethos segue
// o sistema). Fuso e idioma fixos: o login manda os do navegador para a conta nova
const VIEWPORTS = {
  desktop: devices['Desktop Chrome'],
  mobile: devices['Pixel 7'],
};
const projects = Object.entries(VIEWPORTS).flatMap(([viewport, device]) =>
  ['light', 'dark'].map((colorScheme) => ({
    name: `${viewport}-${colorScheme}`,
    use: { ...device, colorScheme },
  })),
);

export default defineConfig({
  testDir: './e2e',
  // Cada teste cria as próprias contas (emails únicos), então rodam em paralelo
  fullyParallel: true,
  forbidOnly: CI,
  retries: 0,
  workers: CI ? 4 : 2,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: FRONT_ORIGIN,
    locale: 'pt-BR',
    timezoneId: 'America/Sao_Paulo',
    // Sem transições (o CSS do ethos as desliga com prefers-reduced-motion): o axe mede o contraste
    // das cores finais, e não de uma cor no meio da animação de hover ou de tema
    reducedMotion: 'reduce',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects,
  webServer: [
    {
      // API, banco migrado e SMTP falso com a caixa de entrada (backend/tests/e2e_stack.py)
      command: `uv run --frozen python -m tests.e2e_stack --api-port ${API_PORT} --mail-port ${MAIL_PORT} --app-url ${APP_URL} --data-dir "${STACK_DIR}"`,
      cwd: BACKEND_DIR,
      url: `${API_URL}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
    },
    {
      // Build de produção (vite.config.js) servido pelo vite preview com o proxy da API
      command: 'npx vite build && npx vite preview --config e2e/vite.config.js',
      url: `${APP_URL}/`,
      reuseExistingServer: false,
      timeout: 180_000,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
    },
  ],
});
