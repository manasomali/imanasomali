import ExternalRedirect from './components/ExternalRedirect';
import Layout from './components/Layout';
import RequireAdmin from './components/RequireAdmin';
import RequireSession from './components/RequireSession';
import AdminUsers from './pages/Admin/Accounts';
import AdminBanners from './pages/Admin/Banners';
import AdminUserHabits from './pages/Admin/UserHabits';
import HabitLayout from './pages/Habit';
import HabitAlerts from './pages/HabitAlerts';
import HabitCalendar from './pages/HabitCalendar';
import HabitSettings from './pages/HabitSettings';
import HabitSharing from './pages/HabitSharing';
import Help from './pages/Help';
import History from './pages/History';
import Home from './pages/Home';
import Invites from './pages/Invites';
import NewHabit from './pages/NewHabit';
import NotFound from './pages/NotFound';
import Report from './pages/Report/LazyReport';
import { HABIT_SECTION, LEGACY_REDIRECTS, PATHS } from './paths';

// Todas as rotas, relativas ao basename /ethos. Tela que exige login é filha de RequireSession; a
// ajuda é pública. Login, conta, termos e privacidade são do imago (/imago/...): as rotas antigas
// do ethos levam para lá (LEGACY_REDIRECTS). O painel de admin fica dentro de RequireAdmin (quem
// não é admin volta para a tela inicial)
export const routes = [
  {
    element: <Layout />,
    children: [
      ...Object.entries(LEGACY_REDIRECTS).map(([path, to]) => ({
        path,
        element: <ExternalRedirect to={to} />,
      })),
      { path: PATHS.help, element: <Help /> },
      {
        element: <RequireSession />,
        children: [
          { path: PATHS.home, element: <Home /> },
          { path: PATHS.report, element: <Report /> },
          { path: PATHS.newHabit, element: <NewHabit /> },
          { path: PATHS.invites, element: <Invites /> },
          { path: PATHS.history, element: <History /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: PATHS.admin, element: <AdminUsers /> },
              { path: PATHS.adminUser, element: <AdminUserHabits /> },
              { path: PATHS.adminBanners, element: <AdminBanners /> },
            ],
          },
          {
            // Aba do hábito. Seções novas entram como filhas, com `path: HABIT_SECTION.<nome>`
            // (ex.: { path: HABIT_SECTION.alerts, element: <HabitAlerts /> }), e no HabitNav
            path: PATHS.habit,
            element: <HabitLayout />,
            children: [
              { index: true, element: <HabitCalendar /> },
              { path: HABIT_SECTION.settings, element: <HabitSettings /> },
              { path: HABIT_SECTION.sharing, element: <HabitSharing /> },
              { path: HABIT_SECTION.alerts, element: <HabitAlerts /> },
            ],
          },
        ],
      },
      { path: '*', element: <NotFound /> },
    ],
  },
];
