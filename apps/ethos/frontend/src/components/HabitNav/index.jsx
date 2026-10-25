import { NavLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import { HABIT_SECTION, habitPath } from '../../paths';
import styles from './styles.module.css';

// Submenu da aba de um hábito. Cada tela nova do hábito (ETH-33 configuração, ETH-34
// compartilhamento, ETH-35 alertas) entra aqui com o caminho de HABIT_SECTION e a regra de quem a
// vê (`visible(habit)`; ex.: configuração só para `habit.role === 'owner'`), além da rota filha do
// HabitLayout em src/routes.jsx
const HABIT_NAV = Object.freeze([
  { section: HABIT_SECTION.calendar, i18nKey: 'habit.sections.calendar', visible: () => true },
]);

export default function HabitNav({ habit }) {
  const { t } = useTranslation();
  const linkClass = ({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`;

  return (
    <nav className={styles.nav} aria-label={t('habit.sections.label')}>
      <ul>
        {HABIT_NAV.filter((item) => item.visible(habit)).map((item) => (
          <li key={item.section}>
            <NavLink to={habitPath(habit.id, item.section)} end className={linkClass}>
              {t(item.i18nKey)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
