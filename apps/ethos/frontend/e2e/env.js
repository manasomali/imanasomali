// Endereços e pastas do stack local do E2E (backend/tests/e2e_stack.py), lidos pelo
// playwright.config.js e pelos testes. A origem é a do nginx de dev (apps/imago/dev/nginx.sh, o
// mesmo NGINX_PORT do e2e_stack.py): o imago e o ethos numa origem só, como em produção. Sempre
// 127.0.0.1: o Chromium trata o endereço como origem segura e guarda o cookie
// __Host-imago_session (Secure) também em http
import { fileURLToPath } from 'node:url';

function port(name, fallback) {
  const value = process.env[name];
  if (value === undefined || value === '') return fallback;
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1 || number > 65535) {
    throw new Error(`${name} precisa ser uma porta (1 a 65535)`);
  }
  return number;
}

function flag(name, fallback) {
  const value = process.env[name];
  if (value === undefined || value === '') return fallback;
  if (value !== '0' && value !== '1') throw new Error(`${name} precisa ser 0 ou 1`);
  return value === '1';
}

export const HOST = '127.0.0.1';
export const ORIGIN = `http://${HOST}:8080`;
// Caixa de entrada do SMTP falso (GET /emails?to=<endereço>)
export const MAIL_PORT = port('E2E_MAIL_PORT', 47832);
export const MAIL_URL = `http://${HOST}:${MAIL_PORT}`;

// O container do nginx na rede da máquina: no Linux (o CI), onde o host.docker.internal não
// alcança os backends em 127.0.0.1. Fora dele, o host.docker.internal do Docker Desktop
export const HOST_NETWORK = flag('E2E_HOST_NETWORK', process.platform === 'linux');

export const FRONTEND_DIR = fileURLToPath(new URL('..', import.meta.url));
export const BACKEND_DIR = fileURLToPath(new URL('../../backend', import.meta.url));
export const IMAGO_FRONTEND_DIR = fileURLToPath(new URL('../../../imago/frontend', import.meta.url));
export const IMAGO_BACKEND_DIR = fileURLToPath(new URL('../../../imago/backend', import.meta.url));
// Bancos, CA de teste do SMTP e config do nginx: apagada e recriada a cada execução (fora do git)
export const STACK_DIR = fileURLToPath(new URL('./.stack', import.meta.url));

/**
 * Conta admin importada do ethos, sem os termos aceitos (o `--imported-admin` do stack), uma por
 * projeto: o limite de códigos por email não se cruza entre os projetos.
 */
export function importedAdminEmail(projectName) {
  return `e2e-imported-${projectName}@example.com`;
}
