import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { formatLongDay } from '../../lib/format';
import styles from './styles.module.css';

// Painel do dia escolhido no calendário (ao lado no desktop, acima no celular). Sem dia (outro
// ano, antes de escolher), mostra só a dica
export default function DayPanel({ day, children }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();

  return (
    <section className={styles.panel} aria-labelledby={headingId}>
      <h2 id={headingId} className={styles.heading}>
        {day ? formatLongDay(day, i18n.resolvedLanguage) : t('day_panel.title')}
      </h2>
      {day ? children : <p className={styles.hint}>{t('day_panel.choose')}</p>}
    </section>
  );
}
