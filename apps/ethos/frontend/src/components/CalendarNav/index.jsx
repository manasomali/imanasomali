import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { FiChevronLeft, FiChevronRight } from 'react-icons/fi';
import { RANGE_KINDS, calendarRange, shiftAnchor } from '../../lib/calendarRange';
import { formatPeriod } from '../../lib/format';
import styles from './styles.module.css';

const ICON_SIZE = 20;

// Navegação do calendário: o nome da faixa (`range`, de calendarRange) entre os botões de anterior
// e próximo, que andam pela unidade da faixa (mês, 3 meses ou ano), e a escolha do tipo da faixa.
// `previous`/`next`: as âncoras vizinhas (useCalendarParams), null desabilita o botão;
// `onMove(anchor)` e `onKindChange(kind)` vêm do useCalendarParams
export default function CalendarNav({ range, previous, next, onMove, onKindChange }) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const name = useId();
  const { kind, anchor } = range;

  // Nome do botão com a faixa de destino; desabilitado, a que viria depois dos limites
  const stepLabel = (step, target) => {
    const destination = calendarRange(kind, target ?? shiftAnchor(kind, anchor, step));
    return t(`calendar.${step < 0 ? 'previous' : 'next'}.${kind}`, {
      period: formatPeriod(destination, language),
    });
  };

  return (
    <div className={styles.nav}>
      <div className={styles.step}>
        <button
          type="button"
          className={styles.button}
          aria-label={stepLabel(-1, previous)}
          disabled={previous === null}
          onClick={() => onMove(previous)}
        >
          <FiChevronLeft aria-hidden size={ICON_SIZE} />
        </button>
        <h2 className={styles.period} aria-live="polite">
          {formatPeriod(range, language)}
        </h2>
        <button
          type="button"
          className={styles.button}
          aria-label={stepLabel(1, next)}
          disabled={next === null}
          onClick={() => onMove(next)}
        >
          <FiChevronRight aria-hidden size={ICON_SIZE} />
        </button>
      </div>
      <fieldset className={styles.kinds}>
        <legend className="visually-hidden">{t('calendar.range.label')}</legend>
        {RANGE_KINDS.map((value) => (
          <label key={value} className={styles.kind}>
            <input
              type="radio"
              name={name}
              value={value}
              className={`visually-hidden ${styles.radio}`}
              checked={value === kind}
              onChange={() => onKindChange(value)}
            />
            <span className={styles.option}>{t(`calendar.range.${value}`)}</span>
          </label>
        ))}
      </fieldset>
    </div>
  );
}
