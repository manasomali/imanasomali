import { useEffect, useId, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { requestCode, verifyCode } from '../../api/account';
import ErrorMessage from '../../components/ErrorMessage';
import useCountdown from '../../hooks/useCountdown';
import { CODE_LENGTH, RESEND_SECONDS, isCompleteCode, onlyDigits } from '../../lib/code';
import styles from './styles.module.css';

const EMAIL_MAX_LENGTH = 254;

// Email → código, numa tela só. As mensagens são iguais para qualquer email (a API também responde
// igual), então a tela não revela se a conta existe. `onSignedIn` roda depois do código certo e o
// botão continua ocupado até ela terminar (a tela de entrar decide entre o aceite e o `next`)
export default function CodeForm({ onSignedIn }) {
  const { t, i18n } = useTranslation();
  const ids = useId();
  const emailRef = useRef(null);
  const codeRef = useRef(null);
  const [email, setEmail] = useState('');
  // Email para o qual o código foi pedido; null enquanto a tela pede o email
  const [sentTo, setSentTo] = useState(null);
  const [code, setCode] = useState('');
  // Reenvio feito com sucesso, para o aviso "enviamos um novo código"
  const [resent, setResent] = useState(false);
  const [secondsLeft, startCountdown] = useCountdown();

  const send = useMutation({
    mutationFn: requestCode,
    onSuccess: (_, variables) => {
      setResent(Boolean(variables.resend));
      setSentTo(variables.email);
      startCountdown(RESEND_SECONDS);
    },
  });

  const verify = useMutation({
    mutationFn: verifyCode,
    onSuccess: () => onSignedIn(),
    // O campo continua com o que foi digitado, selecionado para corrigir
    onError: () => {
      codeRef.current?.focus();
      codeRef.current?.select();
    },
  });

  // Foco no campo da etapa que acabou de aparecer (não na primeira renderização)
  const step = sentTo === null ? 'email' : 'code';
  const previousStep = useRef(step);
  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    (step === 'code' ? codeRef : emailRef).current?.focus();
  }, [step]);

  const submitEmail = (event) => {
    event.preventDefault();
    if (send.isPending) return;
    send.mutate({ email: email.trim() });
  };

  const submitCode = (event) => {
    event.preventDefault();
    // O navegador já confere `required` e `pattern`; isto cobre os que não conferem
    if (verify.isPending || !isCompleteCode(code)) return;
    verify.mutate({ email: sentTo, code, language: i18n.resolvedLanguage });
  };

  // O código pode ter chegado num pedido anterior (ex.: a página foi recarregada e o novo pedido
  // bateu no limite): passa para o código sem pedir outro
  const enterExistingCode = () => {
    setSentTo(email.trim());
    setResent(false);
    startCountdown(RESEND_SECONDS);
    send.reset();
  };

  const changeEmail = () => {
    setSentTo(null);
    setCode('');
    setResent(false);
    send.reset();
    verify.reset();
  };

  const emailErrorId = `${ids}-email-error`;
  const codeHelpId = `${ids}-code-help`;
  const codeErrorId = `${ids}-code-error`;

  if (step === 'email') {
    return (
      <form className={styles.form} onSubmit={submitEmail}>
        <p className={styles.muted}>{t('pages.login.intro')}</p>
        <div className={styles.field}>
          <label htmlFor={`${ids}-email`}>{t('pages.login.email')}</label>
          <input
            ref={emailRef}
            id={`${ids}-email`}
            className={styles.input}
            type="email"
            name="email"
            autoComplete="email"
            spellCheck={false}
            required
            maxLength={EMAIL_MAX_LENGTH}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={send.error?.field === 'email'}
            aria-describedby={send.isError ? emailErrorId : undefined}
          />
        </div>
        {send.isError && (
          <div id={emailErrorId} className={styles.error}>
            <ErrorMessage error={send.error} />
            {send.error.status === 429 && (
              <button type="button" className={styles.linkButton} onClick={enterExistingCode}>
                {t('pages.login.have_code')}
              </button>
            )}
          </div>
        )}
        <button type="submit" className={styles.primary} disabled={send.isPending}>
          {send.isPending ? t('pages.login.sending') : t('pages.login.send_code')}
        </button>
      </form>
    );
  }

  return (
    <form className={styles.form} onSubmit={submitCode}>
      <p id={codeHelpId} className={styles.muted}>
        {t('pages.login.code_sent', { email: sentTo })}
      </p>
      <div className={styles.field}>
        <label htmlFor={`${ids}-code`}>{t('pages.login.code')}</label>
        <input
          ref={codeRef}
          id={`${ids}-code`}
          className={`${styles.input} ${styles.code}`}
          type="text"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern={`[0-9]{${CODE_LENGTH}}`}
          required
          value={code}
          onChange={(event) => {
            setCode(onlyDigits(event.target.value));
            if (verify.isError) verify.reset();
          }}
          aria-invalid={verify.error?.field === 'code'}
          aria-describedby={verify.isError ? `${codeErrorId} ${codeHelpId}` : codeHelpId}
        />
      </div>
      {verify.isError && (
        <div id={codeErrorId} className={styles.error}>
          <ErrorMessage error={verify.error} />
        </div>
      )}
      <button type="submit" className={styles.primary} disabled={verify.isPending}>
        {verify.isPending ? t('pages.login.submitting') : t('pages.login.submit')}
      </button>

      <div className={styles.secondary}>
        <button
          type="button"
          className={styles.linkButton}
          disabled={secondsLeft > 0 || send.isPending || verify.isPending}
          onClick={() => send.mutate({ email: sentTo, resend: true })}
        >
          {secondsLeft > 0 ? t('pages.login.resend_in', { seconds: secondsLeft }) : t('pages.login.resend')}
        </button>
        {/* Desligado com um pedido em andamento: a resposta traria a etapa do código de volta */}
        <button
          type="button"
          className={styles.linkButton}
          disabled={send.isPending || verify.isPending}
          onClick={changeEmail}
        >
          {t('pages.login.change_email')}
        </button>
      </div>
      {send.isError && <ErrorMessage error={send.error} />}
      <p role="status" className={styles.muted}>
        {resent && !send.isError ? t('pages.login.resent') : ''}
      </p>
    </form>
  );
}
