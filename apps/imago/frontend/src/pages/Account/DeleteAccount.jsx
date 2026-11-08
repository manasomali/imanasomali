import { useEffect, useId, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Trans, useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { FiTrash2 } from 'react-icons/fi';
import { requestAccountDeletion, useDeleteAccount } from '../../api/account';
import ErrorMessage from '../../components/ErrorMessage';
import useCountdown from '../../hooks/useCountdown';
import { accountApps, appTexts } from '../../lib/apps';
import { CODE_LENGTH, RESEND_SECONDS, isCompleteCode, onlyDigits } from '../../lib/code';
import { PATHS } from '../../paths';
import styles from './styles.module.css';

const ICON_SIZE = 18;

// Etapas, na ordem: o que some em cada aplicação → links de export → pedir o código → código e
// confirmação final
const STEPS = Object.freeze(['warning', 'export', 'request', 'code']);

// Exclusão da conta em todas as aplicações (POST /me/delete/request e DELETE /me {code}), em
// etapas: o aviso do que some (o texto de cada aplicação vem de apps.<nome>.deletion), os links de
// export de cada aplicação (opcionais), o pedido do código (vai para o email da conta) e, por fim, o
// código com a confirmação final. Código errado mantém a etapa, com o campo marcado. Último admin
// ativo: a API recusa (409 last_admin) e a tela mostra o bloqueio. Depois de excluir, o mesmo
// caminho do sair: tela de entrar, com o cache limpo e o aviso da exclusão
export default function DeleteAccount({ me }) {
  const { t, i18n } = useTranslation();
  const ids = useId();
  // null: fechado
  const [step, setStep] = useState(null);
  const [code, setCode] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  // Reenvio feito com sucesso, para o aviso "enviamos um novo código"
  const [resent, setResent] = useState(false);
  const [secondsLeft, startCountdown] = useCountdown();
  const startRef = useRef(null);
  // O que recebe o foco quando a etapa aparece: o título dela, ou o campo do código
  const focusRef = useRef(null);
  const codeRef = useRef(null);

  const exists = (key) => i18n.exists(key);
  const apps = accountApps(me.apps).map((name) => ({ id: name, ...appTexts(name, t, exists) }));
  const exports = apps.filter((app) => app.exportPath !== null);

  const request = useMutation({
    mutationFn: requestAccountDeletion,
    onSuccess: (_, variables) => {
      setResent(Boolean(variables?.resend));
      setStep('code');
      startCountdown(RESEND_SECONDS);
    },
  });
  const remove = useDeleteAccount();
  const blocked = request.error?.code === 'last_admin' || remove.error?.code === 'last_admin';

  const previousStep = useRef(step);
  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    (step === null ? startRef : focusRef).current?.focus();
  }, [step]);

  const close = () => {
    setStep(null);
    setCode('');
    setConfirmed(false);
    setResent(false);
    request.reset();
    remove.reset();
  };

  // O código pode ter chegado num pedido anterior (ex.: o novo pedido bateu no limite)
  const enterExistingCode = () => {
    request.reset();
    setResent(false);
    setStep('code');
  };

  const submitCode = (event) => {
    event.preventDefault();
    // O navegador já confere `required` e `pattern`; isto cobre os que não conferem
    if (remove.isPending || blocked || !isCompleteCode(code) || !confirmed) return;
    remove.mutate(
      { code },
      {
        // O campo continua com o que foi digitado, selecionado para corrigir
        onError: () => {
          codeRef.current?.focus();
          codeRef.current?.select();
        },
      },
    );
  };

  const titleId = `${ids}-title`;
  const stepTitleId = `${ids}-step`;
  const codeHelpId = `${ids}-code-help`;
  const codeErrorId = `${ids}-code-error`;
  const codeRejected = remove.error?.field === 'code';

  const stepTitle = (key) => (
    <h3 id={stepTitleId} ref={focusRef} tabIndex={-1} className={styles.stepTitle}>
      {t(`pages.account.delete.${key}`)}
    </h3>
  );

  // Desligado com um pedido em andamento: a resposta abriria a etapa do código de novo
  const cancelButton = (
    <button
      type="button"
      className={styles.button}
      onClick={close}
      disabled={request.isPending || remove.isPending}
    >
      {t('pages.account.delete.cancel')}
    </button>
  );

  let content = null;
  if (step === 'warning') {
    content = (
      <>
        {stepTitle('warning_title')}
        <p>{t('pages.account.delete.warning_intro')}</p>
        <ul className={styles.bullets}>
          <li>{t('pages.account.delete.lose_account')}</li>
          {apps.map((app) => (
            <li key={app.id}>
              <strong>{app.name}</strong>: {app.deletion ?? t('pages.account.delete.app_fallback')}
            </li>
          ))}
        </ul>
        <p className={styles.muted}>
          <Trans
            i18nKey="pages.account.delete.backups"
            components={{
              privacy: <Link to={`${PATHS.privacy}#deletion`} target="_blank" rel="noreferrer" />,
            }}
          />
        </p>
        <div className={styles.buttons}>
          <button type="button" className={styles.primary} onClick={() => setStep('export')}>
            {t('pages.account.delete.continue')}
          </button>
          {cancelButton}
        </div>
      </>
    );
  } else if (step === 'export') {
    content = (
      <>
        {stepTitle('export_title')}
        <p>{t('pages.account.delete.export_text')}</p>
        {exports.length === 0 ? (
          <p className={styles.muted}>{t('pages.account.delete.export_none')}</p>
        ) : (
          <ul className={styles.bullets}>
            {exports.map((app) => (
              <li key={app.id}>
                <a href={app.exportPath} target="_blank" rel="noreferrer">
                  {app.exportLabel}
                </a>
              </li>
            ))}
          </ul>
        )}
        <p className={styles.muted}>{t('pages.account.delete.export_new_tab')}</p>
        <div className={styles.buttons}>
          <button type="button" className={styles.primary} onClick={() => setStep('request')}>
            {t('pages.account.delete.continue')}
          </button>
          <button type="button" className={styles.button} onClick={() => setStep('warning')}>
            {t('pages.account.delete.back')}
          </button>
          {cancelButton}
        </div>
      </>
    );
  } else if (step === 'request') {
    content = (
      <>
        {stepTitle('request_title')}
        <p>{t('pages.account.delete.request_text', { email: me.email })}</p>
        {request.isError && (
          <div className={styles.form}>
            <ErrorMessage error={request.error} />
            {request.error.status === 429 && (
              <button type="button" className={styles.linkButton} onClick={enterExistingCode}>
                {t('pages.account.delete.have_code')}
              </button>
            )}
          </div>
        )}
        <div className={styles.buttons}>
          {!blocked && (
            <button
              type="button"
              className={styles.primary}
              disabled={request.isPending}
              onClick={() => request.mutate({})}
            >
              {request.isPending ? t('pages.account.delete.sending') : t('pages.account.delete.send_code')}
            </button>
          )}
          <button
            type="button"
            className={styles.button}
            disabled={request.isPending}
            onClick={() => {
              request.reset();
              setStep('export');
            }}
          >
            {t('pages.account.delete.back')}
          </button>
          {cancelButton}
        </div>
      </>
    );
  } else if (step === 'code') {
    content = (
      <form className={styles.form} onSubmit={submitCode}>
        <h3 id={stepTitleId} className={styles.stepTitle}>
          {t('pages.account.delete.code_title')}
        </h3>
        <p id={codeHelpId}>{t('pages.account.delete.code_sent', { email: me.email })}</p>
        <div className={styles.field}>
          <label htmlFor={`${ids}-code`} className={styles.label}>
            {t('pages.account.delete.code')}
          </label>
          <input
            ref={(element) => {
              codeRef.current = element;
              focusRef.current = element;
            }}
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
              if (remove.isError) remove.reset();
            }}
            aria-invalid={codeRejected}
            aria-describedby={codeRejected ? `${codeErrorId} ${codeHelpId}` : codeHelpId}
          />
        </div>
        {remove.isError && (
          <div id={codeErrorId}>
            <ErrorMessage error={remove.error} />
          </div>
        )}

        <h4 className={styles.subtitle}>{t('pages.account.delete.final_title')}</h4>
        <label className={styles.check}>
          <input
            type="checkbox"
            name="confirm"
            required
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          {t('pages.account.delete.final_confirm')}
        </label>
        <div className={styles.buttons}>
          <button type="submit" className={styles.danger} disabled={remove.isPending || blocked}>
            <FiTrash2 aria-hidden size={ICON_SIZE} />
            {remove.isPending ? t('pages.account.delete.deleting') : t('pages.account.delete.submit')}
          </button>
          {cancelButton}
        </div>

        <div className={styles.buttons}>
          <button
            type="button"
            className={styles.linkButton}
            disabled={secondsLeft > 0 || request.isPending || remove.isPending}
            onClick={() => request.mutate({ resend: true })}
          >
            {secondsLeft > 0
              ? t('pages.account.delete.resend_in', { seconds: secondsLeft })
              : t('pages.account.delete.resend')}
          </button>
        </div>
        {request.isError && <ErrorMessage error={request.error} />}
        <p className={styles.status} role="status">
          {resent && !request.isError ? t('pages.account.delete.resent') : ''}
        </p>
      </form>
    );
  }

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.sectionTitle}>
        {t('pages.account.delete.title')}
      </h2>
      <p className={styles.muted}>{t('pages.account.delete.intro')}</p>
      {step !== null ? (
        <div className={styles.panel} role="group" aria-labelledby={stepTitleId}>
          <ol className={styles.steps} aria-label={t('pages.account.delete.steps')}>
            {STEPS.map((name, index) => (
              <li key={name} aria-current={name === step ? 'step' : undefined}>
                {t('pages.account.delete.step', {
                  number: index + 1,
                  name: t(`pages.account.delete.step_${name}`),
                })}
              </li>
            ))}
          </ol>
          {content}
        </div>
      ) : (
        <div className={styles.buttons}>
          <button ref={startRef} type="button" className={styles.button} onClick={() => setStep(STEPS[0])}>
            <FiTrash2 aria-hidden size={ICON_SIZE} />
            {t('pages.account.delete.start')}
          </button>
        </div>
      )}
    </section>
  );
}
