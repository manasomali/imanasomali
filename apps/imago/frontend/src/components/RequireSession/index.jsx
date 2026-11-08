import { Outlet } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMe } from '../../api/account';
import ErrorMessage from '../ErrorMessage';

// Rotas que exigem sessão. Busca GET /me; o 401 leva para a tela de entrar pelo tratamento global
// do QueryClient (src/bootstrap.js), então aqui ele só não desenha nada. Termos pendentes passam:
// a tela de conta funciona com eles (sair e excluir a conta), e o RequireAdmin manda aceitar
export default function RequireSession() {
  const { t } = useTranslation();
  const me = useMe();

  if (me.isPending) return <p role="status">{t('common.loading')}</p>;
  if (me.error?.status === 401) return null;
  // Falha ao recarregar (ex.: sem rede) com o usuário já carregado: a tela continua
  if (me.data === undefined) {
    return <ErrorMessage error={me.error} onRetry={() => me.refetch()} />;
  }
  return <Outlet />;
}
