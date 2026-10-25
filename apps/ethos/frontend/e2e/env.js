// Endereços do stack local do E2E, lidos pelo playwright.config.js, pelo e2e/vite.config.js e
// pelos testes. As portas podem ser trocadas por variáveis de ambiente (ex.: outra cópia do
// repositório rodando o E2E ao mesmo tempo). Sempre 127.0.0.1: o Chromium trata o endereço como
// origem segura e guarda o cookie __Host-ethos_session (Secure) também em http
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

export const HOST = '127.0.0.1';
export const FRONT_PORT = port('E2E_FRONT_PORT', 47830);
export const API_PORT = port('E2E_API_PORT', 47831);
export const MAIL_PORT = port('E2E_MAIL_PORT', 47832);

// A origem do front é a do APP_URL do backend (o backend confere o Origin de toda escrita)
export const FRONT_ORIGIN = `http://${HOST}:${FRONT_PORT}`;
export const APP_URL = `${FRONT_ORIGIN}/ethos`;
export const API_URL = `http://${HOST}:${API_PORT}`;
export const MAIL_URL = `http://${HOST}:${MAIL_PORT}`;

export const FRONTEND_DIR = fileURLToPath(new URL('..', import.meta.url));
export const BACKEND_DIR = fileURLToPath(new URL('../../backend', import.meta.url));
// Banco, CA de teste do SMTP: apagada e recriada a cada execução (fora do git)
export const STACK_DIR = fileURLToPath(new URL('./.stack', import.meta.url));
