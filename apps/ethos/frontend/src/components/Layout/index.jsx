import { Outlet, ScrollRestoration } from 'react-router';
import { useTranslation } from 'react-i18next';
import Menu from '../Menu';
import styles from './styles.module.css';

// Moldura de todas as telas: link de pular para o conteúdo, menu, <main> e rodapé
export default function Layout() {
  const { t } = useTranslation();

  return (
    <>
      <a className={styles.skipLink} href="#content">
        {t('a11y.skip_to_content')}
      </a>
      <Menu />
      <main id="content" tabIndex={-1} className={styles.main}>
        <Outlet />
      </main>
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <p>{t('footer.tagline')}</p>
          <p>
            <a href="/">manasomali.com</a>
          </p>
        </div>
      </footer>
      <ScrollRestoration />
    </>
  );
}
