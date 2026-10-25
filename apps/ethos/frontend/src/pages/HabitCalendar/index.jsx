import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { canMark } from '../../api/habits';
import { useCreateMark, useDeleteMark, useToggleMark, useYearMarks } from '../../api/marks';
import DayPanel from '../../components/DayPanel';
import ErrorMessage from '../../components/ErrorMessage';
import MarkItem from '../../components/MarkItem';
import YearCalendar from '../../components/YearCalendar';
import YearNav from '../../components/YearNav';
import useCalendarParams from '../../hooks/useCalendarParams';
import useHabitContext from '../../hooks/useHabitContext';
import { MIN_YEAR } from '../../lib/calendar';
import { formatLongDay } from '../../lib/format';
import { markedAtFor, today } from '../../lib/time';
import styles from '../calendar.module.css';

const NO_MARKS = new Map();
const NO_DAY_MARKS = [];

// Calendário de um hábito (rota índice da aba do hábito). Toggle: clicar (ou Enter/Espaço) marca
// ou desmarca o dia e mostra os detalhes no painel. Várias por dia: clicar escolhe o dia, e o
// painel tem o contador, a lista e o "adicionar". Arquivado e viewer só leem
export default function HabitCalendar() {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const { habit, timeZone } = useHabitContext();
  const current = today(timeZone);
  const { year, day, maxYear, setYear, setDay } = useCalendarParams(current);
  const marks = useYearMarks(habit.id, year, timeZone);
  const byDay = marks.data ?? NO_MARKS;
  const loaded = marks.data !== undefined;
  const writable = canMark(habit);
  const { mutate: toggleMark } = useToggleMark(habit, timeZone);
  const { mutate: createMark } = useCreateMark(habit, timeZone);
  const { mutate: deleteMark } = useDeleteMark(habit, timeZone);
  // Erro da última escrita (a mudança otimista já foi desfeita)
  const [error, setError] = useState(null);

  const write = useCallback((mutate, variables) => {
    setError(null);
    mutate(variables, { onError: setError });
  }, []);

  // Marca o dia `value` com `mutate` (toggle ou nova marcação)
  const markDay = useCallback(
    (mutate, value) => {
      let markedAt;
      try {
        markedAt = markedAtFor(value, timeZone);
      } catch {
        // O dia virou futuro (o relógio ou o fuso mudou): nada a marcar
        return;
      }
      write(mutate, { day: value, markedAt });
    },
    [timeZone, write],
  );

  const multi = habit.multi_mark;
  const onActivate = useCallback(
    (value) => {
      setDay(value);
      if (writable && loaded && !multi) markDay(toggleMark, value);
    },
    [setDay, writable, loaded, multi, markDay, toggleMark],
  );

  const dayLabel = (value, count, future) => {
    const date = formatLongDay(value, language);
    if (future) return t('calendar.day_future', { date });
    if (multi) {
      return count === 0
        ? t('calendar.day_no_marks', { date })
        : t('calendar.day_count', { date, count });
    }
    return count > 0 ? t('calendar.day_marked', { date }) : t('calendar.day_unmarked', { date });
  };

  const dayProps = (value) => {
    const marksOfDay = byDay.get(value);
    const count = marksOfDay?.length ?? 0;
    const future = value > current;
    return {
      label: dayLabel(value, count, future),
      future,
      today: value === current,
      selected: value === day,
      pending: marksOfDay?.some((mark) => mark.pending) ?? false,
      color: habit.color,
      marked: count > 0,
      count: multi ? count : 0,
      onActivate,
    };
  };

  const dayMarks = (day && byDay.get(day)) || NO_DAY_MARKS;
  const count = dayMarks.length;
  let state;
  if (!loaded) state = t('common.loading');
  else if (multi) state = count === 0 ? t('day_panel.no_marks') : t('day_panel.count', { count });
  else state = count > 0 ? t('day_panel.marked') : t('day_panel.unmarked');

  return (
    <>
      <YearNav year={year} min={MIN_YEAR} max={maxYear} onChange={setYear} />
      <div className={styles.layout}>
        <div className={styles.panel}>
          <DayPanel day={day}>
            <p className={styles.state}>{state}</p>
            {writable && loaded && (
              <div className={styles.actions}>
                {multi ? (
                  <button
                    type="button"
                    className={styles.primary}
                    onClick={() => markDay(createMark, day)}
                  >
                    {t('day_panel.add')}
                  </button>
                ) : (
                  <button
                    type="button"
                    className={styles.primary}
                    onClick={() => markDay(toggleMark, day)}
                  >
                    {count > 0 ? t('day_panel.unmark') : t('day_panel.mark')}
                  </button>
                )}
              </div>
            )}
            {error && (
              <div className={styles.feedback}>
                <ErrorMessage error={error} />
              </div>
            )}
            {count > 0 && (
              <ul className={styles.list} aria-label={t('day_panel.marks')}>
                {dayMarks.map((mark) => (
                  <MarkItem
                    key={mark.id}
                    habit={habit}
                    mark={mark}
                    timeZone={timeZone}
                    writable={writable}
                    onDelete={
                      writable && multi
                        ? (item) => write(deleteMark, { day, mark: item })
                        : undefined
                    }
                  />
                ))}
              </ul>
            )}
          </DayPanel>
        </div>
        <div className={styles.calendar}>
          {marks.isPending && (
            <p className={styles.status} role="status">
              {t('calendar.loading')}
            </p>
          )}
          {marks.error && !loaded ? (
            <ErrorMessage error={marks.error} onRetry={() => marks.refetch()} />
          ) : (
            <YearCalendar
              year={year}
              label={t('calendar.label', { year })}
              initialFocus={day ?? current}
              dayProps={dayProps}
            />
          )}
        </div>
      </div>
    </>
  );
}
