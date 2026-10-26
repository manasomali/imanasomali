import { useEffect, useId, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import styles from './styles.module.css';

/**
 * Segundo passo de desmarcar um dia com observação, duração ou custo (markHasDetails em
 * src/lib/markDetails.js), que somem junto. Ao aparecer, o foco vai para "Cancelar" (a opção que
 * não perde nada; o grupo é lido com o aviso), e Esc cancela. Quem desenha devolve o foco ao botão
 * de desmarcar em `onConfirm` e `onCancel`. `confirmLabel`: nome acessível do botão de confirmar,
 * quando o texto sozinho não diz o hábito (aba principal).
 */
export default function ConfirmUnmark({ onConfirm, onCancel, confirmLabel }) {
  const { t } = useTranslation();
  const warningId = useId();
  const cancel = useRef(null);

  useEffect(() => {
    cancel.current?.focus();
  }, []);

  // Esc em qualquer dos dois botões cancela
  const onKeyDown = (event) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    onCancel();
  };

  return (
    <div role="group" aria-labelledby={warningId} className={styles.confirm}>
      <p id={warningId} className={styles.warning}>
        {t('confirm_unmark.warning')}
      </p>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.danger}
          aria-label={confirmLabel}
          onClick={onConfirm}
          onKeyDown={onKeyDown}
        >
          {t('confirm_unmark.confirm')}
        </button>
        <button
          type="button"
          ref={cancel}
          className={styles.button}
          onClick={onCancel}
          onKeyDown={onKeyDown}
        >
          {t('confirm_unmark.cancel')}
        </button>
      </div>
    </div>
  );
}
