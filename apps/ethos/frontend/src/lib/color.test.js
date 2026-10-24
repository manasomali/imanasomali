import { describe, expect, it } from 'vitest';
import { contrastRatio, parseHex, relativeLuminance } from './color';

describe('color', () => {
  it('parses short and long hex', () => {
    expect(parseHex('#fff')).toEqual({ r: 255, g: 255, b: 255 });
    expect(parseHex('#0F766E')).toEqual({ r: 15, g: 118, b: 110 });
  });

  it.each(['fff', '#ffff', '#gggggg', 'red', '', null])('rejects %s', (value) => {
    expect(() => parseHex(value)).toThrow(TypeError);
  });

  it('computes WCAG luminance and contrast', () => {
    expect(relativeLuminance('#000000')).toBe(0);
    expect(relativeLuminance('#ffffff')).toBe(1);
    expect(contrastRatio('#000', '#fff')).toBe(21);
    expect(contrastRatio('#fff', '#000')).toBe(21);
    expect(contrastRatio('#777', '#777')).toBe(1);
    // Valor de referência: #767676 é o cinza mais claro com 4,5:1 sobre o branco
    expect(contrastRatio('#767676', '#ffffff')).toBeCloseTo(4.54, 2);
  });
});
