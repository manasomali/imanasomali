// Estado do relatório na URL (`/relatorio?from=2026-01-01&to=2026-12-31&habit_id=3&habit_id=5`,
// montada por reportPath em src/paths.js), para voltar e compartilhar o link. Sem `habit_id`:
// todos os hábitos. Período ausente ou inválido (data que não existe, invertido, mais de 5 anos):
// o ano atual até hoje.

import { parseHabitId } from '../../paths';
import { checkPeriod, presetPeriod } from './period';

/** Período padrão: de 1º de janeiro até hoje. */
export const DEFAULT_PRESET = 'year';

/** `{from, to, habitIds}` da query da URL; `habitIds` null quer dizer todos. */
export function parseReportSearch(searchParams, today) {
  let from = searchParams.get('from') ?? '';
  let to = searchParams.get('to') ?? '';
  if (checkPeriod(from, to) !== null) ({ from, to } = presetPeriod(DEFAULT_PRESET, today));
  const ids = [];
  for (const value of searchParams.getAll('habit_id')) {
    const id = parseHabitId(value);
    if (id !== null && !ids.includes(id)) ids.push(id);
  }
  return { from, to, habitIds: ids.length > 0 ? ids.sort((a, b) => a - b) : null };
}
