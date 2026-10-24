import { useState } from 'react';
import { Link, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { browserTimezone } from '../../lib/time';
import { dismissTimezoneNotice, shouldSuggestTimezone } from '../../lib/timezoneNotice';
import { PATHS } from '../../paths';
import styles from './styles.module.css';

// Sugere trocar o fuso da conta quando o navegador está noutro fuso. Só sugere: a troca é feita
// na tela de conta, que recebe o fuso do navegador em state.suggestedTimezone
export default function TimezoneNotice({ savedTimezone }) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [browser] = useState(browserTimezone);
  const [dismissed, setDismissed] = useState(false);

  // Na tela de conta o seletor de fuso já está à mão
  if (dismissed || pathname === PATHS.account || !shouldSuggestTimezone(savedTimezone, browser)) {
    return null;
  }

  const dismiss = () => {
    dismissTimezoneNotice(savedTimezone, browser);
    setDismissed(true);
  };

  return (
    <section className={styles.notice} aria-label={t('timezone_notice.label')}>
      <p>{t('timezone_notice.text', { browser, saved: savedTimezone })}</p>
      <div className={styles.actions}>
        <Link to={PATHS.account} state={{ suggestedTimezone: browser }} className={styles.action}>
          {t('timezone_notice.action')}
        </Link>
        <button type="button" className={styles.dismiss} onClick={dismiss}>
          {t('timezone_notice.dismiss')}
        </button>
      </div>
    </section>
  );
}
