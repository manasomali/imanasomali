import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ErrorMessage from '../../components/ErrorMessage';
import HabitSwatch from '../../components/HabitSwatch';
import { PERIOD_PRESETS, checkPeriod, presetPeriod } from '../../lib/export/period';
import styles from './styles.module.css';

// Período e hábitos do relatório. Só vão para a URL (e para a API) no envio: digitar uma data
// não busca nada a cada tecla. Sem nenhum hábito escolhido, ou com o período inválido, não envia
export default function ReportForm({
  params,
  today,
  timeZone,
  habits,
  habitsLoaded,
  habitsError,
  onRetryHabits,
  onSubmit,
}) {
  const { t } = useTranslation();
  const id = useId();
  const [from, setFrom] = useState(params.from);
  const [to, setTo] = useState(params.to);
  // null: todos os hábitos (inclusive os que forem criados depois)
  const [selected, setSelected] = useState(params.habitIds);
  const [submitted, setSubmitted] = useState(false);

  const periodError = checkPeriod(from, to);
  const noHabit = selected !== null && selected.length === 0;
  const errorId = `${id}-period-error`;
  const habitsErrorId = `${id}-habits-error`;

  const choosePreset = (preset) => {
    const period = presetPeriod(preset, today);
    setFrom(period.from);
    setTo(period.to);
  };

  const toggleAll = (checked) => setSelected(checked ? null : []);

  const toggleHabit = (habitId, checked) => {
    const base = selected ?? habits.map((habit) => habit.id);
    const next = checked ? [...base, habitId] : base.filter((value) => value !== habitId);
    // Todos marcados de novo: volta a "todos"
    const all = habits.length > 0 && habits.every((habit) => next.includes(habit.id));
    setSelected(all ? null : [...new Set(next)].sort((a, b) => a - b));
  };

  const submit = (event) => {
    event.preventDefault();
    setSubmitted(true);
    if (periodError || noHabit) return;
    onSubmit({ from, to, habitIds: selected });
  };

  let habitList;
  if (!habitsLoaded) {
    habitList = habitsError ? (
      <ErrorMessage error={habitsError} onRetry={onRetryHabits} />
    ) : (
      <p role="status">{t('common.loading')}</p>
    );
  } else {
    habitList = (
      <ul className={styles.checks}>
        {habits.map((habit) => (
          <li key={habit.id}>
            <label className={styles.check}>
              <input
                type="checkbox"
                checked={selected === null || selected.includes(habit.id)}
                onChange={(event) => toggleHabit(habit.id, event.target.checked)}
              />
              <HabitSwatch className={styles.swatch} color={habit.color} />
              <span className={styles.checkText}>
                {habit.status === 'archived'
                  ? t('report.archived_habit', { name: habit.name })
                  : habit.name}
              </span>
            </label>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate aria-label={t('report.form')}>
      <fieldset className={styles.fieldset}>
        <legend className={styles.legend}>{t('report.period')}</legend>
        <div className={styles.presets} role="group" aria-label={t('report.presets.label')}>
          {PERIOD_PRESETS.map((preset) => (
            <button key={preset} type="button" className={styles.button} onClick={() => choosePreset(preset)}>
              {t(`report.presets.${preset}`)}
            </button>
          ))}
        </div>
        <div className={styles.dates}>
          <label className={styles.field}>
            <span className={styles.label}>{t('report.from')}</span>
            <input
              type="date"
              className={styles.input}
              value={from}
              onChange={(event) => setFrom(event.target.value)}
              aria-invalid={periodError !== null}
              aria-describedby={periodError ? errorId : undefined}
              required
            />
          </label>
          <label className={styles.field}>
            <span className={styles.label}>{t('report.to')}</span>
            <input
              type="date"
              className={styles.input}
              value={to}
              onChange={(event) => setTo(event.target.value)}
              aria-invalid={periodError !== null}
              aria-describedby={periodError ? errorId : undefined}
              required
            />
          </label>
        </div>
        <p className={styles.hint}>{t('report.period_hint', { timezone: timeZone })}</p>
        {periodError && (
          <p id={errorId} className={styles.fieldError}>
            {t(`report.period_errors.${periodError}`)}
          </p>
        )}
      </fieldset>

      <fieldset
        className={styles.fieldset}
        aria-describedby={submitted && noHabit ? habitsErrorId : undefined}
      >
        <legend className={styles.legend}>{t('report.habits')}</legend>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={selected === null}
            onChange={(event) => toggleAll(event.target.checked)}
          />
          <span className={styles.checkText}>{t('report.all_habits')}</span>
        </label>
        {habitList}
        {submitted && noHabit && (
          <p id={habitsErrorId} className={styles.fieldError} role="alert">
            {t('report.no_habit_selected')}
          </p>
        )}
      </fieldset>

      <div>
        <button type="submit" className={styles.primary}>
          {t('report.submit')}
        </button>
      </div>
    </form>
  );
}
