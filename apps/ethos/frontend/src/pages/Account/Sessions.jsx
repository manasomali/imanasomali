import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { FiLogOut } from 'react-icons/fi';
import { useLogout, useLogoutAll } from '../../api/auth';
import ErrorMessage from '../../components/ErrorMessage';
import styles from './styles.module.css';

const ICON_SIZE = 18;

// Sair deste aparelho (POST /auth/logout) ou de todos (POST /auth/logout-all, para expulsar um
// aparelho perdido). Os dois vão para o login e limpam o cache; um de cada vez
export default function Sessions() {
  const { t } = useTranslation();
  const ids = useId();
  const signOut = useLogout();
  const signOutAll = useLogoutAll();
  const busy = signOut.isPending || signOutAll.isPending;
  const titleId = `${ids}-title`;
  const oneHelpId = `${ids}-one`;
  const allHelpId = `${ids}-all`;
  const error = signOut.error ?? signOutAll.error;

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.sectionTitle}>
        {t('pages.account.sessions.title')}
      </h2>
      <div className={styles.actions}>
        <div className={styles.action}>
          <button
            type="button"
            className={styles.button}
            disabled={busy}
            aria-describedby={oneHelpId}
            onClick={() => {
              signOutAll.reset();
              signOut.mutate();
            }}
          >
            <FiLogOut aria-hidden size={ICON_SIZE} />
            {t('pages.account.sessions.sign_out')}
          </button>
          <p id={oneHelpId} className={styles.muted}>
            {t('pages.account.sessions.sign_out_help')}
          </p>
        </div>
        <div className={styles.action}>
          <button
            type="button"
            className={styles.button}
            disabled={busy}
            aria-describedby={allHelpId}
            onClick={() => {
              signOut.reset();
              signOutAll.mutate();
            }}
          >
            <FiLogOut aria-hidden size={ICON_SIZE} />
            {t('pages.account.sessions.sign_out_all')}
          </button>
          <p id={allHelpId} className={styles.muted}>
            {t('pages.account.sessions.sign_out_all_help')}
          </p>
        </div>
      </div>
      <p className={styles.status} role="status">
        {busy ? t('pages.account.sessions.signing_out') : ''}
      </p>
      {error && <ErrorMessage error={error} />}
    </section>
  );
}
