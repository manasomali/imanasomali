import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAccounts } from '../../api/admin';
import { useMe } from '../../api/account';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import { ACCOUNT_STATUSES, EMPTY_ACCOUNT_FILTERS, accountQuery } from '../../lib/admin';
import AccountCard from './AccountCard';
import MailStats from './MailStats';
import styles from './admin.module.css';

const EMAIL_MAX_LENGTH = 254;

// Admin de contas (`/imago/admin`, só is_admin): busca por trecho do email e situação, com "carregar
// mais" pelo cursor, as ações de cada conta e os envios de email das últimas 24 h. O painel de cada
// aplicação cuida só do conteúdo dela
export default function Admin() {
  const { t } = useTranslation();
  const me = useMe().data;
  const id = useId();
  const [draft, setDraft] = useState(EMPTY_ACCOUNT_FILTERS);
  const [filters, setFilters] = useState(EMPTY_ACCOUNT_FILTERS);
  const [notice, setNotice] = useState(null);
  const statusRef = useRef(null);
  const query = useMemo(() => accountQuery(filters), [filters]);
  const accounts = useAccounts(query);
  const title = t('admin.title');

  // O resultado de uma ação recebe o foco: o botão que a disparou pode ter sumido. Um objeto novo
  // a cada aviso, para o mesmo texto receber o foco de novo
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
      <h1 className={styles.title}>{title}</h1>

      <section className={styles.section} aria-labelledby={`${id}-accounts`}>
        <h2 id={`${id}-accounts`} className={styles.subtitle}>
          {t('admin.accounts.title')}
        </h2>
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
                maxLength={EMAIL_MAX_LENGTH}
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
          </div>
          <div className={styles.buttons}>
            <button type="submit" className={styles.primary}>
              {t('admin.accounts.search')}
            </button>
            <button type="button" className={styles.button} onClick={clear}>
              {t('admin.accounts.clear')}
            </button>
          </div>
        </form>

        <p className={styles.hint}>{t('admin.accounts.dates_hint', { timezone: me.timezone })}</p>
        <p ref={statusRef} role="status" tabIndex={-1} className={styles.status}>
          {notice?.text}
        </p>

        {accounts.isPending && <p role="status">{t('common.loading')}</p>}
        {accounts.isError && <ErrorMessage error={accounts.error} onRetry={() => accounts.refetch()} />}
        {accounts.isSuccess && users.length === 0 && <p className={styles.muted}>{t('admin.accounts.empty')}</p>}

        {users.length > 0 && (
          <ul className={styles.list} aria-label={t('admin.accounts.results')}>
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

      <MailStats />
    </>
  );
}
