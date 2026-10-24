// Build de produção de verdade (vite build), em pastas temporárias:
// - os tokens de packages/tokens entram no CSS do ethos, e mudar um token muda esse CSS;
// - o index.html carrega o theme-init.js no <head>, sem defer, e não tem script nem estilo inline
//   (a CSP do ethos é script-src 'self' e style-src 'self').
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

const FRONTEND_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const TOKENS_FILE = resolve(FRONTEND_DIR, '../../../packages/tokens/tokens.css');
const TOKEN = '--surface-hover';
const SENTINEL = '#123456';

const workDir = mkdtempSync(join(tmpdir(), 'ethos-build-'));

async function buildInto(name, alias) {
  const outDir = join(workDir, name);
  await build({
    root: FRONTEND_DIR,
    configFile: resolve(FRONTEND_DIR, 'vite.config.js'),
    logLevel: 'silent',
    build: { outDir, emptyOutDir: true },
    ...(alias ? { resolve: { alias } } : {}),
  });
  return outDir;
}

function builtCss(outDir) {
  const assets = join(outDir, 'assets');
  return readdirSync(assets)
    .filter((file) => file.endsWith('.css'))
    .map((file) => readFileSync(join(assets, file), 'utf8'))
    .join('\n');
}

/** "#aabbcc" também pode sair minificado como "#abc". */
function hexForms(hex) {
  const value = hex.toLowerCase();
  const short = /^#(.)\1(.)\2(.)\3$/.exec(value);
  return short ? [value, `#${short[1]}${short[2]}${short[3]}`] : [value];
}

let original;
let changed;

beforeAll(async () => {
  original = await buildInto('original');

  // Cópia dos tokens com um valor trocado, no lugar do alias @tokens
  const tokens = readFileSync(TOKENS_FILE, 'utf8');
  const altered = tokens.replace(new RegExp(`(${TOKEN}:\\s*)#[0-9a-fA-F]+`), `$1${SENTINEL}`);
  expect(altered).not.toBe(tokens);
  const tokensDir = join(workDir, 'tokens');
  mkdirSync(tokensDir);
  writeFileSync(join(tokensDir, 'tokens.css'), altered);
  changed = await buildInto('changed', { '@tokens': tokensDir });
});

afterAll(() => {
  rmSync(workDir, { recursive: true, force: true });
});

describe('production build', () => {
  it('includes the shared tokens in the CSS', () => {
    const value = /--surface-hover:\s*(#[0-9a-fA-F]+)/.exec(readFileSync(TOKENS_FILE, 'utf8'))[1];
    const css = builtCss(original).toLowerCase();

    expect(hexForms(value).some((form) => css.includes(`${TOKEN}:${form}`))).toBe(true);
    expect(css).toContain('--habit-teal:');
    expect(css).not.toContain(SENTINEL);
  });

  it('changes the CSS when a token changes', () => {
    expect(builtCss(changed)).toContain(`${TOKEN}:${SENTINEL}`);
  });

  it('loads theme-init.js in the <head>, blocking, before the app', () => {
    const html = readFileSync(join(original, 'index.html'), 'utf8');
    const head = /<head>([\s\S]*)<\/head>/.exec(html)[1];
    const tag = /<script\b[^>]*\bsrc="\/ethos\/theme-init\.js"[^>]*><\/script>/.exec(head)?.[0];

    expect(tag).toBeDefined();
    expect(tag).not.toMatch(/\b(defer|async|type=)/);
    expect(head.indexOf(tag)).toBeLessThan(head.indexOf('type="module"'));
    expect(readFileSync(join(original, 'theme-init.js'), 'utf8')).toBe(
      readFileSync(resolve(FRONTEND_DIR, 'public/theme-init.js'), 'utf8'),
    );
  });

  it('has no inline script or style, so the CSP needs no hash', () => {
    const html = readFileSync(join(original, 'index.html'), 'utf8');
    const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];

    expect(scripts.length).toBeGreaterThanOrEqual(2);
    for (const [, attributes, body] of scripts) {
      expect(attributes).toMatch(/\bsrc="\/ethos\//);
      expect(body.trim()).toBe('');
    }
    expect(html).not.toMatch(/<style\b|\sstyle=/);
  });

  it('serves assets and translations under /ethos/', () => {
    const html = readFileSync(join(original, 'index.html'), 'utf8');

    for (const [, url] of html.matchAll(/\b(?:src|href)="([^"]+)"/g)) {
      expect(url.startsWith('/ethos/')).toBe(true);
    }
    for (const language of ['pt', 'en']) {
      expect(() => JSON.parse(readFileSync(join(original, `locales/${language}/translation.json`), 'utf8'))).not.toThrow();
    }
  });
});
