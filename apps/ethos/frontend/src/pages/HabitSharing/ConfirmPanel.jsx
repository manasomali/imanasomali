import { useEffect, useId, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import ErrorMessage from '../../components/ErrorMessage';
import styles from '../sharing.module.css';

// Confirmação de uma ação que não se desfaz (remover membro, sair do hábito), aberta logo abaixo do
// botão que a pediu. O foco vai para "Cancelar" (a opção segura), então um Enter a mais não confirma
export default function ConfirmPanel({ id, title, children, confirmLabel, pending, error, onConfirm, onCancel }) {
  const { t } = useTranslation();
  const titleId = useId();
  const cancelRef = useRef(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  return (
    <div id={id} role="group" aria-labelledby={titleId} className={styles.confirm}>
      <p id={titleId} className={styles.confirmTitle}>
        {title}
      </p>
      {children}
      {error && <ErrorMessage error={error} />}
      <div className={styles.buttons}>
        <button type="button" className={styles.primary} disabled={pending} onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button ref={cancelRef} type="button" className={styles.button} onClick={onCancel}>
          {t('sharing.cancel')}
        </button>
      </div>
    </div>
  );
}
