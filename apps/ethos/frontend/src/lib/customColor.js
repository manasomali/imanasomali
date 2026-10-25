// Contraste da cor própria de um hábito (ETH-49) contra os fundos dos dois temas. A cor própria é
// a mesma nos temas claro e escuro, então o formulário confere as duas: abaixo de
// MIN_COLOR_CONTRAST, a cor é aceita, mas a tela avisa. A paleta já garante esse mínimo
// (src/styles/palette.test.js).
//
// Os fundos vêm do próprio packages/tokens/tokens.css, importado como texto (?raw) e lido em
// runtime: a página só enxerga, pelo getComputedStyle, os valores do tema atual.

import tokensCss from '@tokens/tokens.css?raw';
import { contrastRatio } from './color';
import { DARK, LIGHT, readCustomProperties } from './css';

/** Contraste mínimo de uma cor de hábito contra o fundo (WCAG 2.1, elementos gráficos). */
export const MIN_COLOR_CONTRAST = 3;

export const THEMES = Object.freeze(['light', 'dark']);

// Fundos em que a cor do hábito aparece: a página (--bg) e os cartões e dias do calendário (--surface)
const BACKGROUNDS = Object.freeze(['bg', 'surface']);

/** Cores de cada tema lidas de tokens.css: {light: {bg, surface, fg}, dark: {...}}. */
export function themeColors(css = tokensCss) {
  const blocks = readCustomProperties(css);
  const read = (selector) => {
    const props = blocks.get(selector) ?? {};
    const value = (name) => {
      if (!props[name]) throw new Error(`token ausente: ${name} em ${selector}`);
      return props[name];
    };
    return { bg: value('--bg'), surface: value('--surface'), fg: value('--fg') };
  };
  return { light: read(LIGHT), dark: read(DARK) };
}

export const THEME_COLORS = Object.freeze(themeColors());

/**
 * Temas em que `hex` tem contraste baixo: [{theme, ratio}], com `ratio` o menor contraste contra
 * os fundos do tema (--bg e --surface). Vazio quando a cor passa nos dois.
 */
export function lowContrastThemes(hex, themes = THEME_COLORS) {
  return THEMES.flatMap((theme) => {
    const ratio = Math.min(
      ...BACKGROUNDS.map((background) => contrastRatio(hex, themes[theme][background])),
    );
    return ratio < MIN_COLOR_CONTRAST ? [{ theme, ratio }] : [];
  });
}
