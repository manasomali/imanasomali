/** Valor gravado (não nulo) e diferente do padrão que uma marcação nova ganharia. */
function differs(value, standard) {
  return value !== null && value !== undefined && value !== standard;
}

/**
 * Se desmarcar perderia algo que a pessoa vê e que não volta ao marcar de novo: a observação, uma
 * duração diferente da padrão do hábito ou um custo por marcação diferente do padrão. Só conta o
 * que está ligado no hábito (o que o painel mostra). A duração e o custo padrão voltam sozinhos
 * numa marcação nova (o backend grava os padrões), e o custo no nível hábito é fixo, então nenhum
 * deles pede confirmação.
 */
export function markHasDetails(habit, mark) {
  if (habit.notes_enabled && typeof mark.note === 'string' && mark.note.trim() !== '') return true;
  if (habit.duration_enabled && differs(mark.duration_minutes, habit.duration_minutes)) return true;
  return (
    habit.cost_enabled === true &&
    habit.cost_level === 'mark' &&
    differs(mark.cost_cents, habit.cost_cents)
  );
}

/** Se alguma marcação do dia (`marks`, pode faltar) tem dados que somem ao desmarcar. */
export function dayHasDetails(habit, marks) {
  return (marks ?? []).some((mark) => markHasDetails(habit, mark));
}
