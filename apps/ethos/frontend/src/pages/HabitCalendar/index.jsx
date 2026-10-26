import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { canMark } from '../../api/habits';
import { useCreateMark, useDeleteMark, useMarks, useToggleMark } from '../../api/marks';
import Calendar from '../../components/Calendar';
import CalendarNav from '../../components/CalendarNav';
import ConfirmUnmark from '../../components/ConfirmUnmark';
import DayPanel from '../../components/DayPanel';
import ErrorMessage from '../../components/ErrorMessage';
import MarkItem from '../../components/MarkItem';
import useCalendarParams from '../../hooks/useCalendarParams';
import useHabitContext from '../../hooks/useHabitContext';
import { formatLongDay, formatPeriod } from '../../lib/format';
import { dayHasDetails } from '../../lib/markDetails';
import { markedAtFor, today } from '../../lib/time';
import styles from '../calendar.module.css';

const NO_MARKS = new Map();
const NO_DAY_MARKS = [];

// Calendário de um hábito (rota índice da aba do hábito). Clicar num dia (ou Enter/Espaço) só o
// escolhe e mostra os detalhes no painel, para editar sem desmarcar sem querer (ETH-54). O foco
// fica no calendário (as setas continuam andando); o painel vem antes dele no HTML, então
// Shift+Tab chega aos botões. Toggle: o painel marca e desmarca o dia; desmarcar um dia com
// observação, duração ou custo (dayHasDetails) pede confirmação. Várias por dia: o painel tem o
// contador, a lista e o "adicionar". O duplo clique num dia faz a ação principal do painel
// (primaryAction), pelo mesmo caminho do botão, confirmação inclusive (ETH-55). Arquivado e
// viewer só leem
export default function HabitCalendar() {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const { habit, timeZone } = useHabitContext();
  const current = today(timeZone);
  const { range, day, view, previous, next, move, setKind, setDay, setView } =
    useCalendarParams(current);
  const marks = useMarks(habit.id, range.years, timeZone);
  const byDay = marks.data ?? NO_MARKS;
  const loaded = marks.data !== undefined;
  const writable = canMark(habit);
  const { mutate: toggleMark } = useToggleMark(habit, timeZone);
  const { mutate: createMark } = useCreateMark(habit, timeZone);
  const { mutate: deleteMark } = useDeleteMark(habit, timeZone);
  // Erro da última escrita (a mudança otimista já foi desfeita)
  const [error, setError] = useState(null);
  // Dia em que "desmarcar" espera a confirmação (trocar de dia a esquece)
  const [confirmDay, setConfirmDay] = useState(null);
  // O dia escolhido no último desenho, para saber quando ele muda
  const [shownDay, setShownDay] = useState(day);
  const toggleButton = useRef(null);

  const write = (mutate, variables) => {
    setError(null);
    mutate(variables, { onError: setError });
  };

  // Marca o dia `value` com `mutate` (toggle ou nova marcação)
  const markDay = (mutate, value) => {
    let markedAt;
    try {
      markedAt = markedAtFor(value, timeZone);
    } catch {
      // O dia virou futuro (o relógio ou o fuso mudou): nada a marcar
      return;
    }
    write(mutate, { day: value, markedAt });
  };

  const multi = habit.multi_mark;

  const dayMarks = (day && byDay.get(day)) || NO_DAY_MARKS;
  const count = dayMarks.length;
  let state;
  if (!loaded) state = t('common.loading');
  else if (multi) state = count === 0 ? t('day_panel.no_marks') : t('day_panel.count', { count });
  else state = count > 0 ? t('day_panel.marked') : t('day_panel.unmarked');

  // Se desmarcar o dia `value` (toggle) apagaria observação, duração ou custo
  const askToUnmark = (value) =>
    writable && loaded && !multi && dayHasDetails(habit, byDay.get(value));

  // A confirmação some quando o dia escolhido passa a ser outro ou quando o dia dela não tem mais o
  // que perder, e não volta sozinha depois (voltaria tirando o foco do calendário). Ela vale para
  // `confirmDay`, que pode ainda não ser o escolhido: no duplo clique, a URL (uma transição do
  // router) pode trocar o dia depois de a confirmação ser pedida, e então ela espera o dia chegar
  let keptConfirm = confirmDay;
  if (shownDay !== day) {
    setShownDay(day);
    if (keptConfirm !== day) keptConfirm = null;
  }
  if (keptConfirm !== null && !askToUnmark(keptConfirm)) keptConfirm = null;
  if (keptConfirm !== confirmDay) setConfirmDay(keptConfirm);
  const confirming = keptConfirm !== null && keptConfirm === day;

  // Ação principal do painel no dia `value`: marca ou desmarca (toggle, com a confirmação quando
  // desmarcar perderia detalhes) ou adiciona uma marcação (várias por dia). O botão do painel a faz
  // no dia escolhido; o duplo clique, no dia clicado
  const primaryAction = (value) => {
    if (multi) markDay(createMark, value);
    else if (askToUnmark(value)) setConfirmDay(value);
    else markDay(toggleMark, value);
  };

  // O DayCell é memorizado: o duplo clique recebe uma função estável, que chama a primaryAction do
  // último desenho
  const latestAction = useRef(primaryAction);
  useLayoutEffect(() => {
    latestAction.current = primaryAction;
  });
  const onActivate = useCallback((value) => latestAction.current(value), []);

  const dayLabel = (value, count, future) => {
    const long = formatLongDay(value, language);
    const date = value === day ? t('calendar.day_selected', { date: long }) : long;
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
      onSelect: setDay,
      // Duplo clique: só quem pode marcar, com as marcações carregadas (o DayCell ignora o futuro)
      onActivate: writable && loaded ? onActivate : undefined,
    };
  };

  // Fim da confirmação: desmarca (ou não) e devolve o foco ao botão, que continua na tela
  const closeConfirm = (confirmed) => {
    setConfirmDay(null);
    if (confirmed) markDay(toggleMark, day);
    toggleButton.current?.focus();
  };

  return (
    <>
      <CalendarNav
        range={range}
        view={view}
        previous={previous}
        next={next}
        onMove={move}
        onKindChange={setKind}
        onViewChange={setView}
      />
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
                    onClick={() => primaryAction(day)}
                  >
                    {t('day_panel.add')}
                  </button>
                ) : (
                  <button
                    ref={toggleButton}
                    type="button"
                    className={styles.primary}
                    onClick={() => primaryAction(day)}
                  >
                    {count > 0 ? t('day_panel.unmark') : t('day_panel.mark')}
                  </button>
                )}
              </div>
            )}
            {confirming && (
              <ConfirmUnmark onConfirm={() => closeConfirm(true)} onCancel={() => closeConfirm(false)} />
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
            <ErrorMessage error={marks.error} onRetry={marks.refetch} />
          ) : (
            <Calendar
              range={range}
              view={view}
              label={t('calendar.label', { period: formatPeriod(range, language) })}
              initialFocus={day ?? current}
              dayProps={dayProps}
            />
          )}
        </div>
      </div>
    </>
  );
}
