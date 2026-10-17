import { useTranslation } from 'react-i18next';
import Link from '../Link';
import styles from './styles.module.css';

function Summary() {
  const { t } = useTranslation();
  return (
    <div className={styles.summary}>
      <p>
        {t('components.summary.line1.sector1')}
        <Link href="http://florianopolis.ifsc.edu.br" external>{t('components.summary.line1.IFSC')}</Link>
        {t('components.summary.line1.sector2')}
        <Link href="https://gese.florianopolis.ifsc.edu.br" external>{t('components.summary.line1.GESE')}</Link>
        {t('components.summary.line1.sector3')}
        <Link href="https://www.digitalhouse.com/br" external>{t('components.summary.line1.DH')}</Link>
        {t('components.summary.line1.sector4')}
        <Link href="https://www.opet.com.br" external>{t('components.summary.line1.Opet')}</Link>
      </p>
      <p>
        {t('components.summary.line2.sector1')}
        <Link href="https://www.byne.com.br" external>{t('components.summary.line2.BYNE')}</Link>
        {t('components.summary.line2.sector2')}
        <Link href="https://www.engie.com.br" external>{t('components.summary.line2.engie')}</Link>
        {t('components.summary.line2.sector3')}
        <Link href="http://www.ons.org.br" external>{t('components.summary.line2.ONS')}</Link>
        {t('components.summary.line2.sector4')}
      </p>
      <p>{t('components.summary.line3')}</p>
    </div>
  );
}

export default Summary;
