import { useId } from 'react';
import { Link } from 'react-router';
import { Trans, useTranslation } from 'react-i18next';
import { useMe } from '../../api/account';
import PageTitle from '../../components/PageTitle';
import { contactEmail } from '../../lib/legal';
import { loginPath } from '../../lib/session';
import { BASENAME, PATHS } from '../../paths';
import Apps from './Apps';
import DeleteAccount from './DeleteAccount';
import LanguageForm from './LanguageForm';
import Sessions from './Sessions';
import TimezoneForm from './TimezoneForm';
import styles from './styles.module.css';

// Conta (`/imago/`), a mesma para todas as aplicações: email (só leitura; a troca é pelo suporte),
// as aplicações, idioma e fuso (o único lugar que chama PATCH /me), sair deste aparelho ou de todos
// e a exclusão da conta em passos. Com termos pendentes, a API recusa o PATCH /me: a tela pede o
// aceite e mostra só o que funciona sem ele (sair e excluir a conta)
export default function Account() {
  const { t } = useTranslation();
  const ids = useId();
  // RequireSession só desenha as rotas com o usuário carregado
  const me = useMe().data;
  const pending = me.terms_pending;
  const supportEmail = contactEmail(me.support_email);
  const title = t('pages.account.title');
  const emailTitleId = `${ids}-email`;
  const termsTitleId = `${ids}-terms`;

  return (
    <div className={styles.page}>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>

      {pending && (
        <section className={`${styles.panel} ${styles.notice}`} aria-labelledby={termsTitleId}>
          <h2 id={termsTitleId} className={styles.stepTitle}>
            {t('pages.account.terms_pending.title')}
          </h2>
          <p>{t('pages.account.terms_pending.text')}</p>
          <div className={styles.buttons}>
            <Link to={loginPath(`${BASENAME}${PATHS.account}`)} className={styles.primary}>
              {t('pages.account.terms_pending.accept')}
            </Link>
          </div>
        </section>
      )}

      <section className={styles.section} aria-labelledby={emailTitleId}>
        <h2 id={emailTitleId} className={styles.sectionTitle}>
          {t('pages.account.email.title')}
        </h2>
        <p className={`${styles.email} user-text`}>{me.email}</p>
        <p className={styles.muted}>
          <Trans
            i18nKey="pages.account.email.help"
            values={{ supportEmail }}
            components={{ mail: <a href={`mailto:${supportEmail}`}>{supportEmail}</a> }}
          />
        </p>
        <p className={styles.muted}>{t('pages.account.email.lost_access')}</p>
      </section>

      {!pending && <Apps me={me} />}
      {!pending && <LanguageForm me={me} />}
      {!pending && <TimezoneForm me={me} />}
      <Sessions />
      <DeleteAccount me={me} />
    </div>
  );
}
