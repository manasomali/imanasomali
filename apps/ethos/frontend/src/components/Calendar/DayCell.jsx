import { memo } from 'react';
import useHabitColor from '../../hooks/useHabitColor';
import HabitSwatch from '../HabitSwatch';
import styles from './styles.module.css';

// Um dia do calendário. Memorizado: com props iguais não redesenha, então um clique só redesenha
// os dias que mudaram. Props:
// - `day` ("AAAA-MM-DD"), `label` (aria-label com a data e o estado), `tabIndex` (foco itinerante);
// - `weekStart` (primeiro dia de uma semana depois do dia 1): só na visão em colunas, onde uma
//   linha separa as semanas;
// - `future`: dia depois de hoje, desabilitado (aria-disabled, para continuar focável e lido);
// - `today`, `selected`, `pending` (escrita a caminho);
// - `color` (cor do hábito: nome da paleta ou "#rrggbb"), `marked` e `count` (várias por dia): aba
//   do hábito. O número do dia marcado usa o texto que contrasta com a cor (src/lib/palette.js);
// - `dots` (`{shown: [{id, color}], extra, labels}`, memorizado): aba principal, até 4 pontos,
//   "+N" e as siglas no hover e no foco;
// - `onSelect(day)`: clique, Enter ou Espaço (o botão nativo já trata as duas teclas) só escolhem o
//   dia, nunca marcam nem desmarcam: isso fica nos botões do painel do dia (ETH-54);
// - `onKeyDown` e `onFocus`: do Calendar (setas e foco itinerante).
function DayCell({
  day,
  label,
  tabIndex,
  weekStart = false,
  future = false,
  today = false,
  selected = false,
  pending = false,
  color,
  marked = false,
  count = 0,
  dots,
  onSelect,
  onKeyDown,
  onFocus,
}) {
  const colorRef = useHabitColor(color);
  const onClick = () => {
    if (!future) onSelect(day);
  };

  return (
    <button
      type="button"
      data-day={day}
      ref={colorRef}
      className={styles.day}
      tabIndex={tabIndex}
      aria-label={label}
      aria-disabled={future || undefined}
      aria-current={today ? 'date' : undefined}
      data-marked={marked || undefined}
      data-selected={selected || undefined}
      data-pending={pending || undefined}
      data-week-start={weekStart || undefined}
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
              <HabitSwatch key={habit.id} className={styles.dot} color={habit.color} />
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
