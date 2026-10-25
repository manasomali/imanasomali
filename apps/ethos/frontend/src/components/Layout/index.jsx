import { useRef } from 'react';
import { Link, Outlet, ScrollRestoration } from 'react-router';
import { useTranslation } from 'react-i18next';
import { PATHS } from '../../paths';
import Banner from '../Banner';
import Menu from '../Menu';
import styles from './styles.module.css';

// Moldura de todas as telas: link de pular para o conteúdo, menu, banner do admin (também nas
// telas sem login), <main> e rodapé
export default function Layout() {
  const { t } = useTranslation();
  const mainRef = useRef(null);

  return (
    <>
      <a className={styles.skipLink} href="#content">
        {t('a11y.skip_to_content')}
      </a>
      <Menu />
      <Banner onDismiss={() => mainRef.current?.focus()} />
      <main ref={mainRef} id="content" tabIndex={-1} className={styles.main}>
        <Outlet />
      </main>
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <p>{t('footer.tagline')}</p>
          <nav aria-label={t('footer.legal')}>
            <ul className={styles.footerLinks}>
              <li>
                <Link to={PATHS.terms}>{t('footer.terms')}</Link>
              </li>
              <li>
                <Link to={PATHS.privacy}>{t('footer.privacy')}</Link>
              </li>
              <li>
                <a href="/">manasomali.com</a>
              </li>
            </ul>
          </nav>
        </div>
      </footer>
      <ScrollRestoration />
    </>
  );
}
