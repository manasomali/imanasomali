// Paleta fixa das cores dos hábitos. A API guarda só o nome (HabitColor em app/models.py); os
// valores de cada tema ficam em src/styles/palette.css como --habit-<nome>. Para pintar um
// elemento, use data-habit-color={habit.color} e, no CSS, var(--habit-color): nada de style
// inline, por causa da CSP

export const HABIT_COLORS = Object.freeze([
  'red',
  'orange',
  'amber',
  'yellow',
  'lime',
  'green',
  'teal',
  'cyan',
  'blue',
  'indigo',
  'violet',
  'pink',
]);

export function isHabitColor(name) {
  return HABIT_COLORS.includes(name);
}
