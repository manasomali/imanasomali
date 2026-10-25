import { useEffect, useId, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Trans, useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate } from 'react-router';
import { requestCode, verifyCode } from '../../api/auth';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import { returnPath } from '../../lib/session';
import { PATHS } from '../../paths';
import useCountdown from '../../hooks/useCountdown';
import styles from './styles.module.css';

// Espera entre um envio de código e o próximo (a API aceita 1 por minuto por email)
const RESEND_SECONDS = 60;

const CODE_LENGTH = 6;

/** Só os dígitos ASCII do que foi digitado ou colado ("123 456" vira "123456"), até 6. */
function onlyDigits(value) {
  return value.replace(/[^0-9]/g, '').slice(0, CODE_LENGTH);
}

// Cadastro e login na mesma tela: email → código. As mensagens são iguais para qualquer email
// (a API também responde igual), então a tela não revela se a conta existe. Depois de entrar,
// limpa o cache da sessão anterior e volta para onde a pessoa estava (returnPath)
export default function Login() {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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
    onSuccess: () => {
      queryClient.clear();
      navigate(returnPath(location), { replace: true });
    },
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
    if (verify.isPending) return;
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

  const title = t('pages.login.title');
  const emailErrorId = `${ids}-email-error`;
  const codeHelpId = `${ids}-code-help`;
  const codeErrorId = `${ids}-code-error`;

  return (
    <div className={styles.page}>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>
      {/* Vindo da exclusão da conta (tela de conta) */}
      {location.state?.accountDeleted === true && (
        <p role="status" className={styles.notice}>
          {t('pages.login.account_deleted')}
        </p>
      )}

      {step === 'email' ? (
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
              maxLength={254}
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
      ) : (
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
              pattern="[0-9]{6}"
              required
              value={code}
              onChange={(event) => {
                setCode(onlyDigits(event.target.value));
                if (verify.isError) verify.reset();
              }}
              aria-invalid={verify.isError}
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
              disabled={secondsLeft > 0 || send.isPending}
              onClick={() => send.mutate({ email: sentTo, resend: true })}
            >
              {secondsLeft > 0
                ? t('pages.login.resend_in', { seconds: secondsLeft })
                : t('pages.login.resend')}
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
      )}

      <p className={styles.consent}>
        <Trans
          i18nKey="pages.login.consent"
          components={{
            terms: <Link to={PATHS.terms} target="_blank" rel="noreferrer" />,
            privacy: <Link to={PATHS.privacy} target="_blank" rel="noreferrer" />,
          }}
        />
      </p>
    </div>
  );
}
