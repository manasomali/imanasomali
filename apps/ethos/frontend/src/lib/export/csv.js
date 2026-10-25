// CSV do relatório: uma linha por marcação, com as colunas hábito, data, horário, autor, duração,
// custo e observação (ethos-plan.md). Coluna de informação não escolhida, ou de recurso desligado
// em todos os hábitos do relatório, sai do arquivo; num hábito com o recurso desligado, a célula
// fica vazia.
//
// Formato (RFC 4180): separador vírgula, linhas com CRLF e BOM no começo (o Excel só lê UTF-8
// com ele). Célula com vírgula, aspas, CR ou LF vai entre aspas, com as aspas dobradas.
// Injeção de fórmula: célula que começa com =, +, - ou @ (e também TAB e CR, que o Excel trata
// igual) ganha um ' na frente, para a planilha mostrar o texto em vez de executar a fórmula.
// O cabeçalho vem no idioma da tela. Valores: data "AAAA-MM-DD" e horário "HH:MM" no fuso do
// relatório, duração em minutos, custo com ponto e 2 casas ("1234.50", sem separador de milhar).

export const CSV_MIME = 'text/csv;charset=utf-8';

const BOM = '﻿';
const FORMULA_START = /^[=+\-@\t\r]/;
const NEEDS_QUOTES = /[",\r\n]/;

/** Uma célula pronta para o arquivo: protegida contra fórmula e escapada. */
export function csvCell(value) {
  let text = value === null || value === undefined ? '' : String(value);
  if (FORMULA_START.test(text)) text = `'${text}`;
  return NEEDS_QUOTES.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/** Linhas (arrays de valores) em texto CSV, com BOM e CRLF. */
export function csvText(rows) {
  return BOM + rows.map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

/** Centavos (inteiro, não negativo) como decimal com ponto: 123450 → "1234.50". */
export function centsToDecimal(cents) {
  if (!Number.isSafeInteger(cents) || cents < 0) {
    throw new TypeError(`centavos precisam ser um inteiro não negativo: ${cents}`);
  }
  return `${Math.trunc(cents / 100)}.${String(cents % 100).padStart(2, '0')}`;
}

/** Colunas do CSV para o relatório, na ordem do arquivo. */
export function csvColumns(report) {
  const any = (field) => report.habits.some((item) => item.show[field]);
  const columns = ['habit', 'date', 'time'];
  if (report.options.author) columns.push('author');
  if (any('duration')) columns.push('duration');
  if (any('cost')) columns.push('cost');
  if (any('note')) columns.push('note');
  return columns;
}

function cellOf(column, item, mark, t) {
  switch (column) {
    case 'habit':
      return item.habit.name;
    case 'date':
      return mark.date;
    case 'time':
      return mark.time;
    case 'author':
      return mark.author ? mark.author.email : t('report.removed_user');
    case 'duration':
      return item.show.duration ? mark.duration_minutes : null;
    case 'cost':
      return item.show.cost && Number.isSafeInteger(mark.cost_cents)
        ? centsToDecimal(mark.cost_cents)
        : null;
    default:
      // 'note'
      return item.show.note ? mark.note : null;
  }
}

/** O CSV do relatório (texto). `t`: o t do i18next, para o cabeçalho e "usuário removido". */
export function toCsv(report, { t }) {
  const columns = csvColumns(report);
  const rows = [columns.map((column) => t(`report.csv.${column}`))];
  for (const item of report.habits) {
    for (const mark of item.marks) {
      rows.push(columns.map((column) => cellOf(column, item, mark, t)));
    }
  }
  return csvText(rows);
}
