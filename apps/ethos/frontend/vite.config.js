import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vite.dev/config/
export default defineConfig({
  // Servido em manasomali.com/ethos/
  base: '/ethos/',
  plugins: [react()],
  server: {
    // O site usa a 5173
    port: 5174,
    strictPort: true,
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
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
  },
});
