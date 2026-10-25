// Rotas do app, relativas ao basename (/ethos). Use estas constantes em vez de escrever o caminho

export const BASENAME = '/ethos';

export const PATHS = Object.freeze({
  home: '/',
  login: '/entrar',
  account: '/conta',
  admin: '/admin',
  adminUser: '/admin/contas/:userId',
  adminBanners: '/admin/banners',
  terms: '/termos',
  privacy: '/privacidade',
  // Criar um hábito. Caminho fixo antes de `/habits/:habitId` (a rota fixa ganha da dinâmica, e
  // "new" nunca é um id)
  newHabit: '/habits/new',
  // Aba de um hábito (HabitLayout). O calendário é a rota índice; as outras seções são rotas
  // filhas (`/habits/:habitId/<seção>`, ver HABIT_SECTION)
  habit: '/habits/:habitId',
  // Relatório e export (ETH-36), de vários hábitos: período e hábitos na query (reportPath)
  report: '/relatorio',
});

/**
 * Caminho do relatório com o período e os hábitos na query: `?from=&to=&habit_id=3&habit_id=5`.
 * Sem `habitIds` (ou vazio): todos os hábitos. Ex.: o atalho da aba do hábito,
 * `reportPath({habitIds: [3]})`.
 */
export function reportPath({ from, to, habitIds } = {}) {
  const params = new URLSearchParams();
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  for (const id of habitIds ?? []) params.append('habit_id', String(id));
  const search = params.toString();
  return search ? `${PATHS.report}?${search}` : PATHS.report;
}

/** Tela do conteúdo dos hábitos de uma conta, no painel de admin. */
export function adminUserPath(userId) {
  return PATHS.adminUser.replace(':userId', encodeURIComponent(String(userId)));
}

// Seções da aba de um hábito: o caminho relativo da rota filha do HabitLayout em src/routes.jsx.
// - `calendar`: o calendário, rota índice;
// - `settings`: configuração (ETH-33, só o dono: pages/HabitSettings);
// - `sharing`: compartilhamento (ETH-34);
// - `alerts`: alertas (ETH-35, dono e editor). Caminho fixo: o email do alerta aponta para
//   `/habits/{id}/alerts` (ALERT_SETTINGS_PATH em app/mail/templates.py; src/paths.test.js confere).
// Ao criar a tela, registre a rota filha e o item do submenu em components/HabitNav.
// Relatório (ETH-36) e histórico (ETH-37) cobrem vários hábitos: ficam fora da aba, como rotas de
// topo em PATHS, e recebem o hábito pela query (ex.: `?habit_id=3`)
export const HABIT_SECTION = Object.freeze({
  calendar: '',
  settings: 'settings',
  sharing: 'sharing',
  alerts: 'alerts',
});

/** Id de hábito do caminho (`:habitId`): inteiro positivo em texto, ou null. */
export function parseHabitId(value) {
  if (typeof value !== 'string' || !/^[1-9]\d{0,15}$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

/**
 * Caminho (sem o basename) da seção `section` da aba do hábito `id`, com a query opcional (ex.:
 * `{day: '2026-03-04'}`; null e undefined ficam de fora).
 */
export function habitPath(id, section = HABIT_SECTION.calendar, query = {}) {
  if (!Number.isSafeInteger(id) || id < 1) throw new TypeError(`id de hábito inválido: ${id}`);
  const path = section ? `/habits/${id}/${section}` : `/habits/${id}`;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}
