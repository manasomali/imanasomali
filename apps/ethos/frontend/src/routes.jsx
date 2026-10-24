import Layout from './components/Layout';
import RequireSession from './components/RequireSession';
import Account from './pages/Account';
import Home from './pages/Home';
import Login from './pages/Login';
import NotFound from './pages/NotFound';
import { PATHS } from './paths';

// Todas as rotas, relativas ao basename /ethos. Tela que exige sessão entra como filha de
// RequireSession; telas públicas (login, termos, privacidade) ficam fora dele
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
        ],
      },
      { path: '*', element: <NotFound /> },
    ],
  },
];
