import { Link, NavLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import { HABIT_SECTION, habitPath, reportPath } from '../../paths';
import styles from './styles.module.css';

// Submenu da aba de um hábito. Cada tela nova do hábito (ETH-33 configuração, ETH-34
// compartilhamento, ETH-35 alertas) entra aqui com o caminho de HABIT_SECTION e a regra de quem a
// vê (`visible(habit)`; ex.: configuração só para `habit.role === 'owner'`), além da rota filha do
// HabitLayout em src/routes.jsx
const HABIT_NAV = Object.freeze([
  { section: HABIT_SECTION.calendar, i18nKey: 'habit.sections.calendar', visible: () => true },
  // A tela também volta para o calendário se quem abre não é o dono (pages/HabitSettings)
  {
    section: HABIT_SECTION.settings,
    i18nKey: 'habit.sections.settings',
    visible: (habit) => habit.role === 'owner',
  },
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
        {/* O relatório é uma rota de topo (vários hábitos): este atalho já vem com o hábito */}
        <li>
          <Link to={reportPath({ habitIds: [habit.id] })} className={styles.link}>
            {t('habit.sections.report')}
          </Link>
        </li>
      </ul>
    </nav>
  );
}
