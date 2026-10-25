import { describe, expect, it } from 'vitest';
import { contrastRatio, relativeLuminance } from '../lib/color';
import { MIN_COLOR_CONTRAST, THEME_COLORS } from '../lib/customColor';
import { HABIT_COLORS, isHabitColor, textTone } from '../lib/palette';
import { DARK, DARK_MEDIA, LIGHT, readCustomProperties } from '../lib/css';
import { readFrontendFile } from '../test/files';

// O axe no jsdom não mede contraste (ver src/test/axe.js): aqui o contraste sai dos valores
const palette = readCustomProperties(readFrontendFile('src/styles/palette.css'));
const tokens = readCustomProperties(readFrontendFile('../../../packages/tokens/tokens.css'));
const models = readFrontendFile('../backend/app/models.py');

const MIN_CONTRAST = MIN_COLOR_CONTRAST;
const MIN_TEXT_CONTRAST = 4.5;
// Texto sobre uma cor própria (ETH-49), definido só no :root
const TEXT_TONES = ['--habit-text-light', '--habit-text-dark'];

const themes = {
  light: { palette: palette.get(LIGHT), tokens: tokens.get(LIGHT) },
  dark: { palette: palette.get(DARK), tokens: tokens.get(DARK) },
};

/** Valores do StrEnum HabitColor de app/models.py. */
function backendColors() {
  const block = /class HabitColor\(StrEnum\):([\s\S]*?)\n(?=\S)/.exec(models);
  if (!block) throw new Error('HabitColor não encontrado em app/models.py');
  return [...block[1].matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"/gm)].map((match) => match[1]);
}

describe('habit palette', () => {
  it('has the same 12 colors as HabitColor in the backend', () => {
    expect(HABIT_COLORS).toHaveLength(12);
    expect([...HABIT_COLORS]).toEqual(backendColors());
    expect(isHabitColor('teal')).toBe(true);
    expect(isHabitColor('magenta')).toBe(false);
  });

  it.each(Object.keys(themes))('defines every color in the %s theme', (theme) => {
    const defined = Object.keys(themes[theme].palette).filter((name) => !TEXT_TONES.includes(name));

    expect(defined.sort()).toEqual(HABIT_COLORS.map((name) => `--habit-${name}`).sort());
  });

  it('repeats the same dark values under the media query', () => {
    expect(palette.get(DARK_MEDIA)).toEqual(palette.get(DARK));
  });

  it('maps data-habit-color to every color', () => {
    for (const name of HABIT_COLORS) {
      expect(palette.get(`[data-habit-color='${name}']`)).toEqual({
        '--habit-color': `var(--habit-${name})`,
      });
    }
  });

  describe.each(Object.keys(themes))('%s theme', (theme) => {
    const { palette: colors, tokens: base } = themes[theme];

    it.each(HABIT_COLORS)(`%s has at least ${MIN_CONTRAST}:1 against the background`, (name) => {
      const color = colors[`--habit-${name}`];

      expect(contrastRatio(color, base['--bg'])).toBeGreaterThanOrEqual(MIN_CONTRAST);
      expect(contrastRatio(color, base['--surface'])).toBeGreaterThanOrEqual(MIN_CONTRAST);
    });

    // O dia marcado no calendário escreve o número em var(--bg) sobre a cor do hábito: texto
    // pequeno, então 4,5:1 (WCAG AA)
    it.each(HABIT_COLORS)(`%s has at least ${MIN_TEXT_CONTRAST}:1 as a background for text`, (name) => {
      expect(contrastRatio(colors[`--habit-${name}`], base['--bg'])).toBeGreaterThanOrEqual(
        MIN_TEXT_CONTRAST,
      );
    });
  });
});

describe('custom colors', () => {
  const text = {
    light: themes.light.palette['--habit-text-light'],
    dark: themes.light.palette['--habit-text-dark'],
  };
  // Todas as cores com canais em passos de 17 (00, 11, ..., ff): 4096 cores
  const steps = Array.from({ length: 16 }, (_, index) => (index * 17).toString(16).padStart(2, '0'));
  const sweep = steps.flatMap((r) => steps.flatMap((g) => steps.map((b) => `#${r}${g}${b}`)));

  it('defines the light and dark text once, the same in both themes', () => {
    expect(relativeLuminance(text.light)).toBe(1);
    expect(relativeLuminance(text.dark)).toBe(0);
    for (const tone of TEXT_TONES) {
      expect(Object.keys(themes.dark.palette)).not.toContain(tone);
      expect(Object.keys(palette.get(DARK_MEDIA))).not.toContain(tone);
    }
  });

  it('maps data-habit-text to the text over the color, reset on every colored element', () => {
    expect(palette.get('[data-habit-color]')).toEqual({ '--habit-color-text': 'var(--bg)' });
    for (const tone of ['light', 'dark']) {
      expect(palette.get(`[data-habit-text='${tone}']`)).toEqual({
        '--habit-color-text': `var(--habit-text-${tone})`,
      });
    }
  });

  it(`picks a text with at least ${MIN_TEXT_CONTRAST}:1 over any color`, () => {
    const worst = Math.min(...sweep.map((hex) => contrastRatio(hex, text[textTone(hex)])));

    expect(sweep).toHaveLength(4096);
    expect(new Set(sweep.map(textTone))).toEqual(new Set(['light', 'dark']));
    expect(worst).toBeGreaterThanOrEqual(MIN_TEXT_CONTRAST);
  });

  it('reads the colors of both themes from the tokens', () => {
    for (const theme of Object.keys(themes)) {
      expect(THEME_COLORS[theme]).toEqual({
        bg: themes[theme].tokens['--bg'],
        surface: themes[theme].tokens['--surface'],
        fg: themes[theme].tokens['--fg'],
      });
    }
  });
});
