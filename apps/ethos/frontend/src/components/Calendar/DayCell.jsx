import { memo } from 'react';
import styles from './styles.module.css';

// Um dia do calendário. Memorizado: com props iguais não redesenha, então um clique só redesenha
// os dias que mudaram. Props:
// - `day` ("AAAA-MM-DD"), `label` (aria-label com a data e o estado), `tabIndex` (foco itinerante);
// - `future`: dia depois de hoje, desabilitado (aria-disabled, para continuar focável e lido);
// - `today`, `selected`, `pending` (escrita a caminho);
// - `color` (cor do hábito), `marked` e `count` (várias por dia): aba do hábito;
// - `dots` (`{shown: [{id, color}], extra, labels}`, memorizado): aba principal, até 4 pontos,
//   "+N" e as siglas no hover e no foco;
// - `onActivate(day)`: clique, Enter ou Espaço (o botão nativo já trata as duas teclas);
// - `onKeyDown` e `onFocus`: do Calendar (setas e foco itinerante).
function DayCell({
  day,
  label,
  tabIndex,
  future = false,
  today = false,
  selected = false,
  pending = false,
  color,
  marked = false,
  count = 0,
  dots,
  onActivate,
  onKeyDown,
  onFocus,
}) {
  const onClick = () => {
    if (!future) onActivate(day);
  };

  return (
    <button
      type="button"
      data-day={day}
      data-habit-color={color}
      className={styles.day}
      tabIndex={tabIndex}
      aria-label={label}
      aria-disabled={future || undefined}
      aria-current={today ? 'date' : undefined}
      data-marked={marked || undefined}
      data-selected={selected || undefined}
      data-pending={pending || undefined}
      onClick={onClick}
      onKeyDown={onKeyDown}
      onFocus={onFocus}
    >
      <span className={styles.number} aria-hidden="true">
        {Number(day.slice(8))}
      </span>
      {count > 1 && (
        <span className={styles.count} aria-hidden="true">
          {count}
        </span>
      )}
      {dots && (
        <>
          <span className={styles.dots} aria-hidden="true">
            {dots.shown.map((habit) => (
              <span key={habit.id} className={styles.dot} data-habit-color={habit.color} />
            ))}
            {dots.extra > 0 && <span className={styles.extra}>+{dots.extra}</span>}
          </span>
          <span className={styles.tooltip} aria-hidden="true">
            {dots.labels}
          </span>
        </>
      )}
    </button>
  );
}

export default memo(DayCell);
