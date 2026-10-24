// Leitura simples das propriedades customizadas de um CSS de tokens, agrupadas pelo seletor do
// bloco. Dentro de @media, o seletor vem prefixado pela regra ("@media (...) :root:not(...)").
// Basta para tokens.css e palette.css: sem chaves dentro de valores nem @media aninhado

export function readCustomProperties(css) {
  const blocks = new Map();
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const stack = [];
  let buffer = '';
  for (const char of text) {
    if (char === '{') {
      stack.push(buffer.trim());
      buffer = '';
    } else if (char === '}') {
      const selector = stack.join(' ');
      const props = blocks.get(selector) ?? {};
      for (const declaration of buffer.split(';')) {
        const match = /^\s*(--[\w-]+)\s*:\s*(.+?)\s*$/.exec(declaration);
        if (match) props[match[1]] = match[2];
      }
      if (Object.keys(props).length > 0) blocks.set(selector, props);
      stack.pop();
      buffer = '';
    } else {
      buffer += char;
    }
  }
  return blocks;
}

export const LIGHT = ':root';
export const DARK = ":root[data-theme='dark']";
export const DARK_MEDIA = "@media (prefers-color-scheme: dark) :root:not([data-theme='light'])";
