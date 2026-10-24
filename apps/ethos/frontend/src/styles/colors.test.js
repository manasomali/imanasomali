import { readdirSync } from 'node:fs';
import { relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { FRONTEND_DIR, readFrontendFile } from '../test/files';

// Sem cores fixas: fora da paleta (src/styles/palette.css), cor só por token. Vale para o CSS e
// para o JS (estilo inline também ficaria de fora da CSP)
const PALETTE = 'src/styles/palette.css';
const HEX = /#[0-9a-f]{3,8}\b/i;
const COLOR_FUNCTION = /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/i;
const NAMED = /:\s*[^;{}]*\b(?:white|black|red|green|blue|yellow|orange|purple|gray|grey|pink)\b/i;

function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(dir, entry.name);
    if (entry.isDirectory()) return entry.name === 'test' ? [] : sourceFiles(path);
    return /\.(css|js|jsx)$/.test(entry.name) && !/\.test\./.test(entry.name) ? [path] : [];
  });
}

const files = [
  ...sourceFiles(resolve(FRONTEND_DIR, 'src')),
  resolve(FRONTEND_DIR, 'public/theme-init.js'),
  resolve(FRONTEND_DIR, 'index.html'),
]
  .map((path) => relative(FRONTEND_DIR, path).replaceAll('\\', '/'))
  .filter((path) => path !== PALETTE);

describe('no hard-coded colors', () => {
  it('finds the source files', () => {
    expect(files).toContain('src/index.css');
    expect(files).toContain('src/components/Menu/styles.module.css');
  });

  it.each(files)('%s uses only tokens and the palette', (path) => {
    const lines = readFrontendFile(path)
      .split('\n')
      .filter((line) => HEX.test(line) || COLOR_FUNCTION.test(line) || (path.endsWith('.css') && NAMED.test(line)));

    expect(lines).toEqual([]);
  });
});
