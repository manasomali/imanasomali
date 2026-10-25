import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { canMark } from '../../api/habits';
import { useCreateMark, useToggleMark } from '../../api/marks';
import ConfirmUnmark from '../../components/ConfirmUnmark';
import ErrorMessage from '../../components/ErrorMessage';
import HabitSwatch from '../../components/HabitSwatch';
import { dayHasDetails } from '../../lib/markDetails';
import { markedAtFor } from '../../lib/time';
import { HABIT_SECTION, habitPath } from '../../paths';
import styles from './styles.module.css';

// Um hábito no painel do dia da aba principal: estado no dia e o atalho de marcar ou desmarcar
// (toggle) ou adicionar (várias por dia). Desmarcar um dia com observação, duração ou custo pede
// confirmação, como na aba do hábito. Os detalhes ficam na aba do hábito, aberta já no mesmo dia
export default function OverviewRow({ habit, day, marks, loaded, timeZone }) {
  const { t } = useTranslation();
  const toggle = useToggleMark(habit, timeZone);
  const create = useCreateMark(habit, timeZone);
  const mutation = habit.multi_mark ? create : toggle;
  const count = marks?.length ?? 0;
  // Dia em que "desmarcar" espera a confirmação (trocar de dia a esquece)
  const [confirmDay, setConfirmDay] = useState(null);
  const button = useRef(null);

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

  const askToUnmark = action !== null && !habit.multi_mark && count > 0 && dayHasDetails(habit, marks);
  // Outro dia (ou o dia sem o que perder) esquece a confirmação, que não volta sozinha depois
  // (voltaria tirando o foco do calendário)
  if (confirmDay !== null && (confirmDay !== day || !askToUnmark)) setConfirmDay(null);
  const confirming = askToUnmark && confirmDay === day;

  const write = () => {
    let markedAt;
    try {
      markedAt = markedAtFor(day, timeZone);
    } catch {
      return;
    }
    mutation.mutate({ day, markedAt });
  };

  const onClick = () => {
    if (askToUnmark) setConfirmDay(day);
    else write();
  };

  // Fim da confirmação: desmarca (ou não) e devolve o foco ao botão, que continua na tela
  const closeConfirm = (confirmed) => {
    setConfirmDay(null);
    if (confirmed) write();
    button.current?.focus();
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
            ref={button}
            type="button"
            className={styles.action}
            aria-label={action.label}
            onClick={onClick}
          >
            {action.text}
          </button>
        )}
      </div>
      {confirming && (
        <ConfirmUnmark
          confirmLabel={t('overview.confirm_unmark_label', { habit: habit.label })}
          onConfirm={() => closeConfirm(true)}
          onCancel={() => closeConfirm(false)}
        />
      )}
      {mutation.error && <ErrorMessage error={mutation.error} />}
    </li>
  );
}
