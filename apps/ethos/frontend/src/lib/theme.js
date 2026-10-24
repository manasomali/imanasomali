// Tema claro/escuro com a chave do site (localStorage.theme), aplicado como data-theme no <html>.
// Sem escolha salva, o CSS segue prefers-color-scheme. Antes da primeira pintura quem aplica é
// public/theme-init.js; depois, o useTheme

import { readItem, writeItem } from './storage';

export const THEME_KEY = 'theme';
export const THEMES = Object.freeze(['light', 'dark']);

const DARK_QUERY = '(prefers-color-scheme: dark)';

/** Tema escolhido pela pessoa ('light' ou 'dark'), ou null se ela não escolheu. */
export function readStoredTheme() {
  const value = readItem(THEME_KEY);
  return THEMES.includes(value) ? value : null;
}

export function systemTheme() {
  if (typeof window.matchMedia !== 'function') return 'light';
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light';
}

/** Escuta a troca do tema do sistema; devolve a função que para de escutar. */
export function watchSystemTheme(callback) {
  if (typeof window.matchMedia !== 'function') return () => {};
  const media = window.matchMedia(DARK_QUERY);
  const onChange = () => callback(media.matches ? 'dark' : 'light');
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}

/** Aplica e salva a escolha. Sem armazenamento, vale até o reload. */
export function chooseTheme(theme) {
  if (!THEMES.includes(theme)) throw new RangeError(`tema inválido: ${theme}`);
  document.documentElement.dataset.theme = theme;
  writeItem(THEME_KEY, theme);
}
