import { useId, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FiEye } from 'react-icons/fi';
import { useAccountHabits } from '../../api/admin';
import { useMe } from '../../api/auth';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import { parseUserId } from '../../lib/admin';
import { ApiError } from '../../lib/api';
import { formatDateTime } from '../../lib/datetime';
import { formatMoney } from '../../lib/money';
import { PATHS } from '../../paths';
import AdminNav from './AdminNav';
import styles from './admin.module.css';

const NOT_FOUND = new ApiError(404, 'not_found');

function Detail({ label, children }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function HabitCard({ habit, date, money }) {
  const { t } = useTranslation();
  const period = (value) => t(`admin.user_habits.period.${value}`);

  return (
    <li className={styles.card}>
      <h3 className={styles.cardTitle}>
        <span className={styles.swatch} data-habit-color={habit.color} aria-hidden="true" />
        <span className="user-text">{habit.name}</span>
        {habit.code && <> <span className={styles.badge}>{habit.code}</span></>}{' '}
        <span className={styles.badge}>{t(`admin.user_habits.status.${habit.status}`)}</span>
      </h3>
      {habit.description && <p>{habit.description}</p>}
      <dl className={styles.details}>
        <Detail label={t('admin.user_habits.goal')}>
          {t(`admin.user_habits.goal_${habit.goal_type}`, {
            n: habit.goal_count,
            period: period(habit.goal_period),
          })}
        </Detail>
        <Detail label={t('admin.user_habits.score')}>
          {habit.score_enabled
            ? t('admin.user_habits.score_on', { threshold: habit.score_threshold })
            : t('admin.user_habits.off')}
        </Detail>
        {habit.duration_enabled && (
          <Detail label={t('admin.user_habits.duration')}>
            {habit.duration_minutes === null
              ? t('admin.user_habits.per_mark')
              : t('admin.user_habits.minutes', { n: habit.duration_minutes })}
          </Detail>
        )}
        {habit.cost_enabled && (
          <Detail label={t('admin.user_habits.cost')}>
            {habit.cost_level === 'habit' && habit.cost_cents !== null
              ? money(habit.cost_cents)
              : t('admin.user_habits.per_mark')}
          </Detail>
        )}
        {habit.cost_enabled && habit.cost_limit_cents !== null && (
          <Detail label={t('admin.user_habits.cost_limit')}>
            {t('admin.user_habits.per_period', {
              value: money(habit.cost_limit_cents),
              period: period(habit.cost_limit_period),
            })}
          </Detail>
        )}
        {habit.reward && <Detail label={t('admin.user_habits.reward')}>{habit.reward}</Detail>}
        {habit.punishment && <Detail label={t('admin.user_habits.punishment')}>{habit.punishment}</Detail>}
        <Detail label={t('admin.user_habits.created')}>{date(habit.created_at)}</Detail>
      </dl>
    </li>
  );
}

function Content({ userId, timeZone }) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const [habitId, setHabitId] = useState(null);
  const content = useAccountHabits(userId, habitId);

  if (content.isPending) return <p role="status">{t('common.loading')}</p>;
  if (content.isError && !content.data) {
    return <ErrorMessage error={content.error} onRetry={() => content.refetch()} />;
  }

  const language = i18n.resolvedLanguage;
  const date = (value) => formatDateTime(value, timeZone, language);
  const money = (cents) => formatMoney(cents, language);
  const [first] = content.data.pages;
  const { user, habits } = first;
  const names = new Map(habits.map((habit) => [habit.id, habit.name]));
  const marks = content.data.pages.flatMap((page) => page.marks);

  return (
    <>
      <section className={styles.section} aria-labelledby={`${id}-account`}>
        <h2 id={`${id}-account`} className={styles.subtitle}>
          {user.email}
        </h2>
        <dl className={styles.details}>
          <Detail label={t('admin.accounts.status')}>
            {user.is_active ? t('admin.accounts.status_active') : t('admin.accounts.status_blocked')}
          </Detail>
          <Detail label={t('admin.user_habits.timezone')}>{user.timezone}</Detail>
          <Detail label={t('admin.accounts.created')}>{date(user.created_at)}</Detail>
          <Detail label={t('admin.accounts.last_login')}>
            {user.last_login_at ? date(user.last_login_at) : t('admin.accounts.never')}
          </Detail>
        </dl>
      </section>

      <section className={styles.section} aria-labelledby={`${id}-habits`}>
        <h2 id={`${id}-habits`} className={styles.subtitle}>
          {t('admin.user_habits.habits')}
        </h2>
        {habits.length === 0 ? (
          <p className={styles.muted}>{t('admin.user_habits.no_habits')}</p>
        ) : (
          <ul className={styles.list}>
            {habits.map((habit) => (
              <HabitCard key={habit.id} habit={habit} date={date} money={money} />
            ))}
          </ul>
        )}
      </section>

      <section className={styles.section} aria-labelledby={`${id}-marks`}>
        <h2 id={`${id}-marks`} className={styles.subtitle}>
          {t('admin.user_habits.marks')}
        </h2>
        {habits.length > 0 && (
          <div className={`${styles.field} ${styles.filter}`}>
            <label className={styles.label} htmlFor={`${id}-habit`}>
              {t('admin.user_habits.habit_filter')}
            </label>
            <select
              id={`${id}-habit`}
              className={styles.input}
              value={habitId ?? ''}
              onChange={(event) => setHabitId(event.target.value === '' ? null : Number(event.target.value))}
            >
              <option value="">{t('admin.user_habits.all_habits')}</option>
              {habits.map((habit) => (
                <option key={habit.id} value={habit.id}>
                  {habit.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {content.isError && <ErrorMessage error={content.error} onRetry={() => content.refetch()} />}
        {content.isPlaceholderData && <p role="status">{t('common.loading')}</p>}
        {marks.length === 0 ? (
          <p className={styles.muted}>{t('admin.user_habits.no_marks')}</p>
        ) : (
          <ol className={styles.list}>
            {marks.map((mark) => (
              <li key={mark.id} className={styles.card}>
                <dl className={styles.details}>
                  <Detail label={t('admin.user_habits.marked_at')}>{date(mark.marked_at)}</Detail>
                  <Detail label={t('admin.user_habits.habit')}>{names.get(mark.habit_id) ?? mark.habit_id}</Detail>
                  <Detail label={t('admin.user_habits.author')}>
                    {mark.author ? mark.author.email : t('admin.user_habits.removed_user')}
                  </Detail>
                  {mark.duration_minutes !== null && (
                    <Detail label={t('admin.user_habits.duration')}>
                      {t('admin.user_habits.minutes', { n: mark.duration_minutes })}
                    </Detail>
                  )}
                  {mark.cost_cents !== null && (
                    <Detail label={t('admin.user_habits.cost')}>{money(mark.cost_cents)}</Detail>
                  )}
                  {mark.note && <Detail label={t('admin.user_habits.note')}>{mark.note}</Detail>}
                </dl>
              </li>
            ))}
          </ol>
        )}
        {content.hasNextPage && (
          <button
            type="button"
            className={`${styles.button} ${styles.more}`}
            disabled={content.isFetchingNextPage}
            onClick={() => content.fetchNextPage()}
          >
            {content.isFetchingNextPage ? t('common.loading') : t('admin.load_more')}
          </button>
        )}
      </section>
    </>
  );
}

// Conteúdo dos hábitos de uma conta (só leitura). Cada busca grava `admin_viewed_habits` na
// auditoria: a tela avisa antes e só busca quando o admin pede
export default function AdminUserHabits() {
  const { t } = useTranslation();
  const { userId: param } = useParams();
  const me = useMe().data;
  const userId = parseUserId(param);
  // Vale só para a conta em que o admin clicou: trocar de conta pela URL pede o clique de novo
  const [revealedFor, setRevealedFor] = useState(null);
  const revealed = userId !== null && revealedFor === userId;
  const title = t('admin.user_habits.title');

  return (
    <>
      <PageTitle title={title} />
      <AdminNav />
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.back}>
        <Link to={PATHS.admin}>{t('admin.user_habits.back')}</Link>
      </p>

      {userId === null ? (
        <ErrorMessage error={NOT_FOUND} />
      ) : (
        <>
          <p className={styles.notice} role="note">
            <FiEye aria-hidden size={20} />
            <span>{t('admin.user_habits.audit_notice')}</span>
          </p>
          {revealed ? (
            <Content key={userId} userId={userId} timeZone={me.timezone} />
          ) : (
            <button type="button" className={styles.primary} onClick={() => setRevealedFor(userId)}>
              {t('admin.user_habits.reveal')}
            </button>
          )}
        </>
      )}
    </>
  );
}
