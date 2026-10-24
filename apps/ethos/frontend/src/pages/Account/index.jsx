import { useTranslation } from 'react-i18next';
import PageTitle from '../../components/PageTitle';
import styles from '../page.module.css';

// Provisória: destino do aviso de fuso. Idioma, fuso, sair e exclusão entram na ETH-38
export default function Account() {
  const { t } = useTranslation();
  const title = t('pages.account.title');

  return (
    <>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.muted}>{t('common.coming_soon')}</p>
    </>
  );
}
