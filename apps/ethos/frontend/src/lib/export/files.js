// Arquivos do export (File, prontos para baixar ou compartilhar) e os nomes deles.

import { CSV_MIME, toCsv } from './csv';
import { JSON_MIME, toJson } from './json';

/**
 * Nome de arquivo seguro: só letras ASCII, números, ponto, hífen e sublinhado, sem ponto nem
 * hífen nas pontas (nada de "../" nem arquivo oculto).
 */
export function exportFilename(base, extension) {
  const safe = String(base).replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '');
  return `${safe || 'ethos'}.${extension}`;
}

/** Nome do arquivo de um relatório: "ethos-<from>_<to>.<ext>". */
export function reportFilename(from, to, extension) {
  return exportFilename(`ethos-${from}_${to}`, extension);
}

/** O CSV do relatório como File. `t`: o t do i18next (cabeçalho no idioma da tela). */
export function csvFile(report, { t }) {
  return new File([toCsv(report, { t })], reportFilename(report.from, report.to, 'csv'), {
    type: CSV_MIME,
  });
}

/** O JSON do relatório como File. `generatedAt`: o instante da geração (Date). */
export function jsonFile(report, { generatedAt }) {
  return new File([toJson(report, { generatedAt })], reportFilename(report.from, report.to, 'json'), {
    type: JSON_MIME,
  });
}
