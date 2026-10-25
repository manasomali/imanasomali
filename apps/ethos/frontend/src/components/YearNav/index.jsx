import { useTranslation } from 'react-i18next';
import { FiChevronLeft, FiChevronRight } from 'react-icons/fi';
import styles from './styles.module.css';

const ICON_SIZE = 20;

// Ano do calendário com os botões de ano anterior e seguinte, entre `min` e `max`
export default function YearNav({ year, min, max, onChange }) {
  const { t } = useTranslation();

  return (
    <div className={styles.nav}>
      <button
        type="button"
        className={styles.button}
        aria-label={t('calendar.previous_year', { year: year - 1 })}
        disabled={year <= min}
        onClick={() => onChange(year - 1)}
      >
        <FiChevronLeft aria-hidden size={ICON_SIZE} />
      </button>
      <h2 className={styles.year} aria-live="polite">
        {year}
      </h2>
      <button
        type="button"
        className={styles.button}
        aria-label={t('calendar.next_year', { year: year + 1 })}
        disabled={year >= max}
        onClick={() => onChange(year + 1)}
      >
        <FiChevronRight aria-hidden size={ICON_SIZE} />
      </button>
    </div>
  );
}
