// `vite preview` do E2E: serve o build de produção (dist/, gerado com o vite.config.js principal)
// como o nginx serve em produção. O proxy repassa /api/ethos/* para o backend do E2E tirando o
// prefixo, e as páginas saem com os headers de segurança do infra/apps/ethos/nginx.conf, lidos
// do próprio arquivo: um script ou estilo inline que a CSP bloqueie em produção quebra o E2E
import { readFileSync } from 'node:fs';
import { mergeConfig } from 'vite';
import baseConfig from '../vite.config.js';
import { API_URL, FRONT_PORT, HOST } from './env.js';

const NGINX_CONF = new URL('../../../../infra/apps/ethos/nginx.conf', import.meta.url);
const SECURITY_HEADERS = ['Content-Security-Policy', 'X-Content-Type-Options', 'Referrer-Policy'];

/** Os headers de segurança do `location /ethos/` do nginx.conf. */
export function nginxHeaders(conf) {
  const block = conf.match(/location \/ethos\/ \{([^}]*)\}/);
  if (!block) throw new Error('nginx.conf sem o location /ethos/');
  const headers = {};
  for (const name of SECURITY_HEADERS) {
    const line = block[1].match(new RegExp(`add_header ${name} "([^"]+)" always;`));
    if (!line) throw new Error(`nginx.conf sem o header ${name} no location /ethos/`);
    headers[name] = line[1];
  }
  return headers;
}

export default mergeConfig(baseConfig, {
  preview: {
    host: HOST,
    port: FRONT_PORT,
    strictPort: true,
    headers: nginxHeaders(readFileSync(NGINX_CONF, 'utf8')),
    proxy: {
      '/api/ethos/': {
        target: API_URL,
        rewrite: (path) => path.replace(/^\/api\/ethos/, ''),
      },
    },
  },
});
