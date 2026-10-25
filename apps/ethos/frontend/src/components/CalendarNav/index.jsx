import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { FiChevronLeft, FiChevronRight, FiColumns, FiGrid } from 'react-icons/fi';
import { RANGE_KINDS, calendarRange, shiftAnchor } from '../../lib/calendarRange';
import { CALENDAR_VIEWS } from '../../lib/calendarView';
import { formatPeriod } from '../../lib/format';
import styles from './styles.module.css';

const ICON_SIZE = 20;
const VIEW_ICON_SIZE = 16;
const VIEW_ICONS = { grid: FiGrid, columns: FiColumns };

// Navegação do calendário: o nome da faixa (`range`, de calendarRange) entre os botões de anterior
// e próximo, que andam pela unidade da faixa (mês, 3 meses ou ano), a escolha do tipo da faixa e a
// da visão (`view`: grade ou colunas). `previous`/`next`: as âncoras vizinhas (useCalendarParams),
// null desabilita o botão; `onMove(anchor)`, `onKindChange(kind)` e `onViewChange(view)` vêm do
// useCalendarParams
export default function CalendarNav({
  range,
  view,
  previous,
  next,
  onMove,
  onKindChange,
  onViewChange,
}) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const kindName = useId();
  const viewName = useId();
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
      <div className={styles.choices}>
        <Choice
          legend={t('calendar.range.label')}
          name={kindName}
          options={RANGE_KINDS.map((value) => ({ value, label: t(`calendar.range.${value}`) }))}
          value={kind}
          onChange={onKindChange}
        />
        <Choice
          legend={t('calendar.view.label')}
          name={viewName}
          options={CALENDAR_VIEWS.map((value) => ({
            value,
            label: t(`calendar.view.${value}`),
            Icon: VIEW_ICONS[value],
          }))}
          value={view}
          onChange={onViewChange}
        />
      </div>
    </div>
  );
}

// Botões de rádio num bloco segmentado. `options`: `{value, label, Icon?}`
function Choice({ legend, name, options, value, onChange }) {
  return (
    <fieldset className={styles.choice}>
      <legend className="visually-hidden">{legend}</legend>
      {options.map(({ value: option, label, Icon }) => (
        <label key={option} className={styles.item}>
          <input
            type="radio"
            name={name}
            value={option}
            className={`visually-hidden ${styles.radio}`}
            checked={option === value}
            onChange={() => onChange(option)}
          />
          <span className={styles.option}>
            {Icon && <Icon aria-hidden size={VIEW_ICON_SIZE} />}
            {label}
          </span>
        </label>
      ))}
    </fieldset>
  );
}
