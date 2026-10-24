import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import PageTitle from '../../components/PageTitle';
import { PATHS } from '../../paths';
import styles from '../page.module.css';

export default function NotFound() {
  const { t } = useTranslation();
  const title = t('pages.not_found.title');

  return (
    <>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.muted}>{t('pages.not_found.text')}</p>
      <p>
        <Link to={PATHS.home}>{t('pages.not_found.back_home')}</Link>
      </p>
    </>
  );
}
