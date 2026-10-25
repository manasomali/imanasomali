import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAccounts } from '../../api/admin';
import { useMe } from '../../api/auth';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import { ACCOUNT_STATUSES, EMPTY_ACCOUNT_FILTERS, accountQuery } from '../../lib/admin';
import AccountCard from './AccountCard';
import AdminNav from './AdminNav';
import styles from './admin.module.css';

const DATE_FILTERS = ['created_from', 'created_to', 'last_login_from', 'last_login_to'];

// Painel de admin: busca de contas (email, status, datas de cadastro e de último login, no fuso
// do admin) e as ações de cada conta
export default function AdminAccounts() {
  const { t } = useTranslation();
  const me = useMe().data;
  const id = useId();
  const [draft, setDraft] = useState(EMPTY_ACCOUNT_FILTERS);
  const [filters, setFilters] = useState(EMPTY_ACCOUNT_FILTERS);
  const [notice, setNotice] = useState(null);
  const statusRef = useRef(null);
  const query = useMemo(() => accountQuery(filters), [filters]);
  const accounts = useAccounts(query);
  const title = t('admin.accounts.title');

  // O resultado de uma ação recebe o foco: o botão que a disparou pode ter sumido
  useEffect(() => {
    if (notice) statusRef.current?.focus();
  }, [notice]);

  const change = (name) => (event) => setDraft((value) => ({ ...value, [name]: event.target.value }));

  const search = (event) => {
    event.preventDefault();
    setNotice(null);
    setFilters(draft);
  };

  const clear = () => {
    setNotice(null);
    setDraft(EMPTY_ACCOUNT_FILTERS);
    setFilters(EMPTY_ACCOUNT_FILTERS);
  };

  const users = accounts.data?.pages.flatMap((page) => page.users) ?? [];

  return (
    <>
      <PageTitle title={title} />
      <AdminNav />
      <h1 className={styles.title}>{title}</h1>

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
          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${id}-status`}>
              {t('admin.accounts.status')}
            </label>
            <select id={`${id}-status`} className={styles.input} value={draft.status} onChange={change('status')}>
              <option value="">{t('admin.accounts.status_any')}</option>
              {ACCOUNT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {t(`admin.accounts.status_${status}`)}
                </option>
              ))}
            </select>
          </div>
          {DATE_FILTERS.map((name) => (
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
        <p ref={statusRef} role="status" tabIndex={-1} className={styles.status}>
          {notice?.text}
        </p>

        {accounts.isPending && <p role="status">{t('common.loading')}</p>}
        {accounts.isError && <ErrorMessage error={accounts.error} onRetry={() => accounts.refetch()} />}
        {accounts.isSuccess && users.length === 0 && <p className={styles.muted}>{t('admin.accounts.empty')}</p>}

        {users.length > 0 && (
          <ul className={styles.list}>
            {users.map((account) => (
              <AccountCard
                key={account.id}
                account={account}
                isSelf={account.id === me.id}
                timeZone={me.timezone}
                onDone={(text) => setNotice({ text })}
              />
            ))}
          </ul>
        )}

        {accounts.hasNextPage && (
          <button
            type="button"
            className={`${styles.button} ${styles.more}`}
            disabled={accounts.isFetchingNextPage}
            onClick={() => accounts.fetchNextPage()}
          >
            {accounts.isFetchingNextPage ? t('common.loading') : t('admin.load_more')}
          </button>
        )}
      </section>
    </>
  );
}
