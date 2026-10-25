import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  adminKeys,
  blockAccount,
  changeAccountEmail,
  deleteAccount,
  unblockAccount,
} from '../../api/admin';
import ErrorMessage from '../../components/ErrorMessage';
import { confirmsEmail } from '../../lib/admin';
import { formatDateTime } from '../../lib/datetime';
import { adminUserPath } from '../../paths';
import styles from './admin.module.css';

const EMAIL_MAX_LENGTH = 254;

// Ações que pedem confirmação digitando o email da conta
const CONFIRMED = ['block', 'email', 'delete'];

const ACTIONS = {
  block: (id) => blockAccount(id),
  unblock: (id) => unblockAccount(id),
  email: (id, newEmail) => changeAccountEmail(id, newEmail),
  delete: (id) => deleteAccount(id),
};

// Uma conta na listagem do admin, com as ações. Bloquear, trocar o email e apagar abrem um painel
// que só libera o botão quando o email da conta é digitado. Uma ação por vez: enquanto uma está
// em andamento, as outras ficam desligadas. `onDone(mensagem)` avisa a tela
export default function AccountCard({ account, isSelf, timeZone, onDone }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const [mode, setMode] = useState(null);
  const [typed, setTyped] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const openerRef = useRef(null);
  const firstFieldRef = useRef(null);

  const mutation = useMutation({
    mutationFn: ({ action, email }) => ACTIONS[action](account.id, email),
    onSuccess: (result, { action }) => {
      const messages = {
        block: t('admin.accounts.blocked_done', { email: account.email }),
        unblock: t('admin.accounts.unblocked_done', { email: account.email }),
        email: t('admin.accounts.email_done', { old: account.email, email: result?.email }),
        delete: t('admin.accounts.deleted_done', { email: account.email }),
      };
      if (action === 'email' || action === 'delete') {
        queryClient.removeQueries({ queryKey: adminKeys.userHabits(account.id) });
      }
      queryClient.invalidateQueries({ queryKey: adminKeys.users });
      setMode(null);
      onDone(messages[action]);
    },
  });

  useEffect(() => {
    if (mode) firstFieldRef.current?.focus();
  }, [mode]);

  const open = (action, event) => {
    if (mode === action) {
      close();
      return;
    }
    openerRef.current = event.currentTarget;
    mutation.reset();
    setTyped('');
    setNewEmail('');
    setMode(action);
  };

  const close = () => {
    setMode(null);
    mutation.reset();
    openerRef.current?.focus();
  };

  const confirmed = confirmsEmail(typed, account.email);
  const ready = confirmed && (mode !== 'email' || newEmail.trim() !== '') && !mutation.isPending;

  const submit = (event) => {
    event.preventDefault();
    if (!ready) return;
    mutation.mutate({ action: mode, email: newEmail.trim() });
  };

  const date = (value) => formatDateTime(value, timeZone, i18n.resolvedLanguage);
  const panelId = `${id}-panel`;
  const titleId = `${id}-title`;
  const emailError = mutation.error?.field === 'new_email';

  return (
    <li className={styles.card}>
      <h3 className={styles.cardTitle}>
        <span className="user-text">{account.email}</span>{' '}
        <span className={styles.badge}>
          {account.is_active ? t('admin.accounts.status_active') : t('admin.accounts.status_blocked')}
        </span>
        {account.is_admin && <> <span className={styles.badge}>{t('admin.accounts.admin_badge')}</span></>}
        {isSelf && <> <span className={styles.badge}>{t('admin.accounts.you')}</span></>}
      </h3>

      <dl className={styles.details}>
        <div>
          <dt>{t('admin.accounts.created')}</dt>
          <dd>{date(account.created_at)}</dd>
        </div>
        <div>
          <dt>{t('admin.accounts.last_login')}</dt>
          <dd>{account.last_login_at ? date(account.last_login_at) : t('admin.accounts.never')}</dd>
        </div>
        <div>
          <dt>{t('admin.accounts.habit_count')}</dt>
          <dd>{account.habit_count}</dd>
        </div>
        <div>
          <dt>{t('admin.accounts.mark_count')}</dt>
          <dd>{account.mark_count}</dd>
        </div>
      </dl>

      <div className={styles.buttons} role="group" aria-label={t('admin.accounts.actions', { email: account.email })}>
        <Link to={adminUserPath(account.id)} className={styles.button}>
          {t('admin.accounts.view_habits')}
        </Link>
        {account.is_active ? (
          !isSelf && (
            <button
              type="button"
              className={styles.button}
              aria-expanded={mode === 'block'}
              aria-controls={mode === 'block' ? panelId : undefined}
              disabled={mutation.isPending}
              onClick={(event) => open('block', event)}
            >
              {t('admin.accounts.block')}
            </button>
          )
        ) : (
          <button
            type="button"
            className={styles.button}
            disabled={mutation.isPending}
            onClick={() => mutation.mutate({ action: 'unblock' })}
          >
            {t('admin.accounts.unblock')}
          </button>
        )}
        <button
          type="button"
          className={styles.button}
          aria-expanded={mode === 'email'}
          aria-controls={mode === 'email' ? panelId : undefined}
          disabled={mutation.isPending}
          onClick={(event) => open('email', event)}
        >
          {t('admin.accounts.change_email')}
        </button>
        <button
          type="button"
          className={styles.button}
          aria-expanded={mode === 'delete'}
          aria-controls={mode === 'delete' ? panelId : undefined}
          disabled={mutation.isPending}
          onClick={(event) => open('delete', event)}
        >
          {t('admin.accounts.delete')}
        </button>
      </div>

      {mode === null && mutation.error && <ErrorMessage error={mutation.error} />}

      {CONFIRMED.includes(mode) && (
        <form id={panelId} className={styles.confirm} aria-labelledby={titleId} onSubmit={submit} noValidate>
          <h4 id={titleId}>{t(`admin.accounts.${mode}_title`)}</h4>
          <p>{t(`admin.accounts.${mode}_warning`)}</p>

          {mode === 'email' && (
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`${id}-new-email`}>
                {t('admin.accounts.new_email')}
              </label>
              <input
                ref={firstFieldRef}
                id={`${id}-new-email`}
                className={styles.input}
                type="email"
                autoComplete="off"
                spellCheck={false}
                maxLength={EMAIL_MAX_LENGTH}
                value={newEmail}
                aria-invalid={emailError}
                onChange={(event) => setNewEmail(event.target.value)}
              />
            </div>
          )}

          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${id}-confirm`}>
              {t('admin.accounts.confirm_label', { email: account.email })}
            </label>
            <input
              ref={mode === 'email' ? undefined : firstFieldRef}
              id={`${id}-confirm`}
              className={styles.input}
              type="text"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
            />
          </div>

          {mutation.error && <ErrorMessage error={mutation.error} />}

          <div className={styles.buttons}>
            <button type="submit" className={styles.primary} disabled={!ready}>
              {t(`admin.accounts.${mode}_confirm`)}
            </button>
            <button type="button" className={styles.button} onClick={close}>
              {t('admin.cancel')}
            </button>
          </div>
        </form>
      )}
    </li>
  );
}
