import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ErrorMessage from '../../components/ErrorMessage';
import {
  BANNER_TEXT_MAX_LENGTH,
  bannerForm,
  bannerPayload,
  bannerTextLength,
  singleLine,
} from '../../lib/banner';
import styles from './admin.module.css';

const TEXTS = [
  { name: 'text_pt', lang: 'pt' },
  { name: 'text_en', lang: 'en' },
];
const DATES = ['starts_at', 'ends_at'];

// Formulário de criar (sem `banner`) e de editar um banner: texto em pt e en com contador de 280
// e a janela em data e hora no fuso do admin. `onSubmit(valores)` recebe o corpo pronto para a
// API (no editar, só o que mudou; nada mudou: objeto vazio). `error`: o erro da API
export default function BannerForm({ banner = null, timeZone, pending, error, submitLabel, onSubmit, onCancel }) {
  const { t } = useTranslation();
  const id = useId();
  const [form, setForm] = useState(() => bannerForm(banner, timeZone, Date.now()));
  const [submitted, setSubmitted] = useState(false);
  const { values, errors } = bannerPayload(form, timeZone, banner);
  const shown = submitted ? errors : {};

  const change = (name, transform = (value) => value) => (event) => {
    const { value } = event.target;
    setForm((current) => ({ ...current, [name]: transform(value) }));
  };

  const submit = (event) => {
    event.preventDefault();
    setSubmitted(true);
    if (Object.keys(errors).length > 0 || pending) return;
    onSubmit(values);
  };

  // Campo inválido: pelo formulário ou pela API (field do erro)
  const invalid = (name) => Boolean(shown[name]) || error?.field === name;
  const describedBy = (name, ...extra) =>
    [...extra, shown[name] ? `${id}-${name}-error` : null].filter(Boolean).join(' ') || undefined;

  const fieldError = (name) =>
    shown[name] && (
      <p id={`${id}-${name}-error`} className={styles.fieldError}>
        {t(`admin.banners.errors.${shown[name]}`, { max: BANNER_TEXT_MAX_LENGTH })}
      </p>
    );

  return (
    <form className={styles.form} aria-label={submitLabel} onSubmit={submit} noValidate>
      {TEXTS.map(({ name, lang }) => {
        const length = bannerTextLength(form[name]);
        const over = length > BANNER_TEXT_MAX_LENGTH;
        return (
          <div key={name} className={styles.field}>
            <label className={styles.label} htmlFor={`${id}-${name}`}>
              {t(`admin.banners.${name}`)}
            </label>
            <textarea
              id={`${id}-${name}`}
              className={styles.input}
              lang={lang}
              rows={3}
              value={form[name]}
              aria-invalid={invalid(name) || over}
              aria-describedby={describedBy(name, `${id}-${name}-counter`)}
              onChange={change(name, singleLine)}
            />
            <p id={`${id}-${name}-counter`} className={`${styles.counter} ${over ? styles.counterOver : ''}`}>
              {t('admin.banners.counter', { n: length, max: BANNER_TEXT_MAX_LENGTH })}
            </p>
            {fieldError(name)}
          </div>
        );
      })}

      <div className={styles.fields}>
        {DATES.map((name) => (
          <div key={name} className={styles.field}>
            <label className={styles.label} htmlFor={`${id}-${name}`}>
              {t(`admin.banners.${name}`)}
            </label>
            <input
              id={`${id}-${name}`}
              className={styles.input}
              type="datetime-local"
              value={form[name]}
              aria-invalid={invalid(name)}
              aria-describedby={describedBy(name, `${id}-timezone`)}
              onChange={change(name)}
            />
            {fieldError(name)}
          </div>
        ))}
      </div>
      <p id={`${id}-timezone`} className={styles.hint}>
        {t('admin.banners.timezone_hint', { timezone: timeZone })}
      </p>

      {error && <ErrorMessage error={error} />}

      <div className={styles.buttons}>
        <button type="submit" className={styles.primary} disabled={pending}>
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" className={styles.button} onClick={onCancel}>
            {t('admin.cancel')}
          </button>
        )}
      </div>
    </form>
  );
}
