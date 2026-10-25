// Progresso dos hábitos num período (GET /habits/progress, ETH-23): configuração, pontuação atual,
// períodos da meta e do limite de custo e `marks_range` (primeiro e último dia com marcação, de
// todo o tempo). Datas locais "AAAA-MM-DD", inclusivas, no fuso da conta; até 5 anos e até 100
// ids por chamada.

import { apiFetch } from '../lib/api';

/** Ids por chamada (MAX_HABIT_IDS em app/progress/schemas.py). */
export const MAX_PROGRESS_IDS = 100;

// Chaves do relatório. Ficam embaixo de `habitKeys.all` (['habits']): mudar a configuração de um
// hábito (que invalida habitKeys.all) também refaz o relatório. As marcações invalidam
// `reportKeys.all` em afterMarksChanged (src/api/marks.js)
export const reportKeys = Object.freeze({
  all: ['habits', 'report'],
  data: (params) => ['habits', 'report', params],
});

/**
 * `{from, to, timezone, habits}` da API. `habitIds` null: todos os hábitos que a pessoa acessa,
 * inclusive arquivados; com mais de 100 ids, faz uma chamada por grupo de 100 e junta (por id).
 */
export async function fetchProgress({ from, to, habitIds = null, signal } = {}) {
  if (habitIds === null) {
    return apiFetch('/habits/progress', { query: { from, to }, signal });
  }
  const groups = [];
  for (let index = 0; index < habitIds.length; index += MAX_PROGRESS_IDS) {
    groups.push(habitIds.slice(index, index + MAX_PROGRESS_IDS));
  }
  if (groups.length === 0) return { from, to, timezone: null, habits: [] };
  const responses = await Promise.all(
    groups.map((ids) =>
      apiFetch('/habits/progress', { query: { from, to, habit_ids: ids }, signal }),
    ),
  );
  return {
    ...responses[0],
    habits: responses.flatMap((response) => response.habits).sort((a, b) => a.habit.id - b.habit.id),
  };
}
