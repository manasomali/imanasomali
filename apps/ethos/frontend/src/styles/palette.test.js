import { describe, expect, it } from 'vitest';
import { contrastRatio } from '../lib/color';
import { HABIT_COLORS, isHabitColor } from '../lib/palette';
import { DARK, DARK_MEDIA, LIGHT, readCustomProperties } from '../test/css';
import { readFrontendFile } from '../test/files';

// O axe no jsdom não mede contraste (ver src/test/axe.js): aqui o contraste sai dos valores
const palette = readCustomProperties(readFrontendFile('src/styles/palette.css'));
const tokens = readCustomProperties(readFrontendFile('../../../packages/tokens/tokens.css'));
const models = readFrontendFile('../backend/app/models.py');

const MIN_CONTRAST = 3;
const MIN_TEXT_CONTRAST = 4.5;

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
    const defined = Object.keys(themes[theme].palette).sort();

    expect(defined).toEqual(HABIT_COLORS.map((name) => `--habit-${name}`).sort());
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
