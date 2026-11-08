// Regras do painel de admin que não dependem do React: filtros da listagem de quem usa o ethos e o
// id da pessoa vindo da URL. As contas (bloquear, trocar email, excluir) são do imago (/imago/admin)

// O id do imago: inteiro de 1 a 2^53 - 1 (Number.MAX_SAFE_INTEGER)
const USER_ID_RE = /^[1-9]\d{0,15}$/;

export const USER_DATE_FILTERS = Object.freeze(['first_seen_from', 'first_seen_to']);

export const EMPTY_USER_FILTERS = Object.freeze({
  email: '',
  first_seen_from: '',
  first_seen_to: '',
});

/**
 * Query do GET /admin/users a partir do formulário de filtros: campo vazio fica de fora e o email
 * vai sem os espaços das pontas.
 */
export function userQuery(filters) {
  const query = {};
  const email = filters.email?.trim();
  if (email) query.email = email;
  for (const name of USER_DATE_FILTERS) {
    if (filters[name]) query[name] = filters[name];
  }
  return query;
}

/** Id da pessoa do parâmetro da URL (inteiro de 1 a 2^53 - 1), ou null. */
export function parseUserId(value) {
  if (typeof value !== 'string' || !USER_ID_RE.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}
