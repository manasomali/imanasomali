// E2E do ethos (Playwright, só Chromium): `npm run e2e`. Como funciona e como rodar: seção "E2E"
// do apps/ethos/README.md. Os testes ficam em e2e/ e não entram no `npm test` (vitest)
import { defineConfig, devices } from '@playwright/test';
import {
  BACKEND_DIR,
  FRONTEND_DIR,
  HOST_NETWORK,
  IMAGO_BACKEND_DIR,
  IMAGO_FRONTEND_DIR,
  MAIL_PORT,
  MAIL_URL,
  ORIGIN,
  STACK_DIR,
  importedAdminEmail,
} from './e2e/env.js';

const CI = Boolean(process.env.CI);

// Celular e desktop, tema claro e escuro (prefers-color-scheme; sem escolha salva, o imago e o
// ethos seguem o sistema). Fuso e idioma fixos: o login manda os do navegador para a conta nova
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

// Caminhos entre aspas no comando do shell (sh no Linux, cmd no Windows). Aspas, $ e crase dentro
// deles quebrariam (ou expandiriam) o comando
function quote(value) {
  if (/["$`]/.test(value)) throw new Error(`caminho com aspas, $ ou crase não roda no E2E: ${value}`);
  return `"${value}"`;
}

// O stack (backend/tests/e2e_stack.py): SMTP falso, imago, ethos e o nginx de dev em container
const stack = [
  `uv run --frozen --directory ${quote(BACKEND_DIR)} python -m tests.e2e_stack`,
  `--mail-port ${MAIL_PORT}`,
  `--data-dir ${quote(STACK_DIR)}`,
  ...(HOST_NETWORK ? ['--host-network'] : []),
  ...projects.map((project) => `--imported-admin ${importedAdminEmail(project.name)}`),
].join(' ');

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
    baseURL: ORIGIN,
    locale: 'pt-BR',
    timezoneId: 'America/Sao_Paulo',
    // Sem transições (o CSS do imago e do ethos as desliga com prefers-reduced-motion): o axe mede
    // o contraste das cores finais, e não de uma cor no meio da animação de hover ou de tema
    reducedMotion: 'reduce',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects,
  webServer: [
    {
      // O build de produção dos dois fronts (o mesmo do deploy), as dependências do backend do
      // imago e o stack. Ele sobe tudo e só então abre a caixa de entrada, a URL esperada aqui;
      // o SIGTERM do fim (também numa falha) derruba tudo, o container inclusive
      command: [
        'npm run build',
        `npm --prefix ${quote(IMAGO_FRONTEND_DIR)} run build`,
        `uv sync --frozen --directory ${quote(IMAGO_BACKEND_DIR)}`,
        stack,
      ].join(' && '),
      cwd: FRONTEND_DIR,
      url: `${MAIL_URL}/health`,
      reuseExistingServer: false,
      timeout: 300_000,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 20_000 },
    },
  ],
});
