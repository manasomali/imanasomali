import { describe, expect, it } from 'vitest';
import { readFrontendFile } from '../../test/files';

// O jsdom não tem layout: o tamanho do dia nas duas visões (grade e colunas) é conferido na regra
// do CSS. As duas tiram o tamanho de --day-size, definida uma vez para os dois contêineres, e
// ninguém redefine o tamanho do dia numa visão só
const CSS = readFrontendFile('src/components/Calendar/styles.module.css');

// Propriedades que mudam o tamanho ou a forma do dia
const SIZE_PROPERTIES = [
  'width',
  'height',
  'min-width',
  'min-height',
  'max-width',
  'max-height',
  'aspect-ratio',
  'padding',
  'flex-direction',
  'box-sizing',
];

/** As regras do CSS (inclusive as de dentro de @container): `{selectors, declarations}`. */
function cssRules(text) {
  const source = text.replace(/\/\*[\s\S]*?\*\//g, '');
  return [...source.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selector, body]) => ({
    selectors: selector.split(',').map((part) => part.trim().replace(/\s+/g, ' ')),
    declarations: Object.fromEntries(
      body
        .split(';')
        .map((declaration) => declaration.trim())
        .filter(Boolean)
        .map((declaration) => {
          const colon = declaration.indexOf(':');
          return [declaration.slice(0, colon).trim(), declaration.slice(colon + 1).trim().replace(/\s+/g, ' ')];
        }),
    ),
  }));
}

const rules = cssRules(CSS);

/** As declarações da regra com exatamente esse seletor. */
function declarationsOf(selector) {
  const rule = rules.find((candidate) => candidate.selectors.length === 1 && candidate.selectors[0] === selector);
  expect(rule, selector).toBeDefined();
  return rule.declarations;
}

describe('calendar day size', () => {
  it('reads the rules of the stylesheet', () => {
    expect(rules.length).toBeGreaterThan(20);
  });

  it('defines the day size once, for the grid and the columns together', () => {
    const defining = rules.filter((rule) => '--day-size' in rule.declarations);
    expect(defining).toHaveLength(1);
    expect(defining[0].selectors).toEqual(['.months', '.columns']);
  });

  it('gives the same inputs of the day size to both views', () => {
    // O que entra no --day-size (vãos, largura do mês, meses por linha) muda junto nas duas visões
    const inputs = ['--day-gap', '--month-gap', '--months-per-row', '--month-width'];
    const defining = rules.filter((rule) => inputs.some((name) => name in rule.declarations));
    expect(defining.length).toBeGreaterThanOrEqual(5);
    defining.forEach(({ selectors }) => {
      const grid = selectors.filter((selector) => selector.startsWith('.months')).sort();
      const columns = selectors
        .filter((selector) => selector.startsWith('.columns'))
        .map((selector) => selector.replace('.columns', '.months'))
        .sort();
      expect(selectors).toHaveLength(grid.length + columns.length);
      expect(columns).toEqual(grid);
    });
  });

  it('sizes the grid tracks, the columns and the day with --day-size', () => {
    expect(declarationsOf('.day').width).toBe('var(--day-size)');
    expect(declarationsOf('.day')['aspect-ratio']).toBe('1');
    expect(declarationsOf('.columns')['grid-auto-columns']).toBe('var(--day-size)');
    const grid = rules.find((rule) => rule.selectors.includes('.grid'));
    expect(grid.declarations['grid-template-columns']).toBe('repeat(7, var(--day-size))');
    expect(grid.declarations.gap).toBe('var(--day-gap)');
    expect(declarationsOf('.columnDays').gap).toBe('var(--day-gap)');
    // Entre as colunas, o mesmo vão que entre os dias da grade
    expect(declarationsOf('.columns').gap).toBe('var(--day-gap)');
  });

  it('does not resize the day in one view only', () => {
    // Qualquer regra que mire o próprio botão do dia (".day", ".columns .day[...]" etc.), fora a
    // base, não mexe no tamanho nem na forma
    const dayRules = rules.filter((rule) =>
      rule.selectors.some((selector) => /\.day(?:\[[^\]]*\]|:[\w-]+(?:\([^)]*\))?)*$/.test(selector)),
    );
    const overrides = dayRules
      .filter((rule) => !(rule.selectors.length === 1 && rule.selectors[0] === '.day'))
      .flatMap((rule) =>
        Object.keys(rule.declarations)
          .filter((property) => SIZE_PROPERTIES.includes(property))
          .map((property) => `${rule.selectors.join(', ')} { ${property} }`),
      );
    expect(dayRules.length).toBeGreaterThan(5);
    expect(overrides).toEqual([]);
  });

  it('has no weekday in the columns', () => {
    expect(CSS).not.toMatch(/\.weekday\b/);
  });
});
