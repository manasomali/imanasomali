import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../lib/api';
import { MAX_DURATION_MINUTES } from '../../lib/duration';
import {
  COST_LEVELS,
  FORM_FIELDS,
  GOAL_TYPES,
  PERIODS,
  TEXT_LIMITS,
  goalSummary,
  habitForm,
  habitPayload,
  maxGoalCount,
  minGoalCount,
  textLength,
  turnedOff,
  visibleFields,
} from '../../lib/habitForm';
import { formatMoney } from '../../lib/money';
import { HABIT_COLORS } from '../../lib/palette';
import ErrorMessage from '../ErrorMessage';
import styles from './styles.module.css';

// Mudar estes campos muda os limites de N: o erro de N aparece na hora
const GOAL_FIELDS = new Set(['goal_type', 'goal_period', 'multi_mark']);
const COST_LIMIT_FIELDS = ['cost_limit_cents', 'cost_limit_period'];

/** Elemento de um campo pelo `name` (num grupo de rádios, o marcado ou o primeiro). */
function fieldElement(form, name) {
  const element = form?.elements.namedItem(name);
  if (!element || typeof element.focus === 'function') return element;
  return [...element].find((item) => item.checked) ?? element[0];
}

// Formulário de configuração de um hábito, para criar (sem `habit`) e editar (`habit`: o HabitOut
// salvo, base do que mudou). Valida como a API (src/lib/habitForm.js) e chama `onSubmit(valores)`
// com o corpo pronto: no criar, a configuração; no editar, só o que mudou (nada mudou: avisa e não
// chama). `error`: o erro da última tentativa; um 422 com `field` aparece embaixo do campo.
// `disabled`: só leitura (hábito arquivado). `onEdit`: chamado a cada mudança (ex.: para tirar o
// "salvo" da tela)
export default function HabitForm({ habit = null, pending, error, submitLabel, disabled = false, onSubmit, onEdit }) {
  const { t, i18n } = useTranslation();
  // O dinheiro é lido no idioma em que o formulário foi preenchido
  const [locale] = useState(i18n.resolvedLanguage);
  const id = useId();
  const formRef = useRef(null);
  const [form, setForm] = useState(() => habitForm(habit, locale));
  const [touched, setTouched] = useState(() => new Set());
  const [submitted, setSubmitted] = useState(false);
  const [unchanged, setUnchanged] = useState(false);
  // Erro da API que a pessoa já começou a corrigir (mexeu no campo dele)
  const [handledError, setHandledError] = useState(null);

  const { values, errors } = habitPayload(form, locale, habit);
  // No editar, vai só o que a pessoa mexeu e difere do hábito atual: um campo que ela não tocou e
  // que mudou em outra aba (o hábito é buscado de novo) não volta ao valor antigo
  // O limite de custo e o período dele vão sempre juntos
  const edited = (name) =>
    touched.has(name) || (COST_LIMIT_FIELDS.includes(name) && COST_LIMIT_FIELDS.some((field) => touched.has(field)));
  const changes = habit ? Object.fromEntries(Object.entries(values).filter(([name]) => edited(name))) : values;
  // Campos na tela: o valor do limite de custo só aparece com o período do limite escolhido
  const visible = new Set(visibleFields(form));
  if (form.cost_limit_period === '') visible.delete('cost_limit_cents');
  const off = new Set(turnedOff(form, habit));
  const apiField =
    error instanceof ApiError &&
    error !== handledError &&
    error.code === 'validation_error' &&
    FORM_FIELDS.includes(error.field) &&
    visible.has(error.field)
      ? error.field
      : null;

  // 422 da API: o foco vai para o campo recusado
  useEffect(() => {
    if (apiField) fieldElement(formRef.current, apiField)?.focus();
  }, [apiField, error]);

  const fieldError = (name) => {
    if (errors[name] && (submitted || touched.has(name))) {
      const { code, ...params } = errors[name];
      return t(`habit_form.errors.${code}`, params);
    }
    return apiField === name ? t(`habit_form.invalid.${name}`) : null;
  };

  const update = (name, value) => {
    setForm((current) => ({ ...current, [name]: value }));
    setTouched((current) => {
      const next = new Set(current).add(name);
      if (GOAL_FIELDS.has(name)) next.add('goal_count');
      return next;
    });
    setUnchanged(false);
    if (error?.field === name) setHandledError(error);
    onEdit?.();
  };

  const onText = (name, transform = (value) => value) => (event) =>
    update(name, transform(event.target.value));
  const onCheck = (name) => (event) => update(name, event.target.checked);

  const submit = (event) => {
    event.preventDefault();
    if (pending || disabled) return;
    setSubmitted(true);
    const invalid = FORM_FIELDS.find((name) => errors[name]);
    if (invalid) {
      fieldElement(formRef.current, invalid)?.focus();
      return;
    }
    if (habit && Object.keys(changes).length === 0) {
      setUnchanged(true);
      return;
    }
    onSubmit(changes);
  };

  /** Ids que descrevem o campo: dicas, contador e o erro (quando há). */
  const describedBy = (name, ...extra) =>
    [...extra, fieldError(name) ? `${id}-${name}-error` : null].filter(Boolean).join(' ') || undefined;

  const errorText = (name) => {
    const message = fieldError(name);
    return (
      message && (
        <p id={`${id}-${name}-error`} className={styles.fieldError}>
          {message}
        </p>
      )
    );
  };

  const inputProps = (name, ...describers) => ({
    id: `${id}-${name}`,
    name,
    className: styles.input,
    value: form[name],
    'aria-invalid': fieldError(name) ? true : undefined,
    'aria-describedby': describedBy(name, ...describers),
  });

  /** Campo de texto com contador de caracteres. */
  const textField = (name, { multiline = false, transform, hint, required = false, ...rest } = {}) => {
    const length = textLength(form[name]);
    const max = TEXT_LIMITS[name];
    const hintId = hint ? `${id}-${name}-hint` : null;
    const props = {
      ...inputProps(name, hintId, `${id}-${name}-counter`),
      onChange: onText(name, transform),
      'aria-required': required || undefined,
      ...rest,
    };
    return (
      <div className={styles.field}>
        <label className={styles.label} htmlFor={props.id}>
          {t(`habit_form.${name}`)}
        </label>
        {multiline ? <textarea rows={4} {...props} /> : <input type="text" autoComplete="off" {...props} />}
        <div className={styles.meta}>
          {hint && (
            <p id={hintId} className={styles.hint}>
              {hint}
            </p>
          )}
          <p
            id={`${id}-${name}-counter`}
            className={`${styles.counter} ${length > max ? styles.counterOver : ''}`}
          >
            {t('habit_form.counter', { n: length, max })}
          </p>
        </div>
        {errorText(name)}
      </div>
    );
  };

  /** Chave de um recurso, com o aviso de que os dados ficam guardados ao desligar. */
  const featureSwitch = (flag, children) => (
    <div className={styles.feature}>
      <div className={styles.switchRow}>
        <input
          type="checkbox"
          role="switch"
          id={`${id}-${flag}`}
          name={flag}
          className={styles.switch}
          checked={form[flag]}
          onChange={onCheck(flag)}
          aria-describedby={`${id}-${flag}-hint ${id}-${flag}-off`}
        />
        <label htmlFor={`${id}-${flag}`} className={styles.switchLabel}>
          {t(`habit_form.features.${flag}`)}
        </label>
      </div>
      <p id={`${id}-${flag}-hint`} className={styles.hint}>
        {t(`habit_form.features.${flag}_hint`)}
      </p>
      <p id={`${id}-${flag}-off`} className={styles.kept} role="status">
        {off.has(flag) ? t(`habit_form.kept.${flag}`) : ''}
      </p>
      {form[flag] && children && <div className={styles.featureFields}>{children}</div>}
    </div>
  );

  const goalMin = minGoalCount(form.goal_type);
  const goalMax = maxGoalCount(form.goal_period, form.multi_mark);
  const moneyHint = t('habit_form.money_hint', { example: formatMoney(1250, locale) });
  // A semana do limite, como a da meta, vai de segunda a domingo (o calendário começa no domingo)
  const limitWeekHint = form.cost_limit_period === 'week' ? `${id}-limit-week-hint` : null;

  return (
    <form ref={formRef} className={styles.form} aria-label={submitLabel} onSubmit={submit} noValidate>
      <fieldset className={styles.reset} disabled={disabled}>
        <fieldset className={styles.group}>
          <legend className={styles.legend}>{t('habit_form.groups.identity')}</legend>
          {textField('name', { required: true })}
          {textField('code', {
            transform: (value) => value.toUpperCase(),
            hint: t('habit_form.code_hint'),
            autoCapitalize: 'characters',
            spellCheck: false,
          })}
          {textField('description', { multiline: true })}

          <fieldset className={styles.colors}>
            <legend className={styles.label}>
              {t('habit_form.color')}: {t(`habit_form.colors.${form.color}`)}
            </legend>
            <div className={styles.palette}>
              {HABIT_COLORS.map((color) => (
                <label key={color} className={styles.colorOption} title={t(`habit_form.colors.${color}`)}>
                  <input
                    type="radio"
                    name="color"
                    value={color}
                    className={`visually-hidden ${styles.colorRadio}`}
                    checked={form.color === color}
                    onChange={onText('color')}
                  />
                  <span className={styles.colorSwatch} data-habit-color={color} aria-hidden="true" />
                  <span className="visually-hidden">{t(`habit_form.colors.${color}`)}</span>
                </label>
              ))}
            </div>
            {errorText('color')}
          </fieldset>
        </fieldset>

        <fieldset className={styles.group}>
          <legend className={styles.legend}>{t('habit_form.groups.goal')}</legend>
          <div className={styles.goal}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`${id}-goal_type`}>
                {t('habit_form.goal_type')}
              </label>
              <select {...inputProps('goal_type')} onChange={onText('goal_type')}>
                {GOAL_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(`habit_form.goal_types.${type}`)}
                  </option>
                ))}
              </select>
              {errorText('goal_type')}
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`${id}-goal_count`}>
                {t('habit_form.goal_count')}
              </label>
              <input
                type="number"
                inputMode="numeric"
                min={goalMin}
                max={goalMax}
                step={1}
                aria-required
                {...inputProps('goal_count', `${id}-goal_count-hint`)}
                onChange={onText('goal_count')}
              />
              <p id={`${id}-goal_count-hint`} className={styles.hint}>
                {t('habit_form.goal_count_hint', { min: goalMin, max: goalMax })}
              </p>
              {errorText('goal_count')}
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`${id}-goal_period`}>
                {t('habit_form.goal_period')}
              </label>
              <select {...inputProps('goal_period')} onChange={onText('goal_period')}>
                {PERIODS.map((period) => (
                  <option key={period} value={period}>
                    {t(`habit_form.periods.${period}`)}
                  </option>
                ))}
              </select>
              {errorText('goal_period')}
            </div>
          </div>
          <GoalPreview form={form} />
          {featureSwitch('multi_mark')}
        </fieldset>

        <fieldset className={styles.group}>
          <legend className={styles.legend}>{t('habit_form.groups.features')}</legend>
          {featureSwitch(
            'duration_enabled',
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`${id}-duration_minutes`}>
                {t('habit_form.duration_minutes')}
              </label>
              <input
                type="number"
                inputMode="numeric"
                min={1}
                max={MAX_DURATION_MINUTES}
                step={1}
                aria-required
                {...inputProps('duration_minutes', `${id}-duration_minutes-hint`)}
                onChange={onText('duration_minutes')}
              />
              <p id={`${id}-duration_minutes-hint`} className={styles.hint}>
                {t('habit_form.duration_minutes_hint', { max: MAX_DURATION_MINUTES })}
              </p>
              {errorText('duration_minutes')}
            </div>,
          )}
          {featureSwitch('notes_enabled')}
          {featureSwitch(
            'score_enabled',
            <>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={`${id}-score_threshold`}>
                  {t('habit_form.score_threshold')}
                </label>
                <input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={100}
                  step={1}
                  aria-required
                  {...inputProps('score_threshold', `${id}-score_threshold-hint`)}
                  onChange={onText('score_threshold')}
                />
                <p id={`${id}-score_threshold-hint`} className={styles.hint}>
                  {t('habit_form.score_threshold_hint')}
                </p>
                {errorText('score_threshold')}
              </div>
              {textField('reward', { hint: t('habit_form.reward_hint') })}
              {textField('punishment', { hint: t('habit_form.punishment_hint') })}
            </>,
          )}
          {featureSwitch(
            'cost_enabled',
            <>
              <fieldset className={styles.field}>
                <legend className={styles.label}>{t('habit_form.cost_level')}</legend>
                {COST_LEVELS.map((level) => (
                  <label key={level} className={styles.choice}>
                    <input
                      type="radio"
                      name="cost_level"
                      value={level}
                      checked={form.cost_level === level}
                      onChange={onText('cost_level')}
                    />
                    <span>{t(`habit_form.cost_levels.${level}`)}</span>
                  </label>
                ))}
                {errorText('cost_level')}
              </fieldset>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={`${id}-cost_cents`}>
                  {t(`habit_form.cost_cents_${form.cost_level === 'mark' ? 'mark' : 'habit'}`)}
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  aria-required={form.cost_level === 'habit' || undefined}
                  {...inputProps('cost_cents', `${id}-money-hint`)}
                  onChange={onText('cost_cents')}
                />
                {errorText('cost_cents')}
              </div>
              <p id={`${id}-money-hint`} className={styles.hint}>
                {moneyHint}
              </p>
              <div className={styles.goal}>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor={`${id}-cost_limit_period`}>
                    {t('habit_form.cost_limit_period')}
                  </label>
                  <select
                    {...inputProps('cost_limit_period', limitWeekHint)}
                    onChange={onText('cost_limit_period')}
                  >
                    <option value="">{t('habit_form.no_limit')}</option>
                    {PERIODS.map((period) => (
                      <option key={period} value={period}>
                        {t(`habit_form.limit_periods.${period}`)}
                      </option>
                    ))}
                  </select>
                  {limitWeekHint && (
                    <p id={limitWeekHint} className={styles.hint}>
                      {t('habit_form.limit_week_hint')}
                    </p>
                  )}
                  {errorText('cost_limit_period')}
                </div>
                {form.cost_limit_period !== '' && (
                  <div className={styles.field}>
                    <label className={styles.label} htmlFor={`${id}-cost_limit_cents`}>
                      {t('habit_form.cost_limit_cents')}
                    </label>
                    <input
                      type="text"
                      inputMode="decimal"
                      autoComplete="off"
                      aria-required
                      {...inputProps('cost_limit_cents', `${id}-money-hint`)}
                      onChange={onText('cost_limit_cents')}
                    />
                    {errorText('cost_limit_cents')}
                  </div>
                )}
              </div>
            </>,
          )}
        </fieldset>

        {error && !apiField && error !== handledError && <ErrorMessage error={error} />}
        <p className={styles.status} role="status">
          {unchanged ? t('habit_form.unchanged') : ''}
        </p>
        <div className={styles.buttons}>
          <button type="submit" className={styles.primary} disabled={pending}>
            {pending ? t('habit_form.saving') : submitLabel}
          </button>
        </div>
      </fieldset>
    </form>
  );
}

// Prévia da meta em texto ("Pelo menos 3 vezes por semana"; "no máximo 0" vira "nenhuma vez"),
// lida pelo leitor de tela quando muda. Na meta semanal, lembra que a semana vai de segunda a
// domingo, já que o calendário começa no domingo
function GoalPreview({ form }) {
  const { t } = useTranslation();
  const summary = goalSummary(form);
  let text = t('goal_preview.invalid');
  let minutes = null;
  if (summary) {
    const period = t(`goal_preview.period.${summary.period}`);
    text = summary.never
      ? t('goal_preview.never', { period })
      : t(`goal_preview.${summary.type}`, { count: summary.count, period });
    if (summary.totalMinutes !== null) {
      minutes = t(`goal_preview.minutes_${summary.type}`, { total: summary.totalMinutes, period });
    }
  }
  return (
    <div className={styles.preview} aria-live="polite">
      <p>
        <span className={styles.previewLabel}>{t('goal_preview.label')}</span> <span>{text}</span>
      </p>
      {minutes && <p>{minutes}</p>}
      {summary?.period === 'week' && <p>{t('goal_preview.week_range')}</p>}
    </div>
  );
}
