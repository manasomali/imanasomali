import { describe, expect, it } from 'vitest';
import { contrastRatio } from './color';
import { MIN_COLOR_CONTRAST, THEME_COLORS, lowContrastThemes, themeColors } from './customColor';

// Os valores de THEME_COLORS contra packages/tokens/tokens.css: src/styles/palette.test.js

describe('custom color contrast', () => {
  it('warns about white in the light theme only', () => {
    expect(lowContrastThemes('#ffffff')).toEqual([{ theme: 'light', ratio: 1 }]);
  });

  it('warns about black in the dark theme only', () => {
    const [warning, ...rest] = lowContrastThemes('#000000');

    expect(rest).toEqual([]);
    expect(warning.theme).toBe('dark');
    expect(warning.ratio).toBeLessThan(MIN_COLOR_CONTRAST);
  });

  it('does not warn about a color that works in both themes', () => {
    expect(lowContrastThemes('#808080')).toEqual([]);
  });

  it('checks the surface too, not only the page background', () => {
    // Passa contra o branco, mas não contra o #f5f5f5 das superfícies
    const themes = { light: { bg: '#ffffff', surface: '#f5f5f5' }, dark: THEME_COLORS.dark };
    expect(contrastRatio('#909090', '#ffffff')).toBeGreaterThan(MIN_COLOR_CONTRAST);
    const [warning] = lowContrastThemes('#909090', themes);

    expect(warning.theme).toBe('light');
    expect(warning.ratio).toBeLessThan(MIN_COLOR_CONTRAST);
  });

  it('refuses tokens without a theme background', () => {
    expect(() => themeColors(':root { --bg: #fff; --surface: #eee; --fg: #000; }')).toThrow(
      /--bg em :root\[data-theme='dark'\]/,
    );
  });
});
