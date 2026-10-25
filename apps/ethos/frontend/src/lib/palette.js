// Cores dos hábitos. A API guarda o nome de uma das 12 cores da paleta (HabitColor em
// app/models.py) ou uma cor própria "#rrggbb" em minúsculas, a mesma nos dois temas (ETH-49). Os
// valores da paleta em cada tema ficam em src/styles/palette.css como --habit-<nome>.
//
// Para pintar um elemento com a cor de um hábito, use SEMPRE `useHabitColor(color)` (ref) ou o
// componente `HabitSwatch`, e no CSS `var(--habit-color, var(--muted))`. Por baixo,
// `applyHabitColor` marca o elemento com data-habit-color (o nome da paleta, ou "custom") e, na
// cor própria, define --habit-color pelo CSSOM (`element.style.setProperty`). A CSP do ethos
// (`style-src 'self'`) bloqueia o atributo style escrito no HTML, mas não o CSSOM. Nada de
// style inline no JSX.

import { relativeLuminance } from './color';

export const HABIT_COLORS = Object.freeze([
  'red',
  'orange',
  'amber',
  'yellow',
  'lime',
  'green',
  'teal',
  'cyan',
  'blue',
  'indigo',
  'violet',
  'pink',
]);

/** Valor de data-habit-color de um elemento com cor própria. */
export const CUSTOM_COLOR = 'custom';

// "#" e 6 dígitos hexadecimais em minúsculas (o que a API salva e devolve)
const CUSTOM_COLOR_RE = /^#[0-9a-f]{6}$/;

export function isHabitColor(name) {
  return HABIT_COLORS.includes(name);
}

/** Se o valor é uma cor própria ("#rrggbb", minúsculas). */
export function isCustomColor(value) {
  return typeof value === 'string' && CUSTOM_COLOR_RE.test(value);
}

/** Se a API aceita o valor como cor: um nome da paleta ou uma cor própria. */
export function isValidColor(value) {
  return isHabitColor(value) || isCustomColor(value);
}

// Luminâncias do texto claro e do escuro sobre uma cor própria: --habit-text-light (branco) e
// --habit-text-dark (preto) em src/styles/palette.css (o teste da paleta confere)
const LIGHT_TEXT_LUMINANCE = 1;
const DARK_TEXT_LUMINANCE = 0;

/**
 * Texto que fica legível sobre a cor própria `hex`: 'light' ou 'dark', o de maior contraste.
 * Com branco e preto, o maior dos dois é sempre pelo menos 4,58:1 (texto pequeno, WCAG AA).
 */
export function textTone(hex) {
  const luminance = relativeLuminance(hex);
  const light = (LIGHT_TEXT_LUMINANCE + 0.05) / (luminance + 0.05);
  const dark = (luminance + 0.05) / (DARK_TEXT_LUMINANCE + 0.05);
  return light >= dark ? 'light' : 'dark';
}

/**
 * Pinta `element` com a cor de um hábito (nome da paleta ou "#rrggbb"). Sem cor válida, tira a
 * marcação: o CSS cai no `var(--muted)`. O texto sobre a cor (o número do dia marcado) usa
 * `var(--habit-color-text)`: --bg na paleta, e texto claro ou escuro na cor própria
 * (data-habit-text, por `textTone`).
 */
export function applyHabitColor(element, color) {
  if (isCustomColor(color)) {
    element.dataset.habitColor = CUSTOM_COLOR;
    element.dataset.habitText = textTone(color);
    element.style.setProperty('--habit-color', color);
    return;
  }
  if (isHabitColor(color)) element.dataset.habitColor = color;
  else delete element.dataset.habitColor;
  delete element.dataset.habitText;
  element.style.removeProperty('--habit-color');
}

/**
 * Valor de --habit-<nome> no tema atual da página ("#rrggbb"), ou null (CSS não carregado, nome
 * fora da paleta). Serve de ponto de partida do seletor de cor própria.
 */
export function readPaletteHex(name, element = globalThis.document?.documentElement) {
  if (!isHabitColor(name) || !element) return null;
  const value = globalThis.getComputedStyle(element).getPropertyValue(`--habit-${name}`).trim().toLowerCase();
  return isCustomColor(value) ? value : null;
}
