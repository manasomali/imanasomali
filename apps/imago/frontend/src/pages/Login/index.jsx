import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Trans, useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router';
import { meQueryKey, useMe } from '../../api/account';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import { ApiError } from '../../lib/api';
import { pageLocation } from '../../lib/location';
import { appRoute, resolveNext } from '../../lib/next';
import { SESSION_NOT_SAVED } from '../../lib/session';
import { PATHS } from '../../paths';
import CodeForm from './CodeForm';
import TermsAcceptance from './TermsAcceptance';
import styles from './styles.module.css';

// Tela de entrar (`/imago/entrar?next=<caminho>`), destino do 401 do imago e de todas as
// aplicações. Busca o /me ao abrir:
// - sem sessão (401): email → código. Cadastro e login são a mesma coisa;
// - com sessão e os termos em dia: vai direto para o `next`;
// - com sessão e termos pendentes: só o aceite, sem pedir código de novo.
// Depois do login ou do aceite, volta para o `next` (validado em src/lib/next.js): dentro do imago
// pelo router, para uma aplicação ou o site com navegação de página inteira
export default function Login() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const next = resolveNext(searchParams.get('next'));
  // Sempre busca de novo ao abrir: um /me guardado de antes (sessão que acabou) mandaria de volta
  // para o `next`, que responderia 401 de novo
  const me = useMe({ staleTime: 0, refetchOnMount: 'always' });
  const checked = me.isFetchedAfterMount;
  // Sem sessão, o /me nunca teve dados, e o TanStack Query põe toda busca nova dele (a depois do
  // código, a de quando a aba volta ao foco) em `pending`, sem o erro da anterior. Até ela
  // terminar, vale a última resposta: o formulário não desmonta (o passo do código, o que foi
  // digitado e o botão ocupado continuam) e nenhum erro pisca na tela
  const settledSignedOut = me.isError && me.error.status === 401;
  const [lastSignedOut, setLastSignedOut] = useState(settledSignedOut);
  if (!me.isPending && lastSignedOut !== settledSignedOut) setLastSignedOut(settledSignedOut);
  const signedOut = me.isPending ? lastSignedOut : settledSignedOut;
  const user = signedOut ? undefined : me.data;
  const proceed = checked && user !== undefined && !user.terms_pending;

  useEffect(() => {
    if (!proceed) return;
    const route = appRoute(next);
    if (route === null) pageLocation.replace(next);
    else void navigate(route, { replace: true });
  }, [proceed, next, navigate]);

  // Depois do código certo: o que estava em cache era de outra sessão. A busca do /me decide entre
  // o aceite e o `next`; até ela terminar, o botão de entrar continua ocupado. Se o /me continuar
  // sem sessão, o navegador não guardou o cookie: vira um erro na tela, em vez de nada acontecer
  const refreshSession = async () => {
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== meQueryKey[0] });
    await queryClient.invalidateQueries({ queryKey: meQueryKey });
    if (queryClient.getQueryState(meQueryKey)?.error?.status === 401) {
      throw new ApiError(0, SESSION_NOT_SAVED);
    }
  };

  const accepting = checked && user?.terms_pending === true;
  const title = accepting ? t('pages.terms_acceptance.title') : t('pages.login.title');

  let content;
  // Também a nova busca depois de um erro que não é 401 (o "tentar de novo")
  if (!checked || (me.isPending && !signedOut)) {
    content = <p role="status">{t('common.loading')}</p>;
  } else if (signedOut) {
    content = (
      <>
        <CodeForm onSignedIn={refreshSession} />
        <p className={styles.consent}>
          <Trans
            i18nKey="pages.login.consent"
            components={{
              terms: <Link to={PATHS.terms} target="_blank" rel="noreferrer" />,
              privacy: <Link to={PATHS.privacy} target="_blank" rel="noreferrer" />,
            }}
          />
        </p>
      </>
    );
  } else if (user === undefined) {
    content = <ErrorMessage error={me.error} onRetry={() => me.refetch()} />;
  } else if (user.terms_pending) {
    content = <TermsAcceptance me={user} />;
  } else {
    content = <p role="status">{t('common.redirecting')}</p>;
  }

  return (
    <div className={styles.page}>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>
      {/* Vindo da exclusão da conta (tela de conta) */}
      {location.state?.accountDeleted === true && signedOut && (
        <p role="status" className={styles.notice}>
          {t('pages.login.account_deleted')}
        </p>
      )}
      {content}
    </div>
  );
}
