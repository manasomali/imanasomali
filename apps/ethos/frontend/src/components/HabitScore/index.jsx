import { useTranslation } from 'react-i18next';
import styles from './styles.module.css';

// Pontuação do hábito, só com a pontuação ligada: o valor (ou "sem dados", até fechar o primeiro
// período completo depois da criação), o limite e o sucesso/falha ("sem dados" não é nenhum dos
// dois). Calculada pela API no fuso da conta
export default function HabitScore({ habit }) {
  const { t } = useTranslation();
  if (!habit.score_enabled || !habit.score) return null;
  const { value, success } = habit.score;

  return (
    <dl className={styles.score}>
      <div>
        <dt>{t('habit.score.label')}</dt>
        <dd>{value === null ? t('habit.score.no_data') : t('habit.score.value', { value })}</dd>
      </div>
      <div>
        <dt>{t('habit.score.threshold')}</dt>
        <dd>{habit.score_threshold}</dd>
      </div>
      {success !== null && (
        <div>
          <dt>{t('habit.score.result')}</dt>
          <dd className={styles.result} data-success={success}>
            {success ? t('habit.score.success') : t('habit.score.failure')}
          </dd>
        </div>
      )}
    </dl>
  );
}
