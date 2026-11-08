import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import browserslist from 'browserslist';
import { describe, expect, it } from 'vitest';
import { buildTargets } from '../build-targets.js';

const FRONTEND_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(resolve(FRONTEND_DIR, 'package.json'), 'utf8'));

describe('browsers', () => {
  it('follows the plan in package.json', () => {
    expect(pkg.browserslist).toEqual([
      'last 2 Chrome versions',
      'last 2 Edge versions',
      'last 2 Firefox versions',
      'last 2 Safari versions',
      'iOS >= 16',
    ]);
  });

  it('builds for iOS 16, below the Vite default (16.4)', () => {
    const targets = buildTargets(browserslist(undefined, { path: FRONTEND_DIR }));

    expect(targets).toContain('ios16');
    expect(targets.map((target) => target.replace(/[\d.]+$/, '')).sort()).toEqual([
      'chrome',
      'edge',
      'firefox',
      'ios',
      'safari',
    ]);
  });
});

describe('buildTargets', () => {
  it('keeps the lowest version of each browser', () => {
    expect(
      buildTargets(['chrome 141', 'chrome 140', 'ios_saf 16.4-16.7', 'ios_saf 16.0', 'safari 18.10', 'safari 18.9']),
    ).toEqual(['chrome140', 'ios16', 'safari18.9']);
  });

  it('skips browsers and versions it does not know', () => {
    expect(buildTargets(['and_chr 141', 'op_mini all', 'firefox TP', 'firefox 140', 'edge'])).toEqual([
      'firefox140',
    ]);
  });

  it('fails without any known browser', () => {
    expect(() => buildTargets(['op_mini all'])).toThrow();
  });
});
