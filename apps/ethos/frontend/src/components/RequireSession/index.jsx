import { Outlet } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMe } from '../../api/auth';
import ErrorMessage from '../ErrorMessage';
import TermsModal from '../TermsModal';
import TimezoneNotice from '../TimezoneNotice';

// Rotas que exigem sessão. Busca GET /auth/me; o 401 leva para o login pelo tratamento global do
// QueryClient (src/bootstrap.js), então aqui ele só não desenha nada. Com uma versão nova dos termos
// por aceitar, só o modal de aceite aparece: a tela não é montada (a API recusaria as chamadas dela
// com 403 terms_not_accepted)
export default function RequireSession() {
  const { t } = useTranslation();
  const me = useMe();

  if (me.isPending) return <p role="status">{t('common.loading')}</p>;
  if (me.error?.status === 401) return null;
  // Falha ao recarregar (ex.: sem rede) com o usuário já carregado: a tela continua
  if (me.data === undefined) {
    return <ErrorMessage error={me.error} onRetry={() => me.refetch()} />;
  }
  if (me.data.terms_pending) return <TermsModal me={me.data} />;
  return (
    <>
      <TimezoneNotice savedTimezone={me.data.timezone} />
      <Outlet />
    </>
  );
}
