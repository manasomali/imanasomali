import { useTranslation } from 'react-i18next';
import PageTitle from '../../components/PageTitle';
import styles from '../page.module.css';

// Provisória: o calendário de hábitos entra na ETH-32
export default function Home() {
  const { t } = useTranslation();
  const title = t('pages.home.title');

  return (
    <>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.muted}>{t('common.coming_soon')}</p>
    </>
  );
}
