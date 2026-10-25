import { useCallback, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { moveDay, yearBounds, yearMonths } from '../../lib/calendar';
import { formatMonth, weekdayNames } from '../../lib/format';
import DayCell from './DayCell';
import styles from './styles.module.css';

// Calendário anual, um bloco por mês (semana começando na segunda). Os dias são botões com foco
// itinerante: só um fica na ordem do Tab e as setas andam entre eles (Home/End: começo e fim do
// mês), então o ano inteiro custa uma parada de Tab. `dayProps(day)` dá as props do DayCell de cada
// dia (ver DayCell; o DayCell é memorizado, então use valores estáveis, como textos e objetos
// memorizados, para um clique não redesenhar o ano inteiro). `initialFocus`: o dia que entra na
// ordem do Tab antes de qualquer foco (ex.: hoje)
export default function YearCalendar({ year, label, initialFocus, dayProps }) {
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const months = useMemo(() => yearMonths(year), [year]);
  const weekdays = useMemo(() => weekdayNames(language), [language]);
  const { first, last } = yearBounds(year);
  const [focused, setFocused] = useState(null);
  const container = useRef(null);

  const inYear = (day) => typeof day === 'string' && day >= first && day <= last;
  let tabStop = first;
  if (inYear(focused)) tabStop = focused;
  else if (inYear(initialFocus)) tabStop = initialFocus;

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
    <div ref={container} className={styles.year} role="group" aria-label={label}>
      {months.map(({ month, days, offset }) => {
        const id = `month-${year}-${month}`;
        return (
          <section key={month} className={styles.month} aria-labelledby={id}>
            <h3 id={id} className={styles.monthName}>
              {formatMonth(month, language)}
            </h3>
            <div className={styles.weekdays} aria-hidden="true">
              {weekdays.map((weekday) => (
                <span key={weekday.long}>{weekday.short}</span>
              ))}
            </div>
            <div className={styles.grid}>
              {offset > 0 && <span className={styles[`offset${offset}`]} aria-hidden="true" />}
              {days.map((day) => (
                <DayCell
                  key={day}
                  {...dayProps(day)}
                  day={day}
                  tabIndex={day === tabStop ? 0 : -1}
                  onKeyDown={onKeyDown}
                  onFocus={onFocus}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
