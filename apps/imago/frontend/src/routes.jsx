import Layout from './components/Layout';
import RequireAdmin from './components/RequireAdmin';
import RequireSession from './components/RequireSession';
import Account from './pages/Account';
import Admin from './pages/Admin';
import Legal from './pages/Legal';
import Login from './pages/Login';
import NotFound from './pages/NotFound';
import { PATHS } from './paths';

// Todas as rotas, relativas ao basename /imago. Tela que exige sessão entra como filha de
// RequireSession; telas públicas (entrar, termos, privacidade) ficam fora dele. A tela de conta
// funciona com termos pendentes (dá para sair e excluir a conta sem aceitar); o admin fica dentro
// de RequireAdmin, que exige os termos aceitos e is_admin
export const routes = [
  {
    element: <Layout />,
    children: [
      { path: PATHS.login, element: <Login /> },
      { path: PATHS.terms, element: <Legal key="terms" name="terms" /> },
      { path: PATHS.privacy, element: <Legal key="privacy" name="privacy" /> },
      {
        element: <RequireSession />,
        children: [
          { path: PATHS.account, element: <Account /> },
          {
            element: <RequireAdmin />,
            children: [{ path: PATHS.admin, element: <Admin /> }],
          },
        ],
      },
      { path: '*', element: <NotFound /> },
    ],
  },
];
