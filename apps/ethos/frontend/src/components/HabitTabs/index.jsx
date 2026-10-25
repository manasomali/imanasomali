import { NavLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useHabits } from '../../api/habits';
import HabitSwatch from '../HabitSwatch';
import { PATHS, habitPath } from '../../paths';
import styles from './styles.module.css';

// Abas do topo: a principal (todos os hábitos) e uma por hábito ativo ou pausado, com a cor e a
// sigla (ou o nome, cortado com reticências se não couber; o `title` mostra o nome). Os arquivados
// não aparecem aqui (ficam na seção de arquivados da principal). Erro e carregamento da lista
// ficam com a tela, que usa a mesma consulta
export default function HabitTabs() {
  const { t } = useTranslation();
  const habits = useHabits();
  const tabClass = ({ isActive }) => `${styles.tab} ${isActive ? styles.active : ''}`;

  return (
    <nav className={styles.tabs} aria-label={t('habit_tabs.label')}>
      <ul>
        <li>
          <NavLink to={PATHS.home} end className={tabClass}>
            {t('habit_tabs.all')}
          </NavLink>
        </li>
        {habits.data?.map((habit) => (
          <li key={habit.id}>
            <NavLink to={habitPath(habit.id)} className={tabClass} title={habit.name}>
              <HabitSwatch className={styles.swatch} color={habit.color} />
              <span className={`truncate ${styles.label}`}>{habit.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
