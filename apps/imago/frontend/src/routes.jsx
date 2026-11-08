import Layout from './components/Layout';
import Legal from './pages/Legal';
import Login from './pages/Login';
import NotFound from './pages/NotFound';
import { PATHS } from './paths';

// Todas as rotas, relativas ao basename /imago. As telas entram como filhas do Layout; entrar, os
// termos e a privacidade abrem sem login
export const routes = [
  {
    element: <Layout />,
    children: [
      { path: PATHS.login, element: <Login /> },
      { path: PATHS.terms, element: <Legal key="terms" name="terms" /> },
      { path: PATHS.privacy, element: <Legal key="privacy" name="privacy" /> },
      { path: '*', element: <NotFound /> },
    ],
  },
];
