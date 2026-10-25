import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useUpdateMark } from '../../api/marks';
import { ApiError } from '../../lib/api';
import { MAX_DURATION_MINUTES, parseDuration } from '../../lib/duration';
import { formatTime } from '../../lib/format';
import { formatMoney, parseMoney } from '../../lib/money';
import ErrorMessage from '../ErrorMessage';
import styles from './styles.module.css';

/** Campos da marcação que a tela deixa editar, conforme os recursos ligados no hábito. */
function editableFields(habit) {
  return {
    note: habit.notes_enabled,
    duration: habit.duration_enabled,
    // No nível hábito o custo é fixo (a API recusa outro valor)
    cost: habit.cost_enabled && habit.cost_level === 'mark',
  };
}

// Campos da API (o `field` do 422) para os do formulário
const API_FIELDS = { note: 'note', duration_minutes: 'duration', cost_cents: 'cost' };

// Detalhes de uma marcação: horário, autor ("usuário removido" quando a conta foi apagada) e, com
// o recurso ligado, duração, custo e observação. Dono e editor (`writable`) editam observação,
// duração e custo; a data não muda. `onDelete(mark)`: botão de apagar (várias por dia)
export default function MarkItem({ habit, mark, timeZone, writable, onDelete }) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const fields = editableFields(habit);
  const time = formatTime(mark.marked_at, timeZone, language);
  const ready = writable && !mark.pending;
  const canEdit = ready && (fields.note || fields.duration || fields.cost);

  return (
    <li className={styles.item} data-pending={mark.pending || undefined}>
      <dl className={styles.details}>
        <div>
          <dt>{t('mark.time')}</dt>
          <dd>{time}</dd>
        </div>
        <div>
          <dt>{t('mark.author')}</dt>
          <dd>{mark.author ? mark.author.email : t('mark.removed_user')}</dd>
        </div>
        {habit.duration_enabled && mark.duration_minutes !== null && (
          <div>
            <dt>{t('mark.duration')}</dt>
            <dd>{t('mark.minutes', { count: mark.duration_minutes })}</dd>
          </div>
        )}
        {habit.cost_enabled && mark.cost_cents !== null && (
          <div>
            <dt>{t('mark.cost')}</dt>
            <dd>{formatMoney(mark.cost_cents, language)}</dd>
          </div>
        )}
        {habit.notes_enabled && mark.note && (
          <div className={styles.note}>
            <dt>{t('mark.note')}</dt>
            <dd>{mark.note}</dd>
          </div>
        )}
      </dl>

      {mark.pending && (
        <p className={styles.muted} role="status">
          {t('mark.saving')}
        </p>
      )}

      {ready && !editing && (canEdit || onDelete) && (
        <div className={styles.actions}>
          {canEdit && (
            <button
              type="button"
              className={styles.button}
              aria-label={t('mark.edit_label', { time })}
              onClick={() => setEditing(true)}
            >
              {t('mark.edit')}
            </button>
          )}
          {onDelete && !confirming && (
            <button
              type="button"
              className={styles.button}
              aria-label={t('mark.delete_label', { time })}
              onClick={() => setConfirming(true)}
            >
              {t('mark.delete')}
            </button>
          )}
          {onDelete && confirming && (
            <>
              <button type="button" className={styles.danger} onClick={() => onDelete(mark)}>
                {t('mark.confirm_delete')}
              </button>
              <button type="button" className={styles.button} onClick={() => setConfirming(false)}>
                {t('mark.cancel')}
              </button>
            </>
          )}
        </div>
      )}

      {canEdit && editing && (
        <MarkForm habit={habit} mark={mark} fields={fields} onClose={() => setEditing(false)} />
      )}
    </li>
  );
}

function initialValues(mark, language) {
  return {
    note: mark.note ?? '',
    duration: mark.duration_minutes === null ? '' : String(mark.duration_minutes),
    cost: mark.cost_cents === null ? '' : formatMoney(mark.cost_cents, language),
  };
}

/**
 * O que mudou no formulário, no formato do PATCH, e os erros de cada campo. Campo igual ao da
 * marcação fica de fora; observação vazia apaga (null); custo vazio apaga; duração não fica vazia.
 */
function changesFrom(values, mark, fields, language) {
  const changes = {};
  const errors = {};
  if (fields.note) {
    const note = values.note.trim() || null;
    if (note !== mark.note) changes.note = note;
  }
  if (fields.duration && !(values.duration.trim() === '' && mark.duration_minutes === null)) {
    const minutes = parseDuration(values.duration);
    if (minutes === null) errors.duration = 'mark.invalid_duration';
    else if (minutes !== mark.duration_minutes) changes.duration_minutes = minutes;
  }
  if (fields.cost) {
    const text = values.cost.trim();
    const cents = text === '' ? null : parseMoney(text, language);
    if (text !== '' && cents === null) errors.cost = 'mark.invalid_cost';
    else if (cents !== mark.cost_cents) changes.cost_cents = cents;
  }
  return { changes, errors };
}

function MarkForm({ habit, mark, fields, onClose }) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const id = useId();
  const update = useUpdateMark(habit);
  const [values, setValues] = useState(() => initialValues(mark, language));
  const [errors, setErrors] = useState({});

  // 422 com o campo vai para o campo; o resto aparece embaixo do formulário
  const apiField =
    update.error instanceof ApiError && update.error.code === 'validation_error'
      ? API_FIELDS[update.error.field]
      : undefined;
  const fieldError = (name) => {
    if (errors[name]) return t(errors[name]);
    return apiField === name ? t(`mark.invalid_${name}`) : null;
  };

  const onChange = (name) => (event) => {
    const { value } = event.target;
    setValues((previous) => ({ ...previous, [name]: value }));
  };

  const onSubmit = (event) => {
    event.preventDefault();
    const result = changesFrom(values, mark, fields, language);
    setErrors(result.errors);
    if (Object.keys(result.errors).length > 0) return;
    if (Object.keys(result.changes).length === 0) {
      onClose();
      return;
    }
    update.mutate({ mark, changes: result.changes }, { onSuccess: onClose });
  };

  const field = (name, label, input) => {
    const error = fieldError(name);
    return (
      <div className={styles.field}>
        <label htmlFor={`${id}-${name}`}>{label}</label>
        {input({
          id: `${id}-${name}`,
          value: values[name],
          onChange: onChange(name),
          'aria-invalid': error ? true : undefined,
          'aria-describedby': error ? `${id}-${name}-error` : undefined,
        })}
        {error && (
          <p id={`${id}-${name}-error`} className={styles.fieldError}>
            {error}
          </p>
        )}
      </div>
    );
  };

  return (
    <form className={styles.form} onSubmit={onSubmit} noValidate>
      <p className={styles.muted}>{t('mark.date_fixed')}</p>
      {fields.note &&
        field('note', t('mark.note'), (props) => <textarea rows={3} {...props} />)}
      {fields.duration &&
        field('duration', t('mark.duration_minutes'), (props) => (
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_DURATION_MINUTES}
            step={1}
            {...props}
          />
        ))}
      {fields.cost &&
        field('cost', t('mark.cost'), (props) => (
          <input type="text" inputMode="decimal" {...props} />
        ))}
      {update.error && !apiField && <ErrorMessage error={update.error} />}
      <div className={styles.actions}>
        <button type="submit" className={styles.primary} disabled={update.isPending}>
          {update.isPending ? t('mark.saving') : t('mark.save')}
        </button>
        <button type="button" className={styles.button} onClick={onClose}>
          {t('mark.cancel')}
        </button>
      </div>
    </form>
  );
}
