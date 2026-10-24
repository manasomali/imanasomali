import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Pasta apps/ethos/frontend. Sem new URL(..., import.meta.url): o Vite troca esse padrão pela URL
// de um asset
export const FRONTEND_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

/** Conteúdo de um arquivo do repo, pelo caminho relativo a apps/ethos/frontend. */
export function readFrontendFile(path) {
  return readFileSync(resolve(FRONTEND_DIR, path), 'utf8');
}
