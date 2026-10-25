// Dados do relatório e do export: o GET /habits/progress do período mais as marcações de cada
// hábito no período. Tudo é montado no navegador (src/lib/export/).
//
// Marcações: lidas pelo cache do ano dos calendários (yearMarksQuery em src/api/marks.js; o
// GET /habits/{id}/marks aceita até 367 dias por chamada, e cada ano segue o next_cursor), uma
// consulta por hábito e ano, no máximo MARK_REQUESTS ao mesmo tempo. Só os anos entre a primeira e
// a última marcação do hábito (`marks_range` da API) são buscados: hábito sem marcação não custa
// nenhuma chamada.
//
// Período maior que 5 anos (só o "exportar tudo"): o progresso vem em pedaços de até 5 anos
// (periodChunks), juntados por hábito; um período da meta que cruza a divisa vem nos dois pedaços,
// inteiro e igual, e entra uma vez.

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { csvFile, jsonFile } from '../lib/export/files';
import { ALL_OPTIONS } from '../lib/export/options';
import { MIN_REPORT_DAY, periodChunks, yearsOf } from '../lib/export/period';
import { buildReport } from '../lib/export/report';
import { localDate, today as todayIn } from '../lib/time';
import { yearMarksQuery } from './marks';
import { fetchProgress, reportKeys } from './progress';

// Chamadas de marcações em paralelo
const MARK_REQUESTS = 4;

/** `fn` em cada item, no máximo `limit` ao mesmo tempo; para no primeiro erro. */
async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  let failed = false;
  const worker = async () => {
    while (!failed && next < items.length) {
      const index = next;
      next += 1;
      try {
        results[index] = await fn(items[index]);
      } catch (error) {
        failed = true;
        throw error;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

function appendPeriods(list, more) {
  const last = list.length > 0 ? list[list.length - 1].first_day : null;
  for (const period of more) {
    if (last === null || period.first_day > last) list.push(period);
  }
  return list;
}

// Junta os pedaços do progresso por hábito, na ordem dos ids
function mergeProgress(responses) {
  const byId = new Map();
  for (const response of responses) {
    for (const item of response.habits) {
      const current = byId.get(item.habit.id);
      if (!current) {
        byId.set(item.habit.id, {
          ...item,
          periods: [...item.periods],
          cost_periods: item.cost_periods ? [...item.cost_periods] : undefined,
        });
        continue;
      }
      current.habit = item.habit;
      current.goal_target = item.goal_target;
      current.marks_range = item.marks_range;
      appendPeriods(current.periods, item.periods);
      if (item.cost_periods) current.cost_periods = appendPeriods(current.cost_periods ?? [], item.cost_periods);
    }
  }
  return [...byId.values()].sort((a, b) => a.habit.id - b.habit.id);
}

// Anos a buscar: os do período que ficam entre a primeira e a última marcação do hábito
function markYears(item, from, to) {
  const range = item.marks_range;
  if (!range) return [];
  const first = range.first_day > from ? range.first_day : from;
  const last = range.last_day < to ? range.last_day : to;
  return first <= last ? yearsOf(first, last) : [];
}

/**
 * Os dados do relatório: `{from, to, timezone, habits: [{habit, goal_target, periods,
 * cost_periods?, marks_range, marks}]}`, com `marks` (MarkOut) só do período, por instante.
 * `habitIds` null: todos os hábitos que a pessoa acessa, inclusive arquivados. O fuso usado é o
 * da API (o da conta).
 */
export async function fetchReportData(queryClient, { from, to, habitIds = null, timeZone, signal }) {
  const responses = [];
  // Uma marcação de 1/1/1900 UTC cai em 31/12/1899 a oeste de UTC, antes do que a API de
  // progresso aceita: o progresso começa em 1900, e as marcações seguem o período inteiro
  const progressFrom = from < MIN_REPORT_DAY ? MIN_REPORT_DAY : from;
  for (const chunk of periodChunks(progressFrom, to)) {
    responses.push(await fetchProgress({ ...chunk, habitIds, signal }));
  }
  const timezone = responses[0].timezone ?? timeZone;
  const habits = mergeProgress(responses);

  const tasks = habits.flatMap((item) =>
    markYears(item, from, to).map((year) => ({ id: item.habit.id, year })),
  );
  const years = await mapLimit(tasks, MARK_REQUESTS, ({ id, year }) => {
    // Consulta cancelada (saiu da tela, mudou o período): não começa mais nenhuma
    if (signal?.aborted) throw new DOMException('cancelado', 'AbortError');
    return queryClient.fetchQuery(yearMarksQuery(id, year, timezone));
  });
  const marks = new Map(habits.map((item) => [item.habit.id, []]));
  tasks.forEach(({ id }, index) => {
    const list = marks.get(id);
    for (const mark of years[index]) {
      // Marcação otimista (ainda sem resposta da API) fica de fora
      if (mark.pending) continue;
      const day = localDate(mark.marked_at, timezone);
      if (day >= from && day <= to) list.push(mark);
    }
  });

  return {
    from,
    to,
    timezone,
    habits: habits.map((item) => ({ ...item, marks: marks.get(item.habit.id) })),
  };
}

/**
 * Os dados de TODOS os hábitos (inclusive arquivados) em TODO o período: do primeiro dia com
 * marcação ou da criação mais antiga (o que vier antes) até hoje (ou a última marcação). Uma
 * chamada de hoje descobre os hábitos e o `marks_range` de cada um; depois, fetchReportData.
 */
export async function fetchAllReportData(queryClient, { timeZone, signal }) {
  const day = todayIn(timeZone);
  const probe = await fetchProgress({ from: day, to: day, signal });
  const timezone = probe.timezone ?? timeZone;
  let from = todayIn(timezone);
  let to = from;
  for (const item of probe.habits) {
    const created = localDate(item.habit.created_at, timezone);
    if (created < from) from = created;
    const range = item.marks_range;
    if (range && range.first_day < from) from = range.first_day;
    if (range && range.last_day > to) to = range.last_day;
  }
  return fetchReportData(queryClient, { from, to, habitIds: null, timeZone: timezone, signal });
}

/** Formatos do "exportar tudo". */
export const EXPORT_ALL_FORMATS = Object.freeze(['json', 'csv']);

/**
 * "Exportar tudo": todos os hábitos (inclusive arquivados), todo o período, todas as informações
 * (ALL_OPTIONS). Devolve o File ('json' ou 'csv'), sem baixar; quem chama entrega com
 * downloadBlob/shareOrDownload (src/lib/export/share.js). Usado pelo componente ExportAll (tela
 * do relatório e conta, ETH-38). `t`: o t do i18next (cabeçalho do CSV); `now`: o instante da
 * geração.
 */
export async function exportAllFile(queryClient, { timeZone, format, t, now = new Date(), signal }) {
  if (!EXPORT_ALL_FORMATS.includes(format)) throw new RangeError(`formato desconhecido: ${format}`);
  const data = await fetchAllReportData(queryClient, { timeZone, signal });
  const report = buildReport(data, ALL_OPTIONS, { today: todayIn(data.timezone, now) });
  return format === 'csv' ? csvFile(report, { t }) : jsonFile(report, { generatedAt: now });
}

/**
 * Dados do relatório na tela, em cache por período, hábitos e fuso (`reportKeys.data`).
 * `habitIds` null: todos. Refeito quando as marcações mudam (afterMarksChanged) e quando a
 * configuração de um hábito muda (invalidar habitKeys.all).
 */
export function useReportData({ from, to, habitIds, timeZone, enabled = true }) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: reportKeys.data({ from, to, habitIds, timeZone }),
    queryFn: ({ signal }) => fetchReportData(queryClient, { from, to, habitIds, timeZone, signal }),
    enabled,
  });
}
