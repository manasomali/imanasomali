import { useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useUpdateMe } from '../../api/auth';
import ErrorMessage from '../../components/ErrorMessage';
import { sameTimezone } from '../../lib/time';
import { filterTimezones, timezoneLabel, timezoneOffset, timezoneOptions } from '../../lib/timezones';
import styles from './styles.module.css';

// Linhas visíveis da lista (no celular o navegador mostra o seletor dele)
const LIST_SIZE = 8;

function describeTimezone(timeZone) {
  const offset = timezoneOffset(timeZone);
  return offset ? `${timezoneLabel(timeZone)} (${offset})` : timezoneLabel(timeZone);
}

// Fuso da conta (PATCH /auth/me {timezone}): dias do calendário, pontuação e alertas. Escolhido
// numa lista de fusos IANA com busca. `suggested` é o fuso do navegador vindo do aviso de fuso:
// já vem selecionado, mas só muda ao salvar
export default function TimezoneForm({ me, suggested }) {
  const { t } = useTranslation();
  const ids = useId();
  const [selected, setSelected] = useState(suggested ?? me.timezone);
  const [query, setQuery] = useState('');
  const save = useUpdateMe();

  // A lista e os offsets uma vez por visita à tela; inclui o fuso da conta e o sugerido, que
  // podem ter uma grafia que o navegador não lista
  const [options] = useState(() =>
    timezoneOptions({ extra: [me.timezone, suggested].filter(Boolean) }),
  );
  const found = useMemo(() => filterTimezones(options, query), [options, query]);
  // O escolhido fica sempre na lista: no celular o seletor vira uma lista suspensa, que mostraria
  // a primeira opção como escolhida se ele sumisse com a busca
  const visible = useMemo(() => {
    if (found.some((option) => option.value === selected)) return found;
    const current = options.find((option) => option.value === selected);
    return current ? [current, ...found] : found;
  }, [options, found, selected]);

  const titleId = `${ids}-title`;
  const helpId = `${ids}-help`;
  const searchId = `${ids}-search`;
  const listId = `${ids}-list`;
  const errorId = `${ids}-error`;
  const fieldError = save.error?.field === 'timezone';
  const showSuggestion = suggested !== null && !sameTimezone(suggested, me.timezone);

  const submit = (event) => {
    event.preventDefault();
    if (save.isPending) return;
    save.mutate({ timezone: selected });
  };

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.sectionTitle}>
        {t('pages.account.timezone.title')}
      </h2>
      <p id={helpId} className={styles.muted}>
        {t('pages.account.timezone.help', { timezone: describeTimezone(me.timezone) })}
      </p>
      {showSuggestion && (
        <p className={styles.status}>
          {t('pages.account.timezone.suggested', { timezone: timezoneLabel(suggested) })}
        </p>
      )}
      <form className={styles.form} onSubmit={submit}>
        <div className={styles.field}>
          <label htmlFor={searchId} className={styles.label}>
            {t('pages.account.timezone.search')}
          </label>
          <input
            id={searchId}
            className={`${styles.input} ${styles.list}`}
            type="search"
            autoComplete="off"
            spellCheck={false}
            maxLength={64}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-controls={listId}
          />
          <p className={styles.muted} role="status">
            {query.trim() ? t('pages.account.timezone.found', { count: found.length }) : ''}
          </p>
        </div>
        <div className={styles.field}>
          <label htmlFor={listId} className={styles.label}>
            {t('pages.account.timezone.list')}
          </label>
          <select
            id={listId}
            className={`${styles.input} ${styles.list}`}
            size={LIST_SIZE}
            value={selected}
            onChange={(event) => {
              setSelected(event.target.value);
              save.reset();
            }}
            aria-invalid={fieldError}
            aria-describedby={fieldError ? `${errorId} ${helpId}` : helpId}
          >
            {visible.map((option) => (
              <option key={option.value} value={option.value}>
                {option.offset ? `${option.label} (${option.offset})` : option.label}
              </option>
            ))}
          </select>
        </div>
        <p>{t('pages.account.timezone.chosen', { timezone: describeTimezone(selected) })}</p>
        {save.isError && (
          <div id={errorId}>
            <ErrorMessage error={save.error} />
          </div>
        )}
        <div className={styles.buttons}>
          <button type="submit" className={styles.primary} disabled={save.isPending}>
            {save.isPending ? t('pages.account.saving') : t('pages.account.timezone.save')}
          </button>
          <p className={styles.status} role="status">
            {save.isSuccess ? t('pages.account.timezone.saved') : ''}
          </p>
        </div>
      </form>
    </section>
  );
}
