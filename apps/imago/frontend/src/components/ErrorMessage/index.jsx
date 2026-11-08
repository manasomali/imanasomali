import { useTranslation } from 'react-i18next';
import { errorKey } from '../../lib/errors';
import styles from './styles.module.css';

// Mensagem de um erro da API, traduzida pelo código (errors.<codigo>), com "tentar de novo"
// opcional. Ex.: 429 mostra "tente mais tarde"
export default function ErrorMessage({ error, onRetry }) {
  const { t, i18n } = useTranslation();

  return (
    <div role="alert" className={styles.error}>
      <p>{t(errorKey(error, (key) => i18n.exists(key)))}</p>
      {onRetry && (
        <button type="button" className={styles.retry} onClick={onRetry}>
          {t('common.retry')}
        </button>
      )}
    </div>
  );
}
