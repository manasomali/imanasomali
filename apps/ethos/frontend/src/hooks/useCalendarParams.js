import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import {
  RANGE_STORAGE_KEY,
  rangeNeighbors,
  resolveCalendar,
  switchAnchor,
  writeRangeParams,
} from '../lib/calendarRange';
import { VIEW_STORAGE_KEY, resolveView } from '../lib/calendarView';
import { readItem, writeItem } from '../lib/storage';

// Faixa, dia e visão escolhidos no calendário, na URL
// (`?range=3months&month=2026-03&day=2026-03-04&view=columns`), para o voltar do navegador e o link
// compartilhado mostrarem o mesmo; o tipo da faixa e a visão também ficam lembrados no navegador.
// Regras em resolveCalendar (src/lib/calendarRange.js) e resolveView (src/lib/calendarView.js).
// `today` é o dia de hoje no fuso da conta. Devolve:
// - `range` (calendarRange), `day` (o dia escolhido, ou null) e `view` ('grid' ou 'columns');
// - `previous`/`next`: as âncoras vizinhas, null quando não há para onde ir; `move(anchor)` vai
//   para uma delas (empilha no histórico e solta o dia);
// - `setKind(kind)`: troca o tipo, lembra a escolha e mantém o dia escolhido visível;
// - `setDay(day)`: escolhe um dia da faixa (sem empilhar: o voltar volta de tela, não de dia);
// - `setView(view)`: troca a visão e lembra a escolha, com a mesma faixa e o mesmo dia.
export default function useCalendarParams(today) {
  const [params, setParams] = useSearchParams();
  const search = params.toString();
  const storedKind = readItem(RANGE_STORAGE_KEY);
  const view = resolveView(params.get('view'), readItem(VIEW_STORAGE_KEY));
  const { range, day } = useMemo(() => {
    const values = new URLSearchParams(search);
    return resolveCalendar(
      {
        range: values.get('range'),
        month: values.get('month'),
        year: values.get('year'),
        day: values.get('day'),
      },
      storedKind,
      today,
    );
  }, [search, storedKind, today]);
  const { previous, next } = useMemo(() => rangeNeighbors(range, today), [range, today]);

  const { kind } = range;
  // A posição em números: escolher um dia não pode trocar a identidade de setDay (ele vai para
  // todos os DayCell, que são memorizados). Na faixa do ano só o ano conta
  const anchorYear = range.anchor.year;
  const anchorMonth = kind === 'year' ? 1 : range.anchor.month;

  const move = useCallback(
    (target) => {
      setParams(
        (current) => {
          const values = writeRangeParams(new URLSearchParams(current), kind, target);
          values.delete('day');
          return values;
        },
        { preventScrollReset: true },
      );
    },
    [setParams, kind],
  );

  const setKind = useCallback(
    (value) => {
      writeItem(RANGE_STORAGE_KEY, value);
      const target = switchAnchor(range, value, day, today);
      setParams(
        (current) => {
          const values = writeRangeParams(new URLSearchParams(current), value, target);
          // O dia da URL fica se é o escolhido; hoje sem dia na URL continua implícito
          if (current.get('day') !== day) values.delete('day');
          return values;
        },
        { preventScrollReset: true },
      );
    },
    [setParams, range, day, today],
  );

  const setDay = useCallback(
    (value) => {
      setParams(
        (current) => {
          const values = writeRangeParams(new URLSearchParams(current), kind, {
            year: anchorYear,
            month: anchorMonth,
          });
          values.set('day', value);
          return values;
        },
        { replace: true, preventScrollReset: true },
      );
    },
    [setParams, kind, anchorYear, anchorMonth],
  );

  const setView = useCallback(
    (value) => {
      writeItem(VIEW_STORAGE_KEY, value);
      setParams(
        (current) => {
          // A faixa da tela vai explícita na URL; o dia fica como estava (hoje continua implícito)
          const values = writeRangeParams(new URLSearchParams(current), kind, {
            year: anchorYear,
            month: anchorMonth,
          });
          values.set('view', value);
          return values;
        },
        { preventScrollReset: true },
      );
    },
    [setParams, kind, anchorYear, anchorMonth],
  );

  return { range, day, view, previous, next, move, setKind, setDay, setView };
}
