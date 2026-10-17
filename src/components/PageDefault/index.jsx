import { useEffect } from 'react';
import { useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import Menu from '../Menu';
import Footer from '../Footer';
import styles from './styles.module.css';

const SITE_NAME = 'Matheus Nascimento';

// `title` sets the browser tab title (React 19 hoists <title> into <head>).
// `width` picks the content column: "text" for reading, "wide" for grids.
function PageDefault({ title, width = 'text', centered = false, children }) {
  const { t } = useTranslation();
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <>
      <title>{title ? `${title} | ${SITE_NAME}` : `${SITE_NAME} | ${t('meta.tagline')}`}</title>
      <a className={styles.skipLink} href="#content">{t('a11y.skip_to_content')}</a>
      <Menu />
      <main
        id="content"
        tabIndex={-1}
        className={`${styles.main} ${styles[width]} ${centered ? styles.centered : ''}`}
      >
        {children}
      </main>
      <Footer />
    </>
  );
}

export default PageDefault;
