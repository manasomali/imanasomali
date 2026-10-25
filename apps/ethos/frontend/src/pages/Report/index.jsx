import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMe } from '../../api/auth';
import { useHabits } from '../../api/habits';
import { useReportData } from '../../api/report';
import ErrorMessage from '../../components/ErrorMessage';
import ExportAll from '../../components/ExportAll';
import { WithHelp } from '../../components/HelpLink';
import PageTitle from '../../components/PageTitle';
import { DEFAULT_OPTIONS } from '../../lib/export/options';
import { parseReportSearch } from '../../lib/export/params';
import { buildReport } from '../../lib/export/report';
import { formatShortDay } from '../../lib/format';
import { today } from '../../lib/time';
import { reportPath } from '../../paths';
import FieldOptions from './FieldOptions';
import HabitSummary from './HabitSummary';
import ReportExports from './ReportExports';
import ReportForm from './ReportForm';
import styles from './styles.module.css';

const NO_HABITS = [];

// Relatório (`/relatorio?from=&to=&habit_id=`): período (até 5 anos) e hábitos na URL, as
// informações mostradas escolhidas na tela. Mostra o resumo de cada hábito e exporta imagem, CSV e
// JSON, tudo gerado no navegador (src/lib/export/). No fim, o "exportar tudo"
export default function Report() {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const title = t('pages.report.title');
  // RequireSession só desenha as rotas com o usuário carregado
  const timeZone = useMe().data.timezone;
  const current = today(timeZone);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const params = useMemo(() => parseReportSearch(searchParams, current), [searchParams, current]);
  const [options, setOptions] = useState(DEFAULT_OPTIONS);

  const active = useHabits();
  const archived = useHabits({ archived: true });
  const habits = useMemo(
    () => [...(active.data ?? NO_HABITS), ...(archived.data ?? NO_HABITS)],
    [active.data, archived.data],
  );
  const habitsError = active.error ?? archived.error;
  const habitsLoaded = active.data !== undefined && archived.data !== undefined;

  const query = useReportData({ ...params, timeZone });
  const report = useMemo(
    () =>
      query.data
        ? buildReport(query.data, options, { today: today(query.data.timezone) })
        : null,
    [query.data, options],
  );

  const onSubmit = (next) => navigate(reportPath(next));

  let content;
  if (!report) {
    content = query.isPending ? (
      <p role="status">{t('report.loading')}</p>
    ) : (
      <ErrorMessage error={query.error} onRetry={() => query.refetch()} />
    );
  } else if (report.habits.length === 0) {
    content = <p className={styles.muted}>{t('report.empty')}</p>;
  } else {
    content = (
      <>
        <ul className={styles.summaries} aria-label={t('report.summaries')}>
          {report.habits.map((item) => (
            <HabitSummary key={item.habit.id} item={item} />
          ))}
        </ul>
        <ReportExports report={report} />
      </>
    );
  }

  return (
    <>
      <PageTitle title={title} />
      <WithHelp section="report" topic={title}>
        <h1 className={styles.title}>{title}</h1>
      </WithHelp>
      <p className={styles.intro}>{t('report.intro')}</p>

      <ReportForm
        // Voltar no histórico (outra URL) recomeça o formulário com os valores dela
        key={searchParams.toString()}
        params={params}
        today={current}
        timeZone={timeZone}
        habits={habits}
        habitsLoaded={habitsLoaded}
        habitsError={habitsError}
        onRetryHabits={() => {
          if (active.error) active.refetch();
          if (archived.error) archived.refetch();
        }}
        onSubmit={onSubmit}
      />
      <FieldOptions options={options} onChange={setOptions} />

      <section className={styles.section} aria-labelledby="report-results">
        <h2 id="report-results" className={styles.subtitle}>
          {t('report.results', {
            from: formatShortDay(params.from, language),
            to: formatShortDay(params.to, language),
          })}
        </h2>
        {query.isFetching && report && (
          <p className={styles.muted} role="status">
            {t('report.updating')}
          </p>
        )}
        {content}
      </section>

      <section className={styles.section} aria-labelledby="report-export-all">
        <h2 id="report-export-all" className={styles.subtitle}>
          {t('export_all.title')}
        </h2>
        <ExportAll />
      </section>
    </>
  );
}
