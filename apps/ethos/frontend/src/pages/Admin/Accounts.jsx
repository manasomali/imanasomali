import { useId, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useAppUsers } from '../../api/admin';
import { useMe } from '../../api/me';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import { EMPTY_USER_FILTERS, USER_DATE_FILTERS, userQuery } from '../../lib/admin';
import { formatDateTime } from '../../lib/datetime';
import { IMAGO_PATHS, adminUserPath } from '../../paths';
import AdminNav from './AdminNav';
import styles from './admin.module.css';

// Painel de admin: quem usa o ethos (app_users), com busca por email e pelo primeiro acesso (no fuso
// do admin), as contagens e o link para o conteúdo dos hábitos. As contas (bloquear, trocar o
// email, excluir) ficam no painel do imago (/imago/admin), linkado aqui
export default function AdminAccounts() {
  const { t, i18n } = useTranslation();
  const me = useMe().data;
  const id = useId();
  const [draft, setDraft] = useState(EMPTY_USER_FILTERS);
  const [filters, setFilters] = useState(EMPTY_USER_FILTERS);
  const query = useMemo(() => userQuery(filters), [filters]);
  const users = useAppUsers(query);
  const title = t('admin.accounts.title');
  const date = (value) => formatDateTime(value, me.timezone, i18n.resolvedLanguage);

  const change = (name) => (event) => setDraft((value) => ({ ...value, [name]: event.target.value }));

  const search = (event) => {
    event.preventDefault();
    setFilters(draft);
  };

  const clear = () => {
    setDraft(EMPTY_USER_FILTERS);
    setFilters(EMPTY_USER_FILTERS);
  };

  const list = users.data?.pages.flatMap((page) => page.users) ?? [];

  return (
    <>
      <PageTitle title={title} />
      <AdminNav />
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.hint}>
        {t('admin.accounts.intro')} <a href={IMAGO_PATHS.admin}>{t('admin.accounts.imago_admin')}</a>
      </p>

      <form className={styles.form} aria-label={t('admin.accounts.filters')} onSubmit={search}>
        <div className={styles.fields}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${id}-email`}>
              {t('admin.accounts.email')}
            </label>
            <input
              id={`${id}-email`}
              className={styles.input}
              type="search"
              autoComplete="off"
              spellCheck={false}
              maxLength={254}
              value={draft.email}
              onChange={change('email')}
            />
          </div>
          {USER_DATE_FILTERS.map((name) => (
            <div key={name} className={styles.field}>
              <label className={styles.label} htmlFor={`${id}-${name}`}>
                {t(`admin.accounts.${name}`)}
              </label>
              <input
                id={`${id}-${name}`}
                className={styles.input}
                type="date"
                min="1900-01-01"
                max="9999-12-31"
                value={draft[name]}
                aria-describedby={`${id}-dates`}
                onChange={change(name)}
              />
            </div>
          ))}
        </div>
        <p id={`${id}-dates`} className={styles.hint}>
          {t('admin.accounts.dates_hint', { timezone: me.timezone })}
        </p>
        <div className={styles.buttons}>
          <button type="submit" className={styles.primary}>
            {t('admin.accounts.search')}
          </button>
          <button type="button" className={styles.button} onClick={clear}>
            {t('admin.accounts.clear')}
          </button>
        </div>
      </form>

      <section className={styles.section} aria-labelledby={`${id}-results`}>
        <h2 id={`${id}-results`} className={styles.subtitle}>
          {t('admin.accounts.results')}
        </h2>

        {users.isPending && <p role="status">{t('common.loading')}</p>}
        {users.isError && <ErrorMessage error={users.error} onRetry={() => users.refetch()} />}
        {users.isSuccess && list.length === 0 && <p className={styles.muted}>{t('admin.accounts.empty')}</p>}

        {list.length > 0 && (
          <ul className={styles.list}>
            {list.map((user) => (
              <li key={user.id} className={styles.card}>
                <h3 className={styles.cardTitle}>
                  <span className="user-text">{user.email}</span>
                  {user.id === me.id && <> <span className={styles.badge}>{t('admin.accounts.you')}</span></>}
                </h3>
                <dl className={styles.details}>
                  <div>
                    <dt>{t('admin.accounts.first_seen')}</dt>
                    <dd>{date(user.first_seen_at)}</dd>
                  </div>
                  <div>
                    <dt>{t('admin.accounts.habit_count')}</dt>
                    <dd>{user.habit_count}</dd>
                  </div>
                  <div>
                    <dt>{t('admin.accounts.mark_count')}</dt>
                    <dd>{user.mark_count}</dd>
                  </div>
                </dl>
                <div className={styles.buttons} role="group" aria-label={t('admin.accounts.actions', { email: user.email })}>
                  <Link to={adminUserPath(user.id)} className={styles.button}>
                    {t('admin.accounts.view_habits')}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}

        {users.hasNextPage && (
          <button
            type="button"
            className={`${styles.button} ${styles.more}`}
            disabled={users.isFetchingNextPage}
            onClick={() => users.fetchNextPage()}
          >
            {users.isFetchingNextPage ? t('common.loading') : t('admin.load_more')}
          </button>
        )}
      </section>
    </>
  );
}
