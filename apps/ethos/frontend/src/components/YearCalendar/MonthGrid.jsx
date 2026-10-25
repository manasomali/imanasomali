import DayCell from './DayCell';
import styles from './styles.module.css';

// Um mês do calendário: nome, cabeçalho dos dias da semana e a grade de 7 colunas, que começa em
// WEEK_START (domingo; src/lib/calendar.js). `month`: `{year, month, days, offset}` de
// calendarMonth; `title`: o nome do mês; `weekdays`: calendarWeekdayNames (na ordem das colunas).
// O foco itinerante e as teclas ficam com quem desenha os meses (YearCalendar): `tabStop` é o dia
// que entra na ordem do Tab, `dayProps`, `onKeyDown` e `onFocus` vão para cada DayCell
export default function MonthGrid({ month, title, weekdays, tabStop, dayProps, onKeyDown, onFocus }) {
  const { year, days, offset } = month;
  const id = `month-${year}-${month.month}`;
  return (
    <section className={styles.month} aria-labelledby={id}>
      <h3 id={id} className={styles.monthName}>
        {title}
      </h3>
      <div className={styles.weekdays} aria-hidden="true">
        {weekdays.map((weekday) => (
          <span key={weekday.long}>{weekday.short}</span>
        ))}
      </div>
      <div className={styles.grid}>
        {offset > 0 && (
          <span className={styles[`offset${offset}`]} data-offset={offset} aria-hidden="true" />
        )}
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
}
