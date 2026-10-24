import { useTranslation } from 'react-i18next';
import PageTitle from '../../components/PageTitle';
import styles from '../page.module.css';

// Provisória: destino do 401. O formulário de email e código entra na ETH-31, que volta para
// returnPath(location) (src/lib/session.js) depois do login
export default function Login() {
  const { t } = useTranslation();
  const title = t('pages.login.title');

  return (
    <>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.muted}>{t('common.coming_soon')}</p>
    </>
  );
}
