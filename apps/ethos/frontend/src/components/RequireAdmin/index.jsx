import { Navigate, Outlet } from 'react-router';
import { useMe } from '../../api/auth';
import { PATHS } from '../../paths';

// Rotas do painel de admin, filhas de RequireSession (o usuário já está carregado). Quem não é
// admin volta para a tela inicial. É só conveniência: quem garante é o backend (AdminUser, 403)
export default function RequireAdmin() {
  const me = useMe();

  if (!me.data?.is_admin) return <Navigate to={PATHS.home} replace />;
  return <Outlet />;
}
