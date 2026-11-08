// Regras do admin de contas que não dependem do React: filtros da listagem, situação de cada
// conta, confirmação das ações destrutivas e o caminho da API de uma conta

// Filtro `status` do GET /admin/users
export const ACCOUNT_STATUSES = Object.freeze(['active', 'blocked', 'deleting']);

export const EMPTY_ACCOUNT_FILTERS = Object.freeze({ email: '', status: '' });

/**
 * Query do GET /admin/users a partir do formulário de filtros: campo vazio fica de fora, email sem
 * os espaços das pontas e status só se for um dos conhecidos. O `limit` fica no padrão da API (50).
 */
export function accountQuery(filters) {
  const query = {};
  const email = typeof filters?.email === 'string' ? filters.email.trim() : '';
  if (email) query.email = email;
  if (ACCOUNT_STATUSES.includes(filters?.status)) query.status = filters.status;
  return query;
}

/**
 * Situação de uma conta (AdminUser) para a tela: 'deleting' (exclusão em andamento), 'blocked'
 * (is_active falso) ou 'active'.
 */
export function accountStatus(user) {
  if (user.status === 'deleting') return 'deleting';
  return user.is_active ? 'active' : 'blocked';
}

/**
 * A ação destrutiva só libera quando o admin digita o email da conta. Espaços nas pontas e
 * maiúsculas não importam (o email é salvo em minúsculas); trecho ou outro email não passa.
 */
export function confirmsEmail(typed, email) {
  if (typeof typed !== 'string' || typeof email !== 'string' || email === '') return false;
  return typed.trim().toLowerCase() === email.toLowerCase();
}

/** Caminho da API de uma conta (`/admin/users/{id}` + `suffix`); id fora de 1..2^53-1 lança. */
export function accountApiPath(userId, suffix = '') {
  if (!Number.isSafeInteger(userId) || userId < 1) {
    throw new TypeError(`id de conta inválido: ${userId}`);
  }
  return `/admin/users/${userId}${suffix}`;
}
