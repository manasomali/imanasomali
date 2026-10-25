import { useTranslation } from 'react-i18next';
import HabitSwatch from '../../components/HabitSwatch';
import { formatMoney } from '../../lib/money';
import styles from './styles.module.css';

function Detail({ label, children }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

// Resumo de um hábito no relatório (item do modelo de buildReport): marcações e dias do período,
// meta e períodos encerrados cumpridos e, quando escolhidos e ligados no hábito, pontuação, tempo,
// gasto, limite, recompensa e punição
export default function HabitSummary({ item }) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const { habit, goal, score, cost } = item;
  const money = (cents) => formatMoney(cents, language);
  const period = t(`report.period_names.${goal.period}`);
  const goalText = habit.duration_enabled
    ? t(`report.goal_minutes.${goal.type}`, { count: goal.count, minutes: habit.duration_minutes, period })
    : t(`report.goal.${goal.type}`, { count: goal.count, period });
  const latest = cost?.latestLimit;

  return (
    <li className={styles.card}>
      <h3 className={styles.cardTitle}>
        <HabitSwatch className={styles.swatch} color={habit.color} />
        {habit.code ? `${habit.code} · ${habit.name}` : habit.name}
        {habit.status !== 'active' && (
          <span className={styles.badge}>{t(`report.status.${habit.status}`)}</span>
        )}
      </h3>
      <dl className={styles.details}>
        <Detail label={t('report.marks')}>{item.marks.length}</Detail>
        <Detail label={t('report.days')}>{item.days.size}</Detail>
        <Detail label={t('report.goal_label')}>{goalText}</Detail>
        <Detail label={t('report.periods')}>
          {item.closedPeriods > 0
            ? t('report.periods_value', { met: item.metPeriods, total: item.closedPeriods })
            : t('report.no_periods')}
        </Detail>
        {score && (
          <Detail label={t('report.score')}>
            {score.value === null
              ? t('report.score_no_data')
              : t('report.score_value', { value: score.value, threshold: score.threshold })}
          </Detail>
        )}
        {score && score.success !== null && (
          <Detail label={t('report.result')}>
            {score.success ? t('report.success') : t('report.failure')}
          </Detail>
        )}
        {item.durationMinutes !== null && (
          <Detail label={t('report.duration')}>
            {t('report.minutes', { count: item.durationMinutes })}
          </Detail>
        )}
        {cost && <Detail label={t('report.spend')}>{money(cost.spendCents)}</Detail>}
        {cost && cost.limitCents !== null && cost.limitPeriod && (
          <Detail label={t('report.limit')}>
            {t('report.limit_value', {
              limit: money(cost.limitCents),
              period: t(`report.period_names.${cost.limitPeriod}`),
            })}
            {latest && (
              <>
                <br />
                {latest.limit_percent === null
                  ? t('report.limit_latest', { spend: money(latest.spend_cents) })
                  : t('report.limit_latest_percent', {
                      spend: money(latest.spend_cents),
                      percent: latest.limit_percent,
                    })}
              </>
            )}
          </Detail>
        )}
        {item.show.reward && item.reward && <Detail label={t('report.reward')}>{item.reward}</Detail>}
        {item.show.punishment && item.punishment && (
          <Detail label={t('report.punishment')}>{item.punishment}</Detail>
        )}
      </dl>
    </li>
  );
}
