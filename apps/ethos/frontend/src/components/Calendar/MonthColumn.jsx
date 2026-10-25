import DayCell from './DayCell';
import styles from './styles.module.css';

// Um mês na visão em colunas: o nome e os dias de cima para baixo, o mesmo DayCell da grade, do
// mesmo tamanho (--day-size em styles.module.css) e sem o dia da semana (o aria-label do dia já tem
// a data completa). Uma linha separa as semanas (antes de cada WEEK_START); os dias são todos do
// mesmo tamanho, então o mesmo dia fica na mesma altura em todas as colunas. A coluna tem a largura
// de um dia: o nome do mês aparece abreviado (`shortName`, e o ano embaixo com `withYear`), e o
// título completo (`title`) fica para os leitores de tela. `month`: `{year, month, days, offset}` de
// calendarMonth (o dia `index` cai na coluna `(offset + index) % 7` da grade). O foco itinerante e
// as teclas ficam com quem desenha os meses (Calendar), como no MonthGrid
export default function MonthColumn({
  month,
  title,
  shortName,
  withYear,
  tabStop,
  dayProps,
  onKeyDown,
  onFocus,
}) {
  const { year, days, offset } = month;
  const id = `month-${year}-${month.month}`;
  return (
    <section className={styles.column} aria-labelledby={id}>
      <h3 id={id} className={styles.monthName}>
        <span className="visually-hidden">{title}</span>
        <span aria-hidden="true">{shortName}</span>
        {withYear && (
          <span className={styles.monthYear} aria-hidden="true">
            {year}
          </span>
        )}
      </h3>
      <div className={styles.columnDays}>
        {days.map((day, index) => (
          <DayCell
            key={day}
            {...dayProps(day)}
            day={day}
            weekStart={index > 0 && (offset + index) % 7 === 0}
            tabIndex={day === tabStop ? 0 : -1}
            onKeyDown={onKeyDown}
            onFocus={onFocus}
          />
        ))}
      </div>
    </section>
  );
}
