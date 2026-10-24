import { useTranslation } from 'react-i18next';
import Link from '../Link';
import styles from './styles.module.css';

function Footer() {
  const { t } = useTranslation();
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <p>
          {t('components.footer.line1')}
          {' '}
          Matheus Nascimento
        </p>
        <p>
          {t('components.footer.line2')}
          {' '}
          <Link href="https://vite.dev/" external>Vite</Link>
          {' + '}
          <Link href="https://react.dev/" external>React</Link>
        </p>
        <p>
          {t('components.footer.line3')}
          {' '}
          <Link href="https://github.com/naro143/hugo-coder-portfolio" external>Yusuke Ishimi</Link>
        </p>
      </div>
    </footer>
  );
}

export default Footer;
