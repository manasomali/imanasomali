import Layout from './components/Layout';
import RequireAdmin from './components/RequireAdmin';
import RequireSession from './components/RequireSession';
import Account from './pages/Account';
import AdminAccounts from './pages/Admin/Accounts';
import AdminBanners from './pages/Admin/Banners';
import AdminUserHabits from './pages/Admin/UserHabits';
import Home from './pages/Home';
import Login from './pages/Login';
import NotFound from './pages/NotFound';
import { PATHS } from './paths';

// Todas as rotas, relativas ao basename /ethos. Tela que exige sessão entra como filha de
// RequireSession; telas públicas (login, termos, privacidade) ficam fora dele. O painel de admin
// fica dentro de RequireAdmin (quem não é admin volta para a tela inicial)
export const routes = [
  {
    element: <Layout />,
    children: [
      { path: PATHS.login, element: <Login /> },
      {
        element: <RequireSession />,
        children: [
          { path: PATHS.home, element: <Home /> },
          { path: PATHS.account, element: <Account /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: PATHS.admin, element: <AdminAccounts /> },
              { path: PATHS.adminUser, element: <AdminUserHabits /> },
              { path: PATHS.adminBanners, element: <AdminBanners /> },
            ],
          },
        ],
      },
      { path: '*', element: <NotFound /> },
    ],
  },
];
