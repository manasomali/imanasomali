import { Outlet, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMe } from '../../api/auth';
import { useHabit } from '../../api/habits';
import ErrorMessage from '../../components/ErrorMessage';
import HabitNav from '../../components/HabitNav';
import HabitScore from '../../components/HabitScore';
import HabitSwatch from '../../components/HabitSwatch';
import HabitTabs from '../../components/HabitTabs';
import PageTitle from '../../components/PageTitle';
import { parseHabitId } from '../../paths';
import NotFound from '../NotFound';
import styles from './styles.module.css';

// Aba de um hábito (`/habits/:habitId`): carrega o hábito e desenha o cabeçalho (sigla ou nome,
// cor, status, papel, pontuação) e o submenu das seções. Cada seção é uma rota filha e recebe
// `{habit, timeZone}` por useHabitContext (src/hooks/useHabitContext.js)
export default function HabitLayout() {
  const id = parseHabitId(useParams().habitId);
  if (id === null) return <NotFound />;
  // key: trocar de hábito recomeça os estados das seções
  return <HabitScreen key={id} id={id} />;
}

function HabitScreen({ id }) {
  const { t } = useTranslation();
  // RequireSession só desenha as rotas com o usuário carregado
  const timeZone = useMe().data.timezone;
  const query = useHabit(id);
  const habit = query.data;

  if (habit === undefined) {
    return (
      <>
        <PageTitle title={t('pages.home.title')} />
        <HabitTabs />
        {query.isPending ? (
          <p role="status">{t('common.loading')}</p>
        ) : (
          <ErrorMessage error={query.error} onRetry={() => query.refetch()} />
        )}
      </>
    );
  }

  const badges = [];
  if (habit.status !== 'active') badges.push(t(`habit.status.${habit.status}`));
  if (habit.role !== 'owner') badges.push(t(`habit.role.${habit.role}`));
  let readOnly = null;
  if (habit.status === 'archived') readOnly = t('habit.read_only_archived');
  else if (habit.role === 'viewer') readOnly = t('habit.read_only_viewer');

  return (
    <>
      <PageTitle title={habit.label} />
      <HabitTabs />
      <header className={styles.header}>
        <h1 className={styles.title}>
          <HabitSwatch className={styles.swatch} color={habit.color} />
          {habit.label}
        </h1>
        {habit.code && <p className={styles.name}>{habit.name}</p>}
        {badges.length > 0 && (
          <ul className={styles.badges}>
            {badges.map((badge) => (
              <li key={badge}>{badge}</li>
            ))}
          </ul>
        )}
        {readOnly && <p className={styles.notice}>{readOnly}</p>}
        <HabitScore habit={habit} />
      </header>
      <HabitNav habit={habit} />
      <Outlet context={{ habit, timeZone }} />
    </>
  );
}
