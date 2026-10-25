import { useCallback, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { moveDay } from '../../lib/calendar';
import { calendarWeekdayNames, formatMonth, formatMonthYear } from '../../lib/format';
import MonthGrid from './MonthGrid';
import styles from './styles.module.css';

// Os meses de uma faixa (calendarRange em src/lib/calendarRange.js: um mês, 3 meses ou o ano), um
// bloco por mês (MonthGrid; a semana começa no domingo, WEEK_START). O desenho só percorre
// `range.months` e usa `range.first`/`range.last` como limites do foco. Os dias são botões com foco
// itinerante: só um fica na ordem do Tab e as setas andam entre eles (um dia para os lados, uma
// semana para cima e para baixo; Home/End: começo e fim do mês), então a faixa inteira custa uma
// parada de Tab. `dayProps(day)` dá as props do DayCell de cada dia (ver DayCell; o DayCell é
// memorizado, então use valores estáveis, como textos e objetos memorizados, para um clique não
// redesenhar a faixa inteira). `initialFocus`: o dia que entra na ordem do Tab antes de qualquer
// foco (ex.: hoje)
export default function Calendar({ range, label, initialFocus, dayProps }) {
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const weekdays = useMemo(() => calendarWeekdayNames(language), [language]);
  const { first, last, months } = range;
  // Com dois anos na tela (dezembro e janeiro), o nome do mês leva o ano
  const withYear = range.years.length > 1;
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
      const next = moveDay(day, event.key, first, last);
      if (next === null) return;
      event.preventDefault();
      setFocused(next);
      container.current?.querySelector(`[data-day="${next}"]`)?.focus();
    },
    [first, last],
  );

  const onFocus = useCallback((event) => {
    const day = event.target.dataset?.day;
    if (day) setFocused(day);
  }, []);

  return (
    <div
      ref={container}
      className={styles.months}
      data-range={range.kind}
      role="group"
      aria-label={label}
    >
      {months.map((month) => (
        <MonthGrid
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
