// Contraste entre cores (WCAG 2.1). Usado pelo teste da paleta e por telas que precisam escolher
// a cor de um texto sobre a cor de um hábito

const HEX_RE = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

/** Canais {r, g, b} de 0 a 255 de uma cor "#rgb" ou "#rrggbb"; lança TypeError fora disso. */
export function parseHex(hex) {
  const match = typeof hex === 'string' ? HEX_RE.exec(hex.trim()) : null;
  if (!match) throw new TypeError(`cor inválida: ${hex}`);
  let digits = match[1];
  if (digits.length === 3) digits = [...digits].map((digit) => digit + digit).join('');
  return {
    r: Number.parseInt(digits.slice(0, 2), 16),
    g: Number.parseInt(digits.slice(2, 4), 16),
    b: Number.parseInt(digits.slice(4, 6), 16),
  };
}

function linear(channel) {
  const value = channel / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

/** Luminância relativa, de 0 (preto) a 1 (branco). */
export function relativeLuminance(hex) {
  const { r, g, b } = parseHex(hex);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

/** Razão de contraste entre duas cores, de 1 a 21. */
export function contrastRatio(a, b) {
  const [light, dark] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}
