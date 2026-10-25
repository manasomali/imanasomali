import { useId } from 'react';
import { useLocation } from 'react-router';
import { Trans, useTranslation } from 'react-i18next';
import { useMe } from '../../api/auth';
import PageTitle from '../../components/PageTitle';
import { SUPPORT_EMAIL } from '../../lib/legal';
import { isValidTimezone } from '../../lib/time';
import DeleteAccount from './DeleteAccount';
import LanguageForm from './LanguageForm';
import Sessions from './Sessions';
import TimezoneForm from './TimezoneForm';
import styles from './styles.module.css';

/** Fuso que o aviso de fuso (TimezoneNotice) mandou em state.suggestedTimezone, se for válido. */
function suggestedTimezone(location) {
  const value = location.state?.suggestedTimezone;
  return isValidTimezone(value) ? value : null;
}

// Conta (`/conta`): email (só leitura; a troca é pelo suporte), idioma e fuso (o único lugar que
// chama PATCH /auth/me), sair deste aparelho ou de todos, e a exclusão da conta em passos
export default function Account() {
  const { t } = useTranslation();
  const location = useLocation();
  const ids = useId();
  // RequireSession só desenha as rotas com o usuário carregado
  const me = useMe().data;
  const title = t('pages.account.title');
  const emailTitleId = `${ids}-email`;

  return (
    <div className={styles.page}>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>

      <section className={styles.section} aria-labelledby={emailTitleId}>
        <h2 id={emailTitleId} className={styles.sectionTitle}>
          {t('pages.account.email.title')}
        </h2>
        <p className={styles.email}>{me.email}</p>
        <p className={styles.muted}>
          <Trans
            i18nKey="pages.account.email.help"
            values={{ supportEmail: SUPPORT_EMAIL }}
            components={{ mail: <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a> }}
          />
        </p>
        <p className={styles.muted}>{t('pages.account.email.lost_access')}</p>
      </section>

      <LanguageForm me={me} />
      <TimezoneForm me={me} suggested={suggestedTimezone(location)} />
      <Sessions />
      <DeleteAccount me={me} />
    </div>
  );
}
