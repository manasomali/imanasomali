import Layout from './components/Layout';
import NotFound from './pages/NotFound';

// Todas as rotas, relativas ao basename /imago. As telas entram como filhas do Layout
export const routes = [
  {
    element: <Layout />,
    children: [{ path: '*', element: <NotFound /> }],
  },
];
