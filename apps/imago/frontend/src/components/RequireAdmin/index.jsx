import { Navigate, Outlet, useLocation } from 'react-router';
import { useMe } from '../../api/account';
import { loginPath } from '../../lib/session';
import { BASENAME, PATHS } from '../../paths';

// Rotas do admin, filhas de RequireSession (o usuário já está carregado). Com termos pendentes, a
// API recusa o admin (403 terms_not_accepted): vai para o aceite, na tela de entrar, que volta para
// cá. Quem não é admin volta para a tela de conta. É só conveniência: quem garante é o backend (403)
export default function RequireAdmin() {
  const me = useMe().data;
  const { pathname, search, hash } = useLocation();

  if (me.terms_pending) {
    return <Navigate to={loginPath(`${BASENAME}${pathname}${search}${hash}`)} replace />;
  }
  if (!me.is_admin) return <Navigate to={PATHS.account} replace />;
  return <Outlet />;
}
