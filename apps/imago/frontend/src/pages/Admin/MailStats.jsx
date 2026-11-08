import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { useMailStats } from '../../api/admin';
import ErrorMessage from '../../components/ErrorMessage';
import { MAIL_KINDS, mailTable, mailWindow } from '../../lib/mail';
import styles from './admin.module.css';

// Uma janela do teto (24 h ou 1 h): quantos saíram, quanto falta para o teto e para as
// notificações pararem (o fim de cada janela fica só para códigos e emails de conta)
function MailWindow({ name, stats }) {
  const { t } = useTranslation();
  const values = mailWindow(stats);
  let state = null;
  if (values.full) state = t('admin.mail.full');
  else if (values.notificationsStopped) state = t('admin.mail.notifications_stopped');

  return (
    <div>
      <dt>{t(`admin.mail.${name}`)}</dt>
      <dd>
        {t('admin.mail.window', {
          sent: values.sent,
          limit: values.limit,
          remaining: values.remaining,
        })}
      </dd>
      <dd>
        {t('admin.mail.notification_window', {
          limit: values.notificationLimit,
          remaining: values.notificationRemaining,
        })}
      </dd>
      {state && <dd className={styles.strong}>{state}</dd>}
    </div>
  );
}

// Envios de email (GET /admin/mail): quantos cada aplicação mandou nas últimas 24 h, por tipo, e
// quanto falta para o teto compartilhado, na janela de 24 h e na de 1 h
export default function MailStats() {
  const { t, i18n } = useTranslation();
  const id = useId();
  const stats = useMailStats();
  const titleId = `${id}-title`;
  // Nome de cada aplicação no translation.json; o próprio imago e uma aplicação nova, o nome cru
  const appName = (app) => (i18n.exists(`apps.${app}.name`) ? t(`apps.${app}.name`) : app);

  let content;
  if (stats.isPending) {
    content = <p role="status">{t('common.loading')}</p>;
  } else if (stats.isError) {
    content = <ErrorMessage error={stats.error} onRetry={() => stats.refetch()} />;
  } else {
    const data = stats.data ?? {};
    const { rows, totals } = mailTable(data.by_app);
    content = (
      <>
        <dl className={styles.details}>
          <MailWindow name="day" stats={data.day} />
          <MailWindow name="hour" stats={data.hour} />
        </dl>
        {rows.length === 0 ? (
          <p className={styles.muted}>{t('admin.mail.empty')}</p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <caption>{t('admin.mail.caption', { hours: data.window_hours ?? 24 })}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('admin.mail.app')}</th>
                  {MAIL_KINDS.map((kind) => (
                    <th key={kind} scope="col">
                      {t(`admin.mail.kind.${kind}`)}
                    </th>
                  ))}
                  <th scope="col">{t('admin.mail.total')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.app}>
                    <th scope="row">{appName(row.app)}</th>
                    {MAIL_KINDS.map((kind) => (
                      <td key={kind}>{row[kind]}</td>
                    ))}
                    <td>{row.total}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">{t('admin.mail.total')}</th>
                  {MAIL_KINDS.map((kind) => (
                    <td key={kind}>{totals[kind]}</td>
                  ))}
                  <td>{totals.total}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </>
    );
  }

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.subtitle}>
        {t('admin.mail.title')}
      </h2>
      <p className={styles.hint}>{t('admin.mail.intro')}</p>
      {content}
    </section>
  );
}
