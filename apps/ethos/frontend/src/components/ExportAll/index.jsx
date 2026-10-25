import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { FiDownload } from 'react-icons/fi';
import { useMe } from '../../api/auth';
import { EXPORT_ALL_FORMATS, exportAllFile } from '../../api/report';
import { downloadBlob } from '../../lib/export/share';
import ErrorMessage from '../ErrorMessage';
import styles from './styles.module.css';

const ICON_SIZE = 18;

// "Exportar tudo": todos os hábitos (inclusive arquivados), todo o período e todas as informações,
// em JSON ou CSV, baixado no navegador. Fica na tela do relatório e na conta, antes de excluir
// (ETH-38). Só dentro de RequireSession (usa o fuso da conta). Um export por vez
export default function ExportAll() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const timeZone = useMe().data.timezone;
  // null, {working: formato}, {done: true} ou {error}
  const [state, setState] = useState(null);
  const working = Boolean(state?.working);

  const run = async (format) => {
    setState({ working: format });
    try {
      const file = await exportAllFile(queryClient, { timeZone, format, t });
      downloadBlob(file, file.name);
      setState({ done: true });
    } catch (error) {
      setState({ error });
    }
  };

  return (
    <div className={styles.exportAll}>
      <p className={styles.text}>{t('export_all.text')}</p>
      <div className={styles.buttons}>
        {EXPORT_ALL_FORMATS.map((format) => (
          <button
            key={format}
            type="button"
            className={styles.button}
            onClick={() => run(format)}
            disabled={working}
          >
            <FiDownload aria-hidden size={ICON_SIZE} />
            {t(`export_all.${format}`)}
          </button>
        ))}
      </div>
      <p className={styles.status} role="status">
        {working && t('export_all.working')}
        {state?.done && t('export_all.done')}
      </p>
      {state?.error && <ErrorMessage error={state.error} />}
    </div>
  );
}
