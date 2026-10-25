import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { canMark } from '../../api/habits';
import { useCreateMark, useToggleMark } from '../../api/marks';
import ErrorMessage from '../../components/ErrorMessage';
import HabitSwatch from '../../components/HabitSwatch';
import { markedAtFor } from '../../lib/time';
import { HABIT_SECTION, habitPath } from '../../paths';
import styles from './styles.module.css';

// Um hábito no painel do dia da aba principal: estado no dia e o atalho de marcar (toggle) ou
// adicionar (várias por dia). Os detalhes ficam na aba do hábito, aberta já no mesmo dia
export default function OverviewRow({ habit, day, marks, loaded, timeZone }) {
  const { t } = useTranslation();
  const toggle = useToggleMark(habit, timeZone);
  const create = useCreateMark(habit, timeZone);
  const mutation = habit.multi_mark ? create : toggle;
  const count = marks?.length ?? 0;

  let state;
  if (!loaded) state = t('common.loading');
  else if (!habit.multi_mark) state = count > 0 ? t('day_panel.marked') : t('day_panel.unmarked');
  else state = count === 0 ? t('day_panel.no_marks') : t('day_panel.count', { count });

  // Texto do botão e o nome acessível, que diz o hábito
  let action = null;
  if (loaded && canMark(habit)) {
    let kind = 'mark';
    if (habit.multi_mark) kind = 'add';
    else if (count > 0) kind = 'unmark';
    action = {
      text: t(`overview.${kind}`),
      label: t(`overview.${kind}_label`, { habit: habit.label }),
    };
  }

  const onClick = () => {
    let markedAt;
    try {
      markedAt = markedAtFor(day, timeZone);
    } catch {
      return;
    }
    mutation.mutate({ day, markedAt });
  };

  return (
    <li className={styles.row}>
      <div className={styles.rowMain}>
        <Link
          to={habitPath(habit.id, HABIT_SECTION.calendar, { day })}
          className={`${styles.habit} user-text`}
          title={habit.name}
        >
          <HabitSwatch className={styles.swatch} color={habit.color} />
          {habit.label}
        </Link>
        <span className={styles.state}>{state}</span>
        {action && (
          <button
            type="button"
            className={styles.action}
            aria-label={action.label}
            onClick={onClick}
          >
            {action.text}
          </button>
        )}
      </div>
      {mutation.error && <ErrorMessage error={mutation.error} />}
    </li>
  );
}
