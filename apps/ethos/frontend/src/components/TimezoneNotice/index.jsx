import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { browserTimezone } from '../../lib/time';
import { dismissTimezoneNotice, shouldSuggestTimezone } from '../../lib/timezoneNotice';
import { IMAGO_PATHS } from '../../paths';
import styles from './styles.module.css';

// Sugere trocar o fuso da conta quando o navegador está noutro fuso. Só sugere: a troca é feita na
// tela de conta do imago (/imago/), a conta única do manasomali.com, por um link comum
export default function TimezoneNotice({ savedTimezone }) {
  const { t } = useTranslation();
  const [browser] = useState(browserTimezone);
  const [dismissed, setDismissed] = useState(false);

  if (dismissed || !shouldSuggestTimezone(savedTimezone, browser)) return null;

  const dismiss = () => {
    dismissTimezoneNotice(savedTimezone, browser);
    setDismissed(true);
  };

  return (
    <section className={styles.notice} aria-label={t('timezone_notice.label')}>
      <p>{t('timezone_notice.text', { browser, saved: savedTimezone })}</p>
      <div className={styles.actions}>
        <a href={IMAGO_PATHS.account} className={styles.action}>
          {t('timezone_notice.action')}
        </a>
        <button type="button" className={styles.dismiss} onClick={dismiss}>
          {t('timezone_notice.dismiss')}
        </button>
      </div>
    </section>
  );
}
