import DayCell from './DayCell';
import styles from './styles.module.css';

// Um mês na visão em colunas: o nome e os dias de cima para baixo, cada um com o número, a
// abreviação do dia da semana e a marcação (o mesmo DayCell da grade). Uma linha separa as semanas
// (antes de cada WEEK_START); os dias têm altura fixa, então o mesmo dia fica na mesma altura em
// todas as colunas. `month`: `{year, month, days, offset}` de calendarMonth; `title`: o
// nome do mês; `weekdays`: calendarWeekdayNames (na ordem das colunas da grade, então o dia
// `index` do mês cai em `weekdays[(offset + index) % 7]`). O foco itinerante e as teclas ficam com
// quem desenha os meses (Calendar), como no MonthGrid
export default function MonthColumn({ month, title, weekdays, tabStop, dayProps, onKeyDown, onFocus }) {
  const { year, days, offset } = month;
  const id = `month-${year}-${month.month}`;
  return (
    <section className={styles.column} aria-labelledby={id}>
      <h3 id={id} className={styles.monthName}>
        {title}
      </h3>
      <div className={styles.columnDays}>
        {days.map((day, index) => {
          const column = (offset + index) % 7;
          return (
            <DayCell
              key={day}
              {...dayProps(day)}
              day={day}
              weekday={weekdays[column].abbr}
              weekStart={index > 0 && column === 0}
              tabIndex={day === tabStop ? 0 : -1}
              onKeyDown={onKeyDown}
              onFocus={onFocus}
            />
          );
        })}
      </div>
    </section>
  );
}
