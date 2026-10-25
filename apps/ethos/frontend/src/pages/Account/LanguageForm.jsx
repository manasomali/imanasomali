import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useUpdateMe } from '../../api/auth';
import ErrorMessage from '../../components/ErrorMessage';
import { LANGUAGES } from '../../i18n';
import styles from './styles.module.css';

// Nome de cada idioma escrito nele mesmo (não se traduz)
const LANGUAGE_NAMES = Object.freeze({ pt: 'Português', en: 'English' });

// Idioma da conta (PATCH /auth/me {locale}): o dos emails do ethos. Ao salvar, vira também o da
// tela, na chave i18nextLng compartilhada com o site (useUpdateMe)
export default function LanguageForm({ me }) {
  const { t } = useTranslation();
  const ids = useId();
  const [locale, setLocale] = useState(me.locale);
  const save = useUpdateMe();
  const titleId = `${ids}-title`;
  const helpId = `${ids}-help`;

  const submit = (event) => {
    event.preventDefault();
    if (save.isPending) return;
    save.mutate({ locale });
  };

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.sectionTitle}>
        {t('pages.account.language.title')}
      </h2>
      <form className={styles.form} onSubmit={submit}>
        <fieldset className={styles.field} aria-describedby={helpId}>
          <legend className="visually-hidden">{t('pages.account.language.title')}</legend>
          <p id={helpId} className={styles.muted}>
            {t('pages.account.language.help')}
          </p>
          <div className={styles.choices}>
            {LANGUAGES.map((lng) => (
              <label key={lng} className={styles.choice} lang={lng}>
                <input
                  type="radio"
                  name="locale"
                  value={lng}
                  checked={locale === lng}
                  onChange={() => {
                    setLocale(lng);
                    save.reset();
                  }}
                />
                {LANGUAGE_NAMES[lng]}
              </label>
            ))}
          </div>
        </fieldset>
        {save.isError && <ErrorMessage error={save.error} />}
        <div className={styles.buttons}>
          <button type="submit" className={styles.primary} disabled={save.isPending}>
            {save.isPending ? t('pages.account.saving') : t('pages.account.language.save')}
          </button>
          <p className={styles.status} role="status">
            {save.isSuccess ? t('pages.account.language.saved') : ''}
          </p>
        </div>
      </form>
    </section>
  );
}
