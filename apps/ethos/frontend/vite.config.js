import { fileURLToPath } from 'node:url';
import { defineConfig, searchForWorkspaceRoot } from 'vite';
import react from '@vitejs/plugin-react';
import browserslist from 'browserslist';
import { buildTargets } from './build-targets.js';

const frontendRoot = fileURLToPath(new URL('.', import.meta.url));
const packagesDir = fileURLToPath(new URL('../../../packages', import.meta.url));

// https://vite.dev/config/
export default defineConfig({
  // Servido em manasomali.com/ethos/
  base: '/ethos/',
  plugins: [react()],
  resolve: {
    alias: {
      // Tokens de design do monorepo: src/index.css faz @import '@tokens/tokens.css'. O teste de
      // build (src/build.test.js) troca este alias por uma cópia alterada do arquivo
      '@tokens': `${packagesDir}/tokens`,
    },
  },
  build: {
    // Navegadores do plano, lidos do "browserslist" do package.json (o Vite não lê sozinho, e o
    // padrão dele começa no Safari/iOS 16.4)
    target: buildTargets(browserslist(undefined, { path: frontendRoot })),
  },
  server: {
    // O site usa a 5173
    port: 5174,
    strictPort: true,
    fs: {
      // Definir allow substitui o padrão do Vite: mantém a raiz do front e libera packages/
      allow: [searchForWorkspaceRoot(frontendRoot), packagesDir],
    },
    proxy: {
      // Como o nginx em produção: tira o prefixo /api/ethos antes de repassar
      // para o backend local (uvicorn --root-path /api/ethos)
      '/api/ethos/': {
        target: 'http://127.0.0.1:8000',
        rewrite: (path) => path.replace(/^\/api\/ethos/, ''),
      },
    },
  },
  test: {
    projects: [
      // Código do app, no jsdom, com MSW, i18n e os matchers do axe (src/test/setup.js)
      {
        extends: true,
        test: {
          name: 'app',
          environment: 'jsdom',
          include: ['src/**/*.test.{js,jsx}'],
          setupFiles: ['./src/test/setup.js'],
        },
      },
      // Build de produção e config, no Node
      {
        extends: true,
        test: {
          name: 'build',
          environment: 'node',
          include: ['tests/**/*.test.js'],
          testTimeout: 120_000,
        },
      },
    ],
    coverage: {
      provider: 'v8',
      // Política de testes: 80% em src/lib/ (o CI roda npm test, que liga a cobertura)
      include: ['src/lib/**'],
      exclude: ['src/lib/**/*.test.*'],
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
    },
  },
});
