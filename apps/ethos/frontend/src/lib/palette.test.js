import { afterEach, describe, expect, it } from 'vitest';
import {
  CUSTOM_COLOR,
  applyHabitColor,
  isCustomColor,
  isHabitColor,
  isValidColor,
  readPaletteHex,
  textTone,
} from './palette';

// A paleta contra o backend e o contraste dos valores ficam em src/styles/palette.test.js

afterEach(() => {
  document.documentElement.removeAttribute('style');
});

describe('habit colors', () => {
  it('accepts a palette name or a lowercase #rrggbb, like the API', () => {
    for (const value of ['teal', 'pink', '#0a1b2c', '#ffffff', '#000000']) {
      expect(isValidColor(value), value).toBe(true);
    }
    for (const value of ['#0A1B2C', '#fff', '#gggggg', '#0a1b2c0', ' #0a1b2c', 'magenta', '', null, undefined, 42]) {
      expect(isValidColor(value), String(value)).toBe(false);
    }
    expect(isCustomColor('teal')).toBe(false);
    expect(isHabitColor('#0a1b2c')).toBe(false);
  });

  it('picks dark text over light colors and light text over dark ones', () => {
    expect(textTone('#ffffff')).toBe('dark');
    expect(textTone('#fde047')).toBe('dark');
    expect(textTone('#000000')).toBe('light');
    expect(textTone('#1e3a8a')).toBe('light');
  });

  it('paints a palette color through the data attribute only', () => {
    const element = document.createElement('span');

    applyHabitColor(element, 'teal');

    expect(element.dataset.habitColor).toBe('teal');
    expect(element.dataset.habitText).toBeUndefined();
    expect(element.style.getPropertyValue('--habit-color')).toBe('');
  });

  it('paints a custom color through the CSSOM, with the text tone', () => {
    const element = document.createElement('span');

    applyHabitColor(element, '#ffffff');

    expect(element.dataset.habitColor).toBe(CUSTOM_COLOR);
    expect(element.dataset.habitText).toBe('dark');
    expect(element.style.getPropertyValue('--habit-color')).toBe('#ffffff');
    // CSSOM, não o atributo escrito no HTML (que a CSP bloquearia se viesse no HTML)
    expect(element.getAttribute('style')).toContain('--habit-color');
  });

  it('switches between custom and palette, and clears an invalid color', () => {
    const element = document.createElement('span');

    applyHabitColor(element, '#000000');
    applyHabitColor(element, 'pink');
    expect(element.dataset.habitColor).toBe('pink');
    expect(element.dataset.habitText).toBeUndefined();
    expect(element.style.getPropertyValue('--habit-color')).toBe('');

    applyHabitColor(element, '#000000');
    applyHabitColor(element, 'url(x)');
    expect(element.dataset.habitColor).toBeUndefined();
    expect(element.dataset.habitText).toBeUndefined();
    expect(element.style.getPropertyValue('--habit-color')).toBe('');

    applyHabitColor(element, undefined);
    expect(element.dataset.habitColor).toBeUndefined();
  });

  it('reads the current value of a palette color, when the CSS has it', () => {
    const root = document.documentElement;
    expect(readPaletteHex('teal')).toBeNull();

    root.style.setProperty('--habit-teal', ' #0F766E ');
    root.style.setProperty('--habit-pink', 'var(--x)');

    expect(readPaletteHex('teal')).toBe('#0f766e');
    expect(readPaletteHex('pink')).toBeNull();
    expect(readPaletteHex('magenta')).toBeNull();
    expect(readPaletteHex('teal', null)).toBeNull();
  });
});
