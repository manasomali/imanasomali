import { useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sendInvite, sharingKeys } from '../../api/sharing';
import ErrorMessage from '../../components/ErrorMessage';
import styles from '../sharing.module.css';

// Mesmo limite da API (app/auth/routes.Email)
const EMAIL_MAX_LENGTH = 254;
const ROLES = ['editor', 'viewer'];

// Convite por email, com o papel. A resposta da API é sempre a mesma (com ou sem conta, a quem já
// é membro ou já tem convite), e a tela também: "convite enviado". `slots` (src/lib/sharing.js)
// desliga o envio sem vagas; a API confere de novo (409 guest_limit_reached). `onSending` limpa a
// mensagem anterior e `onSent` mostra a nova, para o leitor de tela anunciar de novo
export default function InviteForm({ habitId, slots, onSending, onSent }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const emailRef = useRef(null);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('editor');
  const [missing, setMissing] = useState(false);

  const mutation = useMutation({
    mutationFn: (values) => sendInvite(habitId, values),
    onSuccess: () => {
      setEmail('');
      onSent(t('sharing.invite.sent'));
    },
    // Também no erro: o limite pode ter sido atingido por outra aba
    onSettled: () => queryClient.invalidateQueries({ queryKey: sharingKeys.invites(habitId) }),
  });

  const full = slots !== null && slots.left === 0;
  const invalid = missing || mutation.error?.field === 'email';
  const emailErrorId = `${id}-email-error`;
  const hintId = `${id}-hint`;

  const submit = (event) => {
    event.preventDefault();
    if (mutation.isPending || full) return;
    const value = email.trim();
    if (!value) {
      setMissing(true);
      emailRef.current?.focus();
      return;
    }
    setMissing(false);
    onSending();
    mutation.mutate({ email: value, role });
  };

  return (
    <form className={styles.form} aria-labelledby={`${id}-title`} onSubmit={submit} noValidate>
      <h3 id={`${id}-title`} className={styles.heading}>
        {t('sharing.invite.title')}
      </h3>
      <p id={hintId} className={styles.hint}>
        {t('sharing.invite.hint')}
      </p>

      <div className={styles.field}>
        <label className={styles.label} htmlFor={`${id}-email`}>
          {t('sharing.invite.email')}
        </label>
        <input
          ref={emailRef}
          id={`${id}-email`}
          className={styles.input}
          type="email"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          maxLength={EMAIL_MAX_LENGTH}
          value={email}
          aria-invalid={invalid}
          aria-describedby={invalid ? `${emailErrorId} ${hintId}` : hintId}
          onChange={(event) => {
            setEmail(event.target.value);
            setMissing(false);
            if (mutation.error) mutation.reset();
          }}
        />
        {invalid && (
          <p id={emailErrorId} className={styles.fieldError}>
            {t(missing ? 'sharing.invite.email_missing' : 'sharing.invite.email_invalid')}
          </p>
        )}
      </div>

      <fieldset className={styles.roles}>
        <legend className={styles.legend}>{t('sharing.invite.role')}</legend>
        {ROLES.map((value) => (
          <label key={value} className={styles.option}>
            <input
              type="radio"
              name={`${id}-role`}
              value={value}
              checked={role === value}
              onChange={() => setRole(value)}
            />
            <span>{t(`sharing.role_hint.${value}`)}</span>
          </label>
        ))}
      </fieldset>

      {slots !== null && (
        <p className={styles.slots}>
          {t('sharing.invite.slots', { used: slots.used, limit: slots.limit })}
          {full && <> {t('sharing.invite.full')}</>}
        </p>
      )}

      {mutation.error && mutation.error.field !== 'email' && <ErrorMessage error={mutation.error} />}

      <div className={styles.buttons}>
        <button type="submit" className={styles.primary} disabled={mutation.isPending || full}>
          {mutation.isPending ? t('sharing.invite.sending') : t('sharing.invite.send')}
        </button>
      </div>
    </form>
  );
}
