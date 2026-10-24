import { Link as RouterLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import PageDefault from '../../components/PageDefault';
import Title from '../../components/Title';
import Link from '../../components/Link';
import styles from './styles.module.css';

function Page404() {
  const { t } = useTranslation();
  return (
    <PageDefault title={t('pages.page404.title')} centered>
      <Title>{t('pages.page404.title')}</Title>
      <p>{t('pages.page404.message')}</p>
      <p className={styles.back}>
        <Link as={RouterLink} to="/">{t('pages.page404.back')}</Link>
      </p>
      <img
        className={styles.gif}
        src="https://media.tenor.com/2g8VHWu_d4UAAAAC/cake-i-do-not-want-cake.gif"
        alt=""
        width="498"
        height="280"
      />
    </PageDefault>
  );
}

export default Page404;
