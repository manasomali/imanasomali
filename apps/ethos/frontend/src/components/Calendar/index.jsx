import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { moveColumnDay, moveDay } from '../../lib/calendar';
import { DEFAULT_CALENDAR_VIEW } from '../../lib/calendarView';
import { calendarWeekdayNames, formatMonth, formatMonthYear } from '../../lib/format';
import MonthColumn from './MonthColumn';
import MonthGrid from './MonthGrid';
import styles from './styles.module.css';

// Os meses de uma faixa (calendarRange em src/lib/calendarRange.js: um mês, 3 meses ou o ano) na
// visão `view` (src/lib/calendarView.js): na grade, um bloco por mês em semanas (MonthGrid; a
// semana começa no domingo, WEEK_START); nas colunas, uma coluna por mês com os dias de cima para
// baixo (MonthColumn), lado a lado, rolando na horizontal dentro do próprio calendário quando não
// cabem. O desenho só percorre `range.months` e usa `range.first`/`range.last` como limites do
// foco. Os dias são botões com foco itinerante: só um fica na ordem do Tab e as setas andam entre
// eles, então a faixa inteira custa uma parada de Tab. Na grade, um dia para os lados e uma semana
// para cima e para baixo (moveDay); nas colunas, um dia para cima e para baixo e o mesmo dia no mês
// vizinho para os lados (moveColumnDay); Home/End: começo e fim do mês nas duas. `dayProps(day)` dá
// as props do DayCell de cada dia (ver DayCell; o DayCell é memorizado, então use valores
// estáveis, como textos e objetos memorizados, para um clique não redesenhar a faixa inteira).
// `initialFocus`: o dia que entra na ordem do Tab antes de qualquer foco (ex.: hoje)
export default function Calendar({
  range,
  view = DEFAULT_CALENDAR_VIEW,
  label,
  initialFocus,
  dayProps,
}) {
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const weekdays = useMemo(() => calendarWeekdayNames(language), [language]);
  const { first, last, months } = range;
  // Com dois anos na tela (dezembro e janeiro), o nome do mês leva o ano
  const withYear = range.years.length > 1;
  const columns = view === 'columns';
  const [focused, setFocused] = useState(null);
  const container = useRef(null);

  const inRange = (day) => typeof day === 'string' && day >= first && day <= last;
  let tabStop = first;
  if (inRange(focused)) tabStop = focused;
  else if (inRange(initialFocus)) tabStop = initialFocus;

  // Teclas e foco dos botões dos dias (data-day)
  const onKeyDown = useCallback(
    (event) => {
      const day = event.target.dataset?.day;
      if (!day) return;
      const next = (columns ? moveColumnDay : moveDay)(day, event.key, first, last);
      if (next === null) return;
      event.preventDefault();
      setFocused(next);
      const target = container.current?.querySelector(`[data-day="${next}"]`);
      if (!target) return;
      // O navegador só rola no foco quando o dia está todo fora da tela; meio escondido na rolagem
      // das colunas, ele ficaria cortado. `nearest`: rola o mínimo, só se precisar (o jsdom não
      // tem scrollIntoView)
      target.focus({ preventScroll: true });
      target.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    },
    [first, last, columns],
  );

  // Nas colunas, ao abrir a visão ou trocar de faixa, a coluna do dia na ordem do Tab (o escolhido,
  // senão hoje) aparece na rolagem do calendário. Só na horizontal: a página não rola. Depois disso,
  // o foco nos dias leva a rolagem junto
  useEffect(() => {
    const element = container.current;
    if (!columns || !element) return;
    const column = element.querySelector('[data-day][tabindex="0"]')?.closest('section');
    if (!column) return;
    const start = column.offsetLeft;
    const end = start + column.offsetWidth;
    if (start < element.scrollLeft) element.scrollLeft = start;
    else if (end > element.scrollLeft + element.clientWidth) {
      element.scrollLeft = end - element.clientWidth;
    }
  }, [columns, first]);

  const Month = columns ? MonthColumn : MonthGrid;

  const onFocus = useCallback((event) => {
    const day = event.target.dataset?.day;
    if (day) setFocused(day);
  }, []);

  return (
    <div
      ref={container}
      className={columns ? styles.columns : styles.months}
      data-range={range.kind}
      data-view={view}
      role="group"
      aria-label={label}
    >
      {months.map((month) => (
        <Month
          key={`${month.year}-${month.month}`}
          month={month}
          title={
            withYear
              ? formatMonthYear(month.year, month.month, language)
              : formatMonth(month.month, language)
          }
          weekdays={weekdays}
          tabStop={tabStop}
          dayProps={dayProps}
          onKeyDown={onKeyDown}
          onFocus={onFocus}
        />
      ))}
    </div>
  );
}
