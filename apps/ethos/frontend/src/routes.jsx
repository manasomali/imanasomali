import Layout from './components/Layout';
import RequireAdmin from './components/RequireAdmin';
import RequireSession from './components/RequireSession';
import Account from './pages/Account';
import AdminAccounts from './pages/Admin/Accounts';
import AdminBanners from './pages/Admin/Banners';
import AdminUserHabits from './pages/Admin/UserHabits';
import HabitLayout from './pages/Habit';
import HabitAlerts from './pages/HabitAlerts';
import HabitCalendar from './pages/HabitCalendar';
import HabitSettings from './pages/HabitSettings';
import HabitSharing from './pages/HabitSharing';
import History from './pages/History';
import Home from './pages/Home';
import Invites from './pages/Invites';
import Legal from './pages/Legal';
import Login from './pages/Login';
import NewHabit from './pages/NewHabit';
import NotFound from './pages/NotFound';
import Report from './pages/Report/LazyReport';
import { HABIT_SECTION, PATHS } from './paths';

// Todas as rotas, relativas ao basename /ethos. Tela que exige sessão entra como filha de
// RequireSession; telas públicas (login, termos, privacidade) ficam fora dele. O painel de admin
// fica dentro de RequireAdmin (quem não é admin volta para a tela inicial)
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
          { path: PATHS.home, element: <Home /> },
          { path: PATHS.account, element: <Account /> },
          { path: PATHS.report, element: <Report /> },
          { path: PATHS.newHabit, element: <NewHabit /> },
          { path: PATHS.invites, element: <Invites /> },
          { path: PATHS.history, element: <History /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: PATHS.admin, element: <AdminAccounts /> },
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
