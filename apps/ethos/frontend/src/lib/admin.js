// Regras do painel de admin que não dependem do React: filtros da listagem de contas,
// confirmação das ações destrutivas e o id da conta vindo da URL

const USER_ID_RE = /^[1-9]\d{0,14}$/;

export const ACCOUNT_STATUSES = Object.freeze(['active', 'blocked']);

export const EMPTY_ACCOUNT_FILTERS = Object.freeze({
  email: '',
  status: '',
  created_from: '',
  created_to: '',
  last_login_from: '',
  last_login_to: '',
});

/**
 * Query do GET /admin/users a partir do formulário de filtros: campo vazio fica de fora, email sem
 * os espaços das pontas e status só se for um dos conhecidos.
 */
export function accountQuery(filters) {
  const query = {};
  const email = filters.email?.trim();
  if (email) query.email = email;
  if (ACCOUNT_STATUSES.includes(filters.status)) query.status = filters.status;
  for (const name of ['created_from', 'created_to', 'last_login_from', 'last_login_to']) {
    if (filters[name]) query[name] = filters[name];
  }
  return query;
}

/**
 * A ação destrutiva só libera quando o admin digita o email da conta. Espaços nas pontas e
 * maiúsculas não importam (o email é salvo em minúsculas); trecho ou outro email não passa.
 */
export function confirmsEmail(typed, email) {
  if (typeof typed !== 'string' || typeof email !== 'string' || email === '') return false;
  return typed.trim().toLowerCase() === email.toLowerCase();
}

/** Id de conta do parâmetro da URL (inteiro positivo), ou null. */
export function parseUserId(value) {
  return typeof value === 'string' && USER_ID_RE.test(value) ? Number(value) : null;
}
