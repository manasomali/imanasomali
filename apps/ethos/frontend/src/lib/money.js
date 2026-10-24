// Dinheiro numa unidade genérica: guardado em centavos (inteiro), mostrado sem símbolo de moeda,
// formatado pelo idioma com 2 casas ("1.234,50" em pt, "1,234.50" em en)

/** Maior valor aceito pela API (MAX_MONEY_CENTS em app/habits/schemas.py). */
export const MAX_MONEY_CENTS = 10 ** 12;

const formatters = new Map();

function formatter(locale) {
  let value = formatters.get(locale);
  if (!value) {
    value = new Intl.NumberFormat(locale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    formatters.set(locale, value);
  }
  return value;
}

/** Formata centavos (inteiro) no idioma dado, com 2 casas e sem símbolo. */
export function formatMoney(cents, locale) {
  if (!Number.isSafeInteger(cents)) {
    throw new TypeError(`centavos precisam ser um inteiro: ${cents}`);
  }
  return formatter(locale).format(cents / 100);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function separators(locale) {
  const parts = formatter(locale).formatToParts(12345.6);
  return {
    group: parts.find((part) => part.type === 'group')?.value ?? '',
    decimal: parts.find((part) => part.type === 'decimal').value,
  };
}

/**
 * Lê um valor digitado no idioma dado e devolve centavos, ou null se não for um valor válido
 * entre 0 e MAX_MONEY_CENTS. Aceita o separador de milhar só nas posições certas ("1.234,5" em
 * pt) e até 2 casas decimais.
 */
export function parseMoney(text, locale) {
  if (typeof text !== 'string') return null;
  const { group, decimal } = separators(locale);
  const g = escapeRegExp(group);
  const d = escapeRegExp(decimal);
  const grouped = group ? `\\d{1,3}(?:${g}\\d{3})+|` : '';
  const match = new RegExp(`^(${grouped}\\d+)(?:${d}(\\d{1,2}))?$`).exec(text.trim());
  if (!match) return null;
  const units = Number(group ? match[1].split(group).join('') : match[1]);
  const cents = units * 100 + Number((match[2] ?? '').padEnd(2, '0'));
  return cents <= MAX_MONEY_CENTS ? cents : null;
}
