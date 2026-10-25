import { useId, useRef, useState } from 'react';
import { Link } from 'react-router';
import { Trans, useTranslation } from 'react-i18next';
import { useAlert, useSaveAlert } from '../../api/alerts';
import ErrorMessage from '../../components/ErrorMessage';
import { WithHelp } from '../../components/HelpLink';
import useHabitContext from '../../hooks/useHabitContext';
import {
  ALERT_HOURS,
  COST_WARNING_PERCENT,
  FREQUENCIES,
  WEEKDAYS,
  alertErrors,
  alertForm,
  alertPayload,
  canFallBehind,
  firstAlertDay,
  formatHour,
  hasCostAlert,
  weeklyPaceStart,
} from '../../lib/alerts';
import { formatDateTime, formatShortDay, weekdayNames } from '../../lib/format';
import { goalSummary, habitForm } from '../../lib/habitForm';
import { formatMoney } from '../../lib/money';
import { PATHS } from '../../paths';
import styles from './styles.module.css';

// Campos que um 422 da API pode apontar e que a tela mostra como inválidos
const FORM_FIELDS = ['goal_enabled', 'cost_enabled', 'hour', 'frequency', 'weekday'];

/** Elemento de um campo pelo `name` (num grupo de rádios, o marcado ou o primeiro). */
function fieldElement(form, name) {
  const element = form?.elements.namedItem(name);
  if (!element || typeof element.focus === 'function') return element;
  return [...element].find((item) => item.checked) ?? element[0];
}

// Alertas do hábito (`/habits/:habitId/alerts`, o link do email de alerta): a configuração pessoal
// de quem é dono ou editor. Viewer não liga alertas: o link nem aparece no submenu, e quem abre o
// endereço vê "sem permissão" (a API também recusa, com 403)
export default function HabitAlerts() {
  const { habit, timeZone } = useHabitContext();
  const { t } = useTranslation();
  const titleId = useId();

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <WithHelp section="alerts" topic={t('habit_alerts.title')}>
        <h2 id={titleId} className={styles.title}>
          {t('habit_alerts.title')}
        </h2>
      </WithHelp>
      {habit.role === 'viewer' ? (
        <p className={styles.notice}>{t('habit_alerts.forbidden')}</p>
      ) : (
        <AlertLoader habit={habit} timeZone={timeZone} />
      )}
    </section>
  );
}

function AlertLoader({ habit, timeZone }) {
  const { t } = useTranslation();
  const query = useAlert(habit.id);

  if (query.data === undefined) {
    return query.isPending ? (
      <p role="status">{t('common.loading')}</p>
    ) : (
      <ErrorMessage error={query.error} onRetry={() => query.refetch()} />
    );
  }
  return <AlertForm habit={habit} alert={query.data} timeZone={timeZone} />;
}

function AlertForm({ habit, alert, timeZone }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const id = useId();
  const formRef = useRef(null);
  const save = useSaveAlert(habit.id);
  // O formulário parte do que estava salvo ao abrir a tela; uma busca nova não apaga o que a
  // pessoa está mudando
  const [form, setForm] = useState(() => alertForm(alert));
  const [submitted, setSubmitted] = useState(false);

  const archived = habit.status === 'archived';
  const costShown = hasCostAlert(habit);
  const errors = submitted ? alertErrors(form) : {};
  const apiField = FORM_FIELDS.includes(save.error?.field) ? save.error.field : null;
  const weekdays = weekdayNames(locale);

  const change = (name, value) => {
    setForm((current) => ({ ...current, [name]: value }));
    if (!save.isIdle) save.reset();
  };

  const submit = (event) => {
    event.preventDefault();
    setSubmitted(true);
    const invalid = FORM_FIELDS.find((name) => alertErrors(form)[name]);
    if (invalid) {
      fieldElement(formRef.current, invalid)?.focus();
      return;
    }
    save.mutate(alertPayload(form), {
      onError: (error) => {
        if (FORM_FIELDS.includes(error?.field)) fieldElement(formRef.current, error.field)?.focus();
      },
    });
  };

  const invalidProps = (name) => ({
    'aria-invalid': errors[name] || apiField === name ? true : undefined,
    'aria-describedby': [`${id}-${name}-hint`, errors[name] ? `${id}-${name}-error` : null]
      .filter(Boolean)
      .join(' '),
  });

  const fieldError = (name) =>
    errors[name] ? (
      <p id={`${id}-${name}-error`} className={styles.fieldError}>
        {t(`habit_alerts.errors.${name}_${errors[name]}`)}
      </p>
    ) : null;

  return (
    <>
      <p className={styles.muted}>{t('habit_alerts.intro')}</p>
      {archived && <p className={styles.notice}>{t('habit_alerts.archived')}</p>}
      {habit.status === 'paused' && <p className={styles.notice}>{t('habit_alerts.paused')}</p>}

      <form
        ref={formRef}
        className={styles.form}
        aria-label={t('habit_alerts.save')}
        onSubmit={submit}
        noValidate
      >
        <fieldset className={styles.reset} disabled={archived}>
          <fieldset className={styles.group}>
            <legend className={styles.legend}>{t('habit_alerts.groups.what')}</legend>
            <div className={styles.feature}>
              <div className={styles.switchRow}>
                <input
                  type="checkbox"
                  role="switch"
                  id={`${id}-goal_enabled`}
                  name="goal_enabled"
                  className={styles.switch}
                  checked={form.goal_enabled}
                  onChange={(event) => change('goal_enabled', event.target.checked)}
                  {...invalidProps('goal_enabled')}
                />
                <label htmlFor={`${id}-goal_enabled`} className={styles.switchLabel}>
                  {t('habit_alerts.goal_enabled')}
                </label>
              </div>
              <GoalRule id={`${id}-goal_enabled-hint`} habit={habit} timeZone={timeZone} />
            </div>
            {costShown && (
              <div className={styles.feature}>
                <div className={styles.switchRow}>
                  <input
                    type="checkbox"
                    role="switch"
                    id={`${id}-cost_enabled`}
                    name="cost_enabled"
                    className={styles.switch}
                    checked={form.cost_enabled}
                    onChange={(event) => change('cost_enabled', event.target.checked)}
                    {...invalidProps('cost_enabled')}
                  />
                  <label htmlFor={`${id}-cost_enabled`} className={styles.switchLabel}>
                    {t('habit_alerts.cost_enabled')}
                  </label>
                </div>
                <CostRule id={`${id}-cost_enabled-hint`} habit={habit} timeZone={timeZone} />
              </div>
            )}
          </fieldset>

          <fieldset className={styles.group}>
            <legend className={styles.legend}>{t('habit_alerts.groups.when')}</legend>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`${id}-hour`}>
                {t('habit_alerts.hour')}
              </label>
              <select
                id={`${id}-hour`}
                name="hour"
                className={styles.input}
                value={form.hour}
                onChange={(event) => change('hour', event.target.value)}
                {...invalidProps('hour')}
              >
                {ALERT_HOURS.map((hour) => (
                  <option key={hour} value={String(hour)}>
                    {formatHour(hour, locale)}
                  </option>
                ))}
              </select>
              <p id={`${id}-hour-hint`} className={styles.hint}>
                <Trans
                  i18nKey="habit_alerts.time_zone"
                  values={{ timeZone }}
                  components={{ account: <Link to={PATHS.account} /> }}
                />
              </p>
              {fieldError('hour')}
            </div>

            <fieldset
              className={styles.field}
              aria-describedby={invalidProps('frequency')['aria-describedby']}
            >
              <legend className={styles.label}>{t('habit_alerts.frequency')}</legend>
              {FREQUENCIES.map((frequency) => (
                <label key={frequency} className={styles.choice}>
                  <input
                    type="radio"
                    name="frequency"
                    value={frequency}
                    checked={form.frequency === frequency}
                    onChange={() => change('frequency', frequency)}
                  />
                  <span>{t(`habit_alerts.frequencies.${frequency}`)}</span>
                </label>
              ))}
              <p id={`${id}-frequency-hint`} className={styles.hint}>
                {t('habit_alerts.frequency_hint')}
              </p>
              {fieldError('frequency')}
            </fieldset>

            {form.frequency === 'weekly' && (
              <div className={styles.field}>
                <label className={styles.label} htmlFor={`${id}-weekday`}>
                  {t('habit_alerts.weekday')}
                </label>
                <select
                  id={`${id}-weekday`}
                  name="weekday"
                  className={styles.input}
                  value={form.weekday}
                  aria-required
                  onChange={(event) => change('weekday', event.target.value)}
                  {...invalidProps('weekday')}
                >
                  <option value="">{t('habit_alerts.weekday_choose')}</option>
                  {WEEKDAYS.map((weekday) => (
                    <option key={weekday} value={String(weekday)}>
                      {weekdays[weekday].long}
                    </option>
                  ))}
                </select>
                <p id={`${id}-weekday-hint`} className={styles.hint}>
                  {t('habit_alerts.weekday_hint')}
                </p>
                {fieldError('weekday')}
              </div>
            )}
          </fieldset>

          <ul className={styles.notes}>
            <li>{t('habit_alerts.notes.one_per_day')}</li>
            <li>{t('habit_alerts.notes.creation')}</li>
            <li>{t('habit_alerts.notes.save_after_hour')}</li>
          </ul>

          {save.error && <ErrorMessage error={save.error} />}
          <div className={styles.buttons}>
            <button type="submit" className={styles.primary} disabled={save.isPending}>
              {save.isPending ? t('habit_alerts.saving') : t('habit_alerts.save')}
            </button>
          </div>
          <p className={styles.status} role="status">
            {save.isSuccess ? t('habit_alerts.saved') : ''}
          </p>
        </fieldset>
      </form>

      <p className={styles.muted}>
        {alert.last_sent_at
          ? t('habit_alerts.last_sent', { when: formatDateTime(alert.last_sent_at, timeZone, locale) })
          : t('habit_alerts.never_sent')}
      </p>
    </>
  );
}

// Quando o alerta de meta dispara, para a meta atual do hábito (app/score.py, Pace.alert)
function GoalRule({ id, habit, timeZone }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const summary = goalSummary(habitForm(habit, locale));
  if (summary === null) {
    return (
      <p id={id} className={styles.hint}>
        {t('habit_alerts.goal_rule.unknown')}
      </p>
    );
  }

  const period = t(`goal_preview.period.${summary.period}`);
  const goal = summary.never
    ? t('goal_preview.never', { period })
    : t(`goal_preview.${summary.type}`, { count: summary.count, period });
  const ofPeriod = t(`habit_alerts.of_period.${summary.period}`);
  const target = summary.totalMinutes ?? summary.count;
  const lines = [];
  if (summary.type === 'max') {
    lines.push(t(`habit_alerts.goal_rule.${summary.never ? 'never' : 'max'}`, { of_period: ofPeriod }));
  } else if (!canFallBehind(target)) {
    // Meta 1 no período: o ritmo só pediria a marcação no fim dele (lib/alerts.js)
    lines.push(t(`habit_alerts.goal_rule.${summary.type}_single`, { of_period: ofPeriod }));
  } else {
    lines.push(t(`habit_alerts.goal_rule.${summary.type}`, { of_period: ofPeriod }));
    lines.push(paceExample(summary.period, target, t, locale));
  }

  return (
    <div id={id} className={styles.rule}>
      <p>
        <span className={styles.ruleLabel}>{t('goal_preview.label')}</span> <span>{goal}</span>
        {summary.totalMinutes !== null && (
          <> <span>{t(`goal_preview.minutes_${summary.type}`, { total: summary.totalMinutes, period })}</span></>
        )}
      </p>
      {lines.map((line) => (
        <p key={line}>{line}</p>
      ))}
      <StartsOn habit={habit} period={summary.period} timeZone={timeZone} />
    </div>
  );
}

// Exemplo do ritmo: na semana, o momento exato em que uma semana sem marcações fica atrasada
// (3x por semana: quarta às 08:00); no mês e no ano, a regra da metade
function paceExample(period, target, t, locale) {
  const start = period === 'week' ? weeklyPaceStart(target) : null;
  if (start === null) return t('habit_alerts.pace_example.half');
  return t('habit_alerts.pace_example.week', {
    weekday: weekdayNames(locale)[start.weekday].long,
    time: formatHour(start.hour, locale, start.minute),
  });
}

// Quando o alerta de custo dispara: aviso em 80% do limite e alerta ao passar (score.check_cost)
function CostRule({ id, habit, timeZone }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const period = habit.cost_limit_period;

  return (
    <div id={id} className={styles.rule}>
      <p>
        {t(`habit_alerts.cost_rule.${period}`, {
          percent: COST_WARNING_PERCENT,
          limit: formatMoney(habit.cost_limit_cents, locale),
        })}
      </p>
      <StartsOn habit={habit} period={period} timeZone={timeZone} />
    </div>
  );
}

// Ainda no período (da meta ou do limite) em que o hábito foi criado: a partir de quando o alerta
// pode disparar
function StartsOn({ habit, period, timeZone }) {
  const { t, i18n } = useTranslation();
  const startsOn = firstAlertDay(habit.created_at, period, timeZone);
  if (startsOn === null) return null;
  return (
    <p>
      {t('habit_alerts.starts_on', {
        this_period: t(`habit_alerts.this_period.${period}`),
        date: formatShortDay(startsOn, i18n.resolvedLanguage),
      })}
    </p>
  );
}
