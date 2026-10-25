import useHabitColor from '../../hooks/useHabitColor';

// Bolinha (ou qualquer marca decorativa) com a cor de um hábito: nome da paleta ou "#rrggbb".
// O tamanho e a forma vêm do `className` de quem usa, com `background: var(--habit-color,
// var(--muted))`. Decorativa: escondida do leitor de tela (o nome do hábito está ao lado)
export default function HabitSwatch({ color, className }) {
  const colorRef = useHabitColor(color);
  return <span ref={colorRef} className={className} aria-hidden="true" />;
}
