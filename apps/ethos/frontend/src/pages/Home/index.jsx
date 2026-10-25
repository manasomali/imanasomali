import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FiPlus } from 'react-icons/fi';
import { useMe } from '../../api/auth';
import { useHabits } from '../../api/habits';
import { useMarksOfHabits } from '../../api/marks';
import Calendar from '../../components/Calendar';
import CalendarNav from '../../components/CalendarNav';
import DayPanel from '../../components/DayPanel';
import ErrorMessage from '../../components/ErrorMessage';
import HabitTabs from '../../components/HabitTabs';
import PageTitle from '../../components/PageTitle';
import useCalendarParams from '../../hooks/useCalendarParams';
import { overviewByDay } from '../../lib/calendar';
import { formatLongDay, formatPeriod } from '../../lib/format';
import { today } from '../../lib/time';
import { PATHS, habitPath } from '../../paths';
import calendar from '../calendar.module.css';
import page from '../page.module.css';
import OverviewRow from './OverviewRow';
import styles from './styles.module.css';

const NO_HABITS = [];

// Aba principal: a faixa do calendário (mês, 3 meses ou ano) com todos os hábitos ativos e pausados. Cada dia mostra até 4 pontos com a
// cor dos hábitos marcados e "+N" para o resto (siglas no hover e no foco). Escolher um dia abre o
// painel com o estado de cada hábito e o atalho de marcar. Os arquivados ficam numa seção à parte
export default function Home() {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const title = t('pages.home.title');
  // RequireSession só desenha as rotas com o usuário carregado
  const timeZone = useMe().data.timezone;
  const current = today(timeZone);
  const { range, day, previous, next, move, setKind, setDay } = useCalendarParams(current);
  const habits = useHabits();
  const list = habits.data ?? NO_HABITS;
  const marks = useMarksOfHabits(list, range.years, timeZone);
  const overview = useMemo(() => overviewByDay(list, marks.byHabit), [list, marks.byHabit]);

  const dayProps = (value) => {
    const future = value > current;
    const dots = overview.get(value);
    const date = formatLongDay(value, language);
    let label;
    if (future) label = t('calendar.day_future', { date });
    else if (dots) label = t('calendar.day_habits', { date, habits: dots.labels });
    else label = t('calendar.day_nothing', { date });
    return {
      label,
      future,
      today: value === current,
      selected: value === day,
      dots,
      onActivate: setDay,
    };
  };

  let content;
  if (habits.data === undefined) {
    content = habits.isPending ? (
      <p role="status">{t('common.loading')}</p>
    ) : (
      <ErrorMessage error={habits.error} onRetry={() => habits.refetch()} />
    );
  } else if (list.length === 0) {
    content = <p className={page.muted}>{t('home.empty')}</p>;
  } else {
    content = (
      <>
        <CalendarNav
          range={range}
          previous={previous}
          next={next}
          onMove={move}
          onKindChange={setKind}
        />
        <div className={calendar.layout}>
          <div className={calendar.panel}>
            <DayPanel day={day}>
              <ul className={calendar.list} aria-label={t('overview.habits')}>
                {list.map((habit) => (
                  <OverviewRow
                    key={habit.id}
                    habit={habit}
                    day={day}
                    marks={marks.byHabit.get(habit.id)?.get(day)}
                    loaded={marks.byHabit.has(habit.id)}
                    timeZone={timeZone}
                  />
                ))}
              </ul>
            </DayPanel>
          </div>
          <div className={calendar.calendar}>
            {marks.pending && (
              <p className={calendar.status} role="status">
                {t('calendar.loading')}
              </p>
            )}
            {marks.error && (
              <div className={calendar.feedback}>
                <ErrorMessage error={marks.error} onRetry={marks.refetch} />
              </div>
            )}
            <Calendar
              range={range}
              label={t('calendar.label', { period: formatPeriod(range, language) })}
              initialFocus={day ?? current}
              dayProps={dayProps}
            />
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <PageTitle title={title} />
      <div className={styles.heading}>
        <h1 className={page.title}>{title}</h1>
        <Link to={PATHS.newHabit} className={styles.newHabit}>
          <FiPlus size={16} aria-hidden="true" />
          {t('home.new_habit')}
        </Link>
      </div>
      <HabitTabs />
      {content}
      <ArchivedHabits />
    </>
  );
}

// Arquivados: só leitura, fora da tela principal. A lista só é buscada ao abrir a seção
function ArchivedHabits() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const archived = useHabits({ archived: true, enabled: open });
  const onToggle = useCallback((event) => setOpen(event.currentTarget.open), []);

  let body = null;
  if (open) {
    if (archived.data === undefined) {
      body = archived.isPending ? (
        <p role="status">{t('common.loading')}</p>
      ) : (
        <ErrorMessage error={archived.error} onRetry={() => archived.refetch()} />
      );
    } else if (archived.data.length === 0) {
      body = <p className={page.muted}>{t('home.archived.empty')}</p>;
    } else {
      body = (
        <ul className={styles.archivedList}>
          {archived.data.map((habit) => (
            <li key={habit.id}>
              <Link to={habitPath(habit.id)} className={`${styles.habit} user-text`} title={habit.name}>
                <span className={styles.swatch} data-habit-color={habit.color} aria-hidden="true" />
                {habit.label}
              </Link>
            </li>
          ))}
        </ul>
      );
    }
  }

  return (
    <details className={styles.archived} onToggle={onToggle}>
      <summary>{t('home.archived.title')}</summary>
      {body}
    </details>
  );
}
