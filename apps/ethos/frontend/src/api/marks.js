// Marcações de um hábito: leitura por ano e as escritas (toggle, criar, editar, apagar) com
// atualização otimista.
//
// Cache: uma entrada por hábito, ano e fuso (`markKeys.year`), com TODAS as marcações do ano local
// (array de MarkOut, por `marked_at` e id). A aba principal e a aba do hábito leem a mesma
// entrada, então marcar numa aparece na outra sem buscar de novo. Uma request por hábito e ano
// (páginas de até 1000; um hábito toggle cabe numa página só). A faixa do calendário (mês, 3 meses
// ou ano) lê os anos que toca: a janela de 3 meses que cruza o ano lê os dois, e cada escrita mexe
// só no ano do dia dela.
//
// Escritas otimistas: a tela muda na hora e, se a API falhar, a mudança é desfeita (a operação
// inversa, não uma foto do cache, para não apagar o efeito de outro clique que ainda está a
// caminho). Quando dois cliques no mesmo hábito se cruzam, ou a resposta não bate com o que a tela
// supôs (ex.: outro membro marcou o mesmo dia), o ano é buscado de novo depois da última escrita.

import { useCallback } from 'react';
import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query';
import { meQueryKey } from './auth';
import { habitKeys } from './habits';
import { historyKeys } from './history';
import { reportKeys } from './progress';
import { apiFetch } from '../lib/api';
import { marksByDay, yearOf, yearRange } from '../lib/calendar';
import { dayBounds, localDate } from '../lib/time';

export const markKeys = Object.freeze({
  all: ['marks'],
  habit: (habitId) => ['marks', habitId],
  year: (habitId, year, timeZone) => ['marks', habitId, year, timeZone],
});

// A API recusa instantes antes de 1900-01-01 UTC (MIN_INSTANT em app/marks/schemas.py), e nenhuma
// marcação é anterior a isso. O ano local 1900 a leste de UTC (e 1899 a oeste) começa antes
const MIN_INSTANT = Date.UTC(1900, 0, 1);

/** Todas as marcações do hábito no ano local `year` (segue o `next_cursor` até a última página). */
export async function fetchYearMarks(habitId, year, timeZone, { signal } = {}) {
  const { from, to } = yearRange(year, timeZone);
  const query = {
    from: new Date(Math.max(from.getTime(), MIN_INSTANT)).toISOString(),
    to: to.toISOString(),
  };
  const marks = [];
  let cursor = null;
  do {
    const page = await apiFetch(`/habits/${habitId}/marks`, {
      query: { ...query, cursor },
      signal,
    });
    marks.push(...page.marks);
    // Cursor repetido seria um laço sem fim: a API sempre anda, mas o front não depende disso
    cursor = page.next_cursor !== cursor ? page.next_cursor : null;
  } while (cursor);
  return marks;
}

/**
 * Opções da consulta do ano (chave e função), para useQuery ou queryClient.fetchQuery. O
 * relatório (src/api/report.js) lê as marcações por aqui, então usa o mesmo cache dos calendários.
 */
export function yearMarksQuery(habitId, year, timeZone, select) {
  return {
    queryKey: markKeys.year(habitId, year, timeZone),
    queryFn: ({ signal }) => fetchYearMarks(habitId, year, timeZone, { signal }),
    select,
  };
}

// Resultado das consultas dos anos de uma faixa: falhou se algum ano ficou sem dados
function firstError(results) {
  return results.find((result) => result.error && result.data === undefined)?.error ?? null;
}

function refetchFailed(results) {
  return () => results.forEach((result) => result.error && result.refetch());
}

/**
 * Marcações do hábito nos anos `years` (os de calendarRange: 1, ou 2 quando a janela de 3 meses
 * cruza o ano), uma consulta por ano no cache do ano. `data`: Map "AAAA-MM-DD" → marcações, só
 * com todos os anos carregados; `isPending` enquanto algum carrega; `error`: o de um ano sem dados;
 * `refetch` busca de novo os que falharam.
 */
export function useMarks(habitId, years, timeZone) {
  const combine = useCallback(
    (results) => ({
      data: results.every((result) => result.data !== undefined)
        ? marksByDay(results.flatMap((result) => result.data), timeZone)
        : undefined,
      isPending: results.some((result) => result.isPending),
      error: firstError(results),
      refetch: refetchFailed(results),
    }),
    [timeZone],
  );
  return useQueries({
    queries: years.map((year) => yearMarksQuery(habitId, year, timeZone)),
    combine,
  });
}

/**
 * Marcações de vários hábitos nos anos `years` (como em useMarks), uma request por hábito e ano,
 * em paralelo. `byHabit`: Map do id para o Map dia → marcações, só dos hábitos com todos os anos
 * carregados; `pending` enquanto algum carrega; `error`: o de um ano sem dados.
 */
export function useMarksOfHabits(habits, years, timeZone) {
  const combine = useCallback(
    (results) => {
      const byHabit = new Map();
      habits.forEach((habit, index) => {
        const own = results.slice(index * years.length, (index + 1) * years.length);
        if (own.every((result) => result.data !== undefined)) {
          byHabit.set(habit.id, marksByDay(own.flatMap((result) => result.data), timeZone));
        }
      });
      return {
        byHabit,
        pending: results.some((result) => result.isPending),
        error: firstError(results),
        refetch: refetchFailed(results),
      };
    },
    [habits, years, timeZone],
  );
  return useQueries({
    queries: habits.flatMap((habit) =>
      years.map((year) => yearMarksQuery(habit.id, year, timeZone)),
    ),
    combine,
  });
}

// Ids das marcações otimistas: negativos, nunca colidem com os da API
let lastTempId = 0;

function byInstant(a, b) {
  return Date.parse(a.marked_at) - Date.parse(b.marked_at) || a.id - b.id;
}

function withMark(marks, mark) {
  if (!marks || marks.some((item) => item.id === mark.id)) return marks;
  return [...marks, mark].sort(byInstant);
}

function withoutMarks(marks, ids) {
  if (!marks) return marks;
  const remove = new Set(ids);
  return marks.filter((mark) => !remove.has(mark.id));
}

function replaceMark(marks, id, mark) {
  if (!marks?.some((item) => item.id === id)) return marks;
  return marks.map((item) => (item.id === id ? mark : item)).sort(byInstant);
}

// Hábitos com escrita cruzada ou resposta inesperada, que buscam o ano de novo quando a última
// escrita terminar. Um conjunto por QueryClient (o app tem um; cada teste, o seu)
const resyncs = new WeakMap();

function resyncSet(queryClient) {
  let set = resyncs.get(queryClient);
  if (!set) {
    set = new Set();
    resyncs.set(queryClient, set);
  }
  return set;
}

/**
 * Depois que as marcações de um hábito mudaram: o relatório (src/api/report.js) guarda totais e
 * períodos derivados delas e é refeito, o histórico ganhou eventos, e a pontuação (só se ligada)
 * vem do GET /habits.
 */
export function afterMarksChanged(queryClient, habit) {
  queryClient.invalidateQueries({ queryKey: reportKeys.all });
  queryClient.invalidateQueries({ queryKey: historyKeys.all });
  if (!habit.score_enabled) return;
  queryClient.invalidateQueries({ queryKey: habitKeys.lists() });
  queryClient.invalidateQueries({ queryKey: habitKeys.detail(habit.id) });
}

/**
 * Base das escritas otimistas num hábito. `apply(marks)` devolve `{marks, op}`: o cache novo e a
 * operação feita (para desfazer); `reconcile(data, op)` ajusta o cache com a resposta e devolve
 * false quando ela não bate com o que a tela supôs.
 */
function useOptimisticMarks(habit, timeZone, { request, apply, reconcile }) {
  const queryClient = useQueryClient();
  const mutationKey = markKeys.habit(habit.id);

  return useMutation({
    mutationKey,
    mutationFn: request,
    onMutate: async (variables) => {
      const queryKey = markKeys.year(habit.id, yearOf(variables.day), timeZone);
      // Uma busca em andamento sobrescreveria a mudança otimista com dados velhos
      await queryClient.cancelQueries({ queryKey });
      if (queryClient.isMutating({ mutationKey }) > 1) resyncSet(queryClient).add(habit.id);
      let op = null;
      queryClient.setQueryData(queryKey, (marks) => {
        if (!marks) return marks;
        const result = apply(marks, variables);
        op = result.op;
        return result.marks;
      });
      // Sem o ano no cache não há o que supor: a resposta é conferida pela nova busca
      if (op === null) resyncSet(queryClient).add(habit.id);
      return { queryKey, op };
    },
    onSuccess: (data, variables, context) => {
      if (context.op && !reconcile(data, context.op, context.queryKey)) {
        resyncSet(queryClient).add(habit.id);
      }
    },
    onError: (error, variables, context) => {
      const op = context?.op;
      if (op?.added) {
        queryClient.setQueryData(context.queryKey, (marks) => withoutMarks(marks, [op.added.id]));
      }
      if (op?.removed) {
        queryClient.setQueryData(context.queryKey, (marks) => op.removed.reduce(withMark, marks));
      }
      // Ex.: mark_mode_mismatch (a configuração mudou) ou o dia foi mexido por outro membro
      resyncSet(queryClient).add(habit.id);
      if (error?.code === 'mark_mode_mismatch' || error?.code === 'habit_archived') {
        queryClient.invalidateQueries({ queryKey: habitKeys.all });
      }
    },
    onSettled: () => {
      // A escrita atual ainda conta como pendente aqui: 1 é "esta é a última"
      if (queryClient.isMutating({ mutationKey }) > 1) return;
      const set = resyncSet(queryClient);
      if (set.delete(habit.id)) queryClient.invalidateQueries({ queryKey: mutationKey });
      afterMarksChanged(queryClient, habit);
    },
  });
}

/** Marcação provisória, mostrada até a API responder. */
function tempMark(queryClient, habit, markedAt) {
  lastTempId -= 1;
  const me = queryClient.getQueryData(meQueryKey);
  return {
    id: lastTempId,
    habit_id: habit.id,
    author: me ? { id: me.id, email: me.email } : null,
    marked_at: markedAt.toISOString(),
    duration_minutes: habit.duration_enabled ? habit.duration_minutes : null,
    cost_cents: habit.cost_enabled ? habit.cost_cents : null,
    note: null,
    created_at: markedAt.toISOString(),
    updated_at: markedAt.toISOString(),
    pending: true,
  };
}

function reconcileAdded(queryClient, mark, op, queryKey) {
  queryClient.setQueryData(queryKey, (marks) => replaceMark(marks, op.added.id, mark));
}

/**
 * Marca ou desmarca um dia de um hábito toggle (botões do painel do dia e o duplo clique no dia da
 * aba do hábito; o clique simples no calendário só escolhe o dia): `mutate({day, markedAt})`
 * (`markedAt` de markedAtFor). Manda o início e o fim do dia local; a tela marca ou desmarca na hora.
 */
export function useToggleMark(habit, timeZone) {
  const queryClient = useQueryClient();
  return useOptimisticMarks(habit, timeZone, {
    request: ({ day, markedAt }) => {
      const { start, end } = dayBounds(day, timeZone);
      return apiFetch(`/habits/${habit.id}/toggle`, {
        method: 'POST',
        body: { day_start: start, day_end: end, marked_at: markedAt },
      });
    },
    apply: (marks, { day, markedAt }) => {
      const inDay = marks.filter((mark) => localDate(mark.marked_at, timeZone) === day);
      if (inDay.length > 0) {
        return { marks: withoutMarks(marks, inDay.map((mark) => mark.id)), op: { removed: inDay } };
      }
      const added = tempMark(queryClient, habit, markedAt);
      return { marks: withMark(marks, added), op: { added } };
    },
    reconcile: (data, op, queryKey) => {
      if (op.added) {
        if (data.marked) {
          reconcileAdded(queryClient, data.mark, op, queryKey);
          return true;
        }
        // A API desmarcou: o dia já tinha marcação (de outro membro, que a tela não via)
        queryClient.setQueryData(queryKey, (marks) => withoutMarks(marks, [op.added.id]));
        return false;
      }
      return !data.marked;
    },
  });
}

/** Nova marcação num hábito com várias por dia: `mutate({day, markedAt})`, com os padrões. */
export function useCreateMark(habit, timeZone) {
  const queryClient = useQueryClient();
  return useOptimisticMarks(habit, timeZone, {
    request: ({ markedAt }) =>
      apiFetch(`/habits/${habit.id}/marks`, { method: 'POST', body: { marked_at: markedAt } }),
    apply: (marks, { markedAt }) => {
      const added = tempMark(queryClient, habit, markedAt);
      return { marks: withMark(marks, added), op: { added } };
    },
    reconcile: (mark, op, queryKey) => {
      reconcileAdded(queryClient, mark, op, queryKey);
      return true;
    },
  });
}

/** Apaga uma marcação: `mutate({day, mark})`, com `day` o dia local dela. */
export function useDeleteMark(habit, timeZone) {
  return useOptimisticMarks(habit, timeZone, {
    request: ({ mark }) =>
      apiFetch(`/habits/${habit.id}/marks/${mark.id}`, { method: 'DELETE' }),
    apply: (marks, { mark }) => ({
      marks: withoutMarks(marks, [mark.id]),
      op: { removed: [mark] },
    }),
    reconcile: () => true,
  });
}

/**
 * Edita observação, duração e custo de uma marcação: `mutate({mark, changes})`, só com os campos
 * que mudaram. Não é otimista: o formulário espera a resposta para mostrar o erro no campo.
 */
export function useUpdateMark(habit) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ mark, changes }) =>
      apiFetch(`/habits/${habit.id}/marks/${mark.id}`, { method: 'PATCH', body: changes }),
    onSuccess: (updated) => {
      queryClient.setQueriesData({ queryKey: markKeys.habit(habit.id) }, (marks) =>
        replaceMark(marks, updated.id, updated),
      );
      afterMarksChanged(queryClient, habit);
    },
  });
}
