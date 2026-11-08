import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminKeys, changeAccountEmail, deleteAccount, setAccountActive } from '../../api/admin';
import ErrorMessage from '../../components/ErrorMessage';
import { accountStatus, confirmsEmail } from '../../lib/admin';
import { formatDateTime } from '../../lib/datetime';
import styles from './admin.module.css';

const EMAIL_MAX_LENGTH = 254;

// Ações que pedem confirmação digitando o email da conta
const CONFIRMED = Object.freeze(['block', 'email', 'delete']);

const ACTIONS = Object.freeze({
  block: (id) => setAccountActive(id, false),
  unblock: (id) => setAccountActive(id, true),
  email: (id, newEmail) => changeAccountEmail(id, newEmail),
  delete: (id) => deleteAccount(id),
});

// Uma conta na listagem do admin, com as ações. Bloquear, trocar o email e excluir abrem um painel
// que só libera o botão quando o email da conta é digitado; desbloquear não pede confirmação. Uma
// ação por vez: enquanto uma está em andamento, as outras ficam desligadas. Conta em exclusão não
// tem ações. `onDone(mensagem)` avisa a tela
export default function AccountCard({ account, isSelf, timeZone, onDone }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const [mode, setMode] = useState(null);
  const [typed, setTyped] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const openerRef = useRef(null);
  const firstFieldRef = useRef(null);
  const status = accountStatus(account);

  const mutation = useMutation({
    mutationFn: ({ action, email }) => ACTIONS[action](account.id, email),
    onSuccess: (result, { action }) => {
      const messages = {
        block: () => t('admin.accounts.blocked_done', { email: account.email }),
        unblock: () => t('admin.accounts.unblocked_done', { email: account.email }),
        email: () => t('admin.accounts.email_done', { old: account.email, email: result?.email }),
        delete: () => t('admin.accounts.deleted_done', { email: account.email }),
      };
      void queryClient.invalidateQueries({ queryKey: adminKeys.users });
      setMode(null);
      onDone(messages[action]());
    },
  });

  useEffect(() => {
    if (mode) firstFieldRef.current?.focus();
  }, [mode]);

  const close = () => {
    setMode(null);
    mutation.reset();
    openerRef.current?.focus();
  };

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
  const newEmailErrorId = `${id}-new-email-error`;
  const emailError = mutation.error?.field === 'new_email';

  const actionButton = (action) => (
    <button
      type="button"
      className={styles.button}
      aria-expanded={mode === action}
      aria-controls={mode === action ? panelId : undefined}
      disabled={mutation.isPending}
      onClick={(event) => open(action, event)}
    >
      {t(`admin.accounts.${action === 'email' ? 'change_email' : action}`)}
    </button>
  );

  return (
    <li className={styles.card}>
      <h3 className={styles.cardTitle}>
        <span className="user-text">{account.email}</span>{' '}
        <span className={styles.badge}>{t(`admin.accounts.status_${status}`)}</span>
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
          <dt>{t('admin.accounts.timezone')}</dt>
          <dd>{account.timezone}</dd>
        </div>
        <div>
          <dt>{t('admin.accounts.locale')}</dt>
          <dd>{account.locale}</dd>
        </div>
      </dl>

      {status === 'deleting' ? (
        <p className={styles.muted}>{t('admin.accounts.deleting_note')}</p>
      ) : (
        <div className={styles.buttons} role="group" aria-label={t('admin.accounts.actions', { email: account.email })}>
          {status === 'active' && !isSelf && actionButton('block')}
          {status === 'blocked' && (
            <button
              type="button"
              className={styles.button}
              disabled={mutation.isPending}
              onClick={() => mutation.mutate({ action: 'unblock' })}
            >
              {t('admin.accounts.unblock')}
            </button>
          )}
          {actionButton('email')}
          {actionButton('delete')}
        </div>
      )}

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
                aria-describedby={emailError ? newEmailErrorId : undefined}
                onChange={(event) => {
                  setNewEmail(event.target.value);
                  if (mutation.isError) mutation.reset();
                }}
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

          {mutation.error && (
            <div id={newEmailErrorId}>
              <ErrorMessage error={mutation.error} />
            </div>
          )}

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
