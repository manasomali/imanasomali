import { useCallback } from 'react';
import { applyHabitColor } from '../lib/palette';

/**
 * Ref que pinta o elemento com a cor de um hábito (nome da paleta ou "#rrggbb"), pelo CSSOM:
 * `<span ref={useHabitColor(habit.color)} className={styles.swatch} />` e, no CSS,
 * `var(--habit-color, var(--muted))`. O jeito único de aplicar a cor (ver src/lib/palette.js).
 * A ref só muda quando a cor muda; o React a chama de novo e `applyHabitColor` troca tudo.
 */
export default function useHabitColor(color) {
  return useCallback(
    (element) => {
      if (element) applyHabitColor(element, color);
    },
    [color],
  );
}
