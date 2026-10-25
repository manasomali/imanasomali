import { useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMembers } from '../../api/sharing';
import { parseUserId } from '../../lib/admin';
import {
  CUSTOM_SELECTION,
  EMPTY_HISTORY_FILTERS,
  EVENT_GROUPS,
  MAX_HISTORY_DAY,
  MIN_HISTORY_DAY,
  authorOptions,
  eventSelection,
  groupSelection,
  historySearch,
  isInvertedRange,
  selectionEvents,
} from '../../lib/history';
import { parseHabitId } from '../../paths';
import styles from './styles.module.css';

const NONE = [];

function habitName(habit) {
  return habit.code ? `${habit.label} (${habit.name})` : habit.label;
}

// Filtros do histórico. Edita um rascunho e só aplica (muda a URL) no "Filtrar", para cada data
// digitada não virar uma busca. Quando a URL muda por fora (voltar do navegador, link), o rascunho
// volta a ser o da URL; o formulário não é recriado, então o foco fica onde estava.
// Pessoas do filtro de autor: você, o dono e os membros do hábito escolhido
// (GET /habits/{id}/members) e quem já apareceu como autor no histórico (`seenAuthors`); a pessoa
// que veio pela URL e a tela não conhece aparece como "pessoa nº <id>"
export default function Filters({ initial, me, habits, archived, seenAuthors, onApply }) {
  const { t } = useTranslation();
  const id = useId();
  const [draft, setDraft] = useState(initial);
  const [rangeError, setRangeError] = useState(() => isInvertedRange(initial));
  const initialKey = historySearch(initial).toString();
  const [appliedKey, setAppliedKey] = useState(initialKey);
  if (initialKey !== appliedKey) {
    setAppliedKey(initialKey);
    setDraft(initial);
    setRangeError(isInvertedRange(initial));
  }
  const toRef = useRef(null);
  const members = useMembers(draft.habitId, { enabled: draft.habitId !== null }).data?.members ?? NONE;
  const people = authorOptions(
    me,
    [members.map((member) => member.user), seenAuthors],
    draft.userId,
  );
  const known = [...habits, ...archived].some((habit) => habit.id === draft.habitId);
  const selection = eventSelection(draft.events);

  const set = (name, value) => setDraft((current) => ({ ...current, [name]: value }));

  const changeDate = (name) => (event) => {
    setRangeError(false);
    set(name, event.target.value);
  };

  const submit = (event) => {
    event.preventDefault();
    if (isInvertedRange(draft)) {
      setRangeError(true);
      toRef.current?.focus();
      return;
    }
    onApply(draft);
  };

  // Limpa também o rascunho: com a URL já sem filtros, nada muda nela e o formulário não recomeça
  const clear = () => {
    setDraft(EMPTY_HISTORY_FILTERS);
    setRangeError(false);
    onApply(EMPTY_HISTORY_FILTERS);
  };

  const personLabel = (person) => {
    if (person.email === null) return t('history.person', { id: person.id });
    return person.id === me.id ? t('history.filters.you', { email: person.email }) : person.email;
  };

  return (
    <form className={styles.form} aria-label={t('history.filters.label')} noValidate onSubmit={submit}>
      <div className={styles.fields}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${id}-habit`}>
            {t('history.filters.habit')}
          </label>
          <select
            id={`${id}-habit`}
            className={styles.input}
            value={draft.habitId ?? ''}
            onChange={(event) => set('habitId', parseHabitId(event.target.value))}
          >
            <option value="">{t('history.filters.all_habits')}</option>
            {draft.habitId !== null && !known && (
              <option value={draft.habitId}>{t('history.filters.habit_unknown', { id: draft.habitId })}</option>
            )}
            {habits.map((habit) => (
              <option key={habit.id} value={habit.id}>
                {habitName(habit)}
              </option>
            ))}
            {archived.length > 0 && (
              <optgroup label={t('history.filters.archived')}>
                {archived.map((habit) => (
                  <option key={habit.id} value={habit.id}>
                    {habitName(habit)}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${id}-author`}>
            {t('history.filters.author')}
          </label>
          <select
            id={`${id}-author`}
            className={styles.input}
            value={draft.userId ?? ''}
            aria-describedby={`${id}-people`}
            onChange={(event) => set('userId', parseUserId(event.target.value))}
          >
            <option value="">{t('history.filters.all_people')}</option>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {personLabel(person)}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${id}-event`}>
            {t('history.filters.event')}
          </label>
          <select
            id={`${id}-event`}
            className={styles.input}
            value={selection}
            onChange={(event) => set('events', selectionEvents(event.target.value, draft.events))}
          >
            <option value="">{t('history.filters.all_events')}</option>
            {selection === CUSTOM_SELECTION && (
              <option value={CUSTOM_SELECTION}>
                {t('history.filters.custom_events', { count: draft.events.length })}
              </option>
            )}
            {Object.entries(EVENT_GROUPS).map(([name, events]) => (
              <optgroup key={name} label={t(`history.groups.${name}`)}>
                <option value={groupSelection(name)}>{t(`history.filters.group_all.${name}`)}</option>
                {events.map((event) => (
                  <option key={event} value={event}>
                    {t(`history.event_names.${event}`)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${id}-from`}>
            {t('history.filters.from')}
          </label>
          <input
            id={`${id}-from`}
            className={styles.input}
            type="date"
            min={MIN_HISTORY_DAY}
            max={MAX_HISTORY_DAY}
            value={draft.from}
            aria-describedby={`${id}-dates`}
            onChange={changeDate('from')}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${id}-to`}>
            {t('history.filters.to')}
          </label>
          <input
            ref={toRef}
            id={`${id}-to`}
            className={styles.input}
            type="date"
            min={MIN_HISTORY_DAY}
            max={MAX_HISTORY_DAY}
            value={draft.to}
            aria-invalid={rangeError}
            aria-describedby={rangeError ? `${id}-range ${id}-dates` : `${id}-dates`}
            onChange={changeDate('to')}
          />
          {rangeError && (
            <p id={`${id}-range`} className={styles.fieldError}>
              {t('history.filters.invalid_range')}
            </p>
          )}
        </div>
      </div>

      <div className={styles.hints}>
        <p id={`${id}-dates`} className={styles.hint}>
          {t('history.filters.dates_hint', { timezone: me.timezone })}
        </p>
        <p id={`${id}-people`} className={styles.hint}>
          {t('history.filters.people_hint')}
        </p>
      </div>

      <div className={styles.buttons}>
        <button type="submit" className={styles.primary}>
          {t('history.filters.apply')}
        </button>
        <button type="button" className={styles.button} onClick={clear}>
          {t('history.filters.clear')}
        </button>
      </div>
    </form>
  );
}
