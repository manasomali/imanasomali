import { useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { MIN_YEAR, parseDay, parseYear, yearOf } from '../lib/calendar';

// Ano e dia escolhidos no calendário, na URL (`?year=2025&day=2025-03-04`), para o voltar do
// navegador e o link compartilhado mostrarem o mesmo. Valor inválido, dia no futuro e ano depois
// do atual são ignorados. `today` é o dia de hoje no fuso da conta.
// - `year`: o da URL, senão o do dia, senão o atual;
// - `day`: o da URL se for desse ano; sem ele, hoje no ano atual e null nos outros anos.
export default function useCalendarParams(today) {
  const [params, setParams] = useSearchParams();
  const maxYear = yearOf(today);

  const parsedDay = parseDay(params.get('day'));
  const validDay =
    parsedDay !== null && parsedDay <= today && yearOf(parsedDay) >= MIN_YEAR ? parsedDay : null;
  const year =
    parseYear(params.get('year'), { max: maxYear }) ?? (validDay ? yearOf(validDay) : maxYear);
  let day = null;
  if (validDay !== null && yearOf(validDay) === year) day = validDay;
  else if (year === maxYear) day = today;

  const setYear = useCallback(
    (value) => {
      setParams((previous) => {
        const next = new URLSearchParams(previous);
        next.set('year', String(value));
        next.delete('day');
        return next;
      }, { preventScrollReset: true });
    },
    [setParams],
  );

  // Escolher um dia não empilha histórico: o voltar do navegador volta de tela, não de dia
  const setDay = useCallback(
    (value) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          next.set('year', String(yearOf(value)));
          next.set('day', value);
          return next;
        },
        { replace: true, preventScrollReset: true },
      );
    },
    [setParams],
  );

  return { year, day, maxYear, setYear, setDay };
}
