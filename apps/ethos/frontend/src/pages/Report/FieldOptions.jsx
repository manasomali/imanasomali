import { useTranslation } from 'react-i18next';
import { REPORT_FIELDS } from '../../lib/export/options';
import styles from './styles.module.css';

// Informações mostradas no resumo e nos exports. Mudam na hora, sem buscar de novo: só o modelo
// do relatório (buildReport) é refeito
export default function FieldOptions({ options, onChange }) {
  const { t } = useTranslation();

  return (
    <fieldset className={`${styles.fieldset} ${styles.options}`}>
      <legend className={styles.legend}>{t('report.fields.label')}</legend>
      <p className={styles.hint}>{t('report.fields.hint')}</p>
      <ul className={styles.checks}>
        {REPORT_FIELDS.map((field) => (
          <li key={field}>
            <label className={styles.check}>
              <input
                type="checkbox"
                checked={options[field]}
                onChange={(event) => onChange({ ...options, [field]: event.target.checked })}
              />
              <span className={styles.checkText}>{t(`report.fields.${field}`)}</span>
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}
