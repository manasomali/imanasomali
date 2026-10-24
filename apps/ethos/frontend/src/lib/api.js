// Cliente da API do ethos. Toda chamada passa por apiFetch: mesma origem, cookie de sessão
// (__Host-ethos_session, HttpOnly: o front nunca lê) e erro sempre como ApiError com o código do
// catálogo de app/errors.py. A API nunca manda texto pronto: a tela traduz errors.<codigo>

export const API_BASE = '/api/ethos';

/** Falha de rede (sem resposta do servidor): código só do front, também traduzido. */
export const NETWORK_ERROR = 'network_error';

// Mesmo mapa de app/errors.py (_STATUS_CODES), para respostas que não vêm do FastAPI: o nginx
// responde 429 (limite do auth), 502 e 504 com HTML
const STATUS_CODES = {
  400: 'bad_request',
  401: 'unauthorized',
  403: 'forbidden',
  404: 'not_found',
  405: 'method_not_allowed',
  409: 'conflict',
  422: 'validation_error',
  429: 'rate_limited',
  500: 'internal_error',
  503: 'service_unavailable',
};

const CODE_RE = /^[a-z][a-z0-9_]{0,63}$/;

export class ApiError extends Error {
  constructor(status, code, field = null) {
    super(code);
    this.name = 'ApiError';
    // 0 quando não houve resposta (NETWORK_ERROR)
    this.status = status;
    this.code = code;
    this.field = field;
  }
}

export function codeForStatus(status) {
  if (STATUS_CODES[status]) return STATUS_CODES[status];
  return status >= 500 ? 'internal_error' : 'bad_request';
}

async function errorFromResponse(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    // Corpo vazio ou HTML (nginx): o código sai do status
  }
  const valid = body !== null && typeof body === 'object' && CODE_RE.test(body.error);
  const code = valid ? body.error : codeForStatus(response.status);
  const field = valid && typeof body.field === 'string' ? body.field : null;
  return new ApiError(response.status, code, field);
}

function buildUrl(path, query) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) {
    throw new TypeError(`caminho da API inválido: ${path}`);
  }
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== undefined && item !== null) url.searchParams.append(key, String(item));
    }
  }
  return url;
}

/**
 * Chama a API em `path` (sem o prefixo /api/ethos, ex.: "/auth/me"). `query` vira a query string
 * (lista repete a chave, undefined/null ficam de fora) e `body` vai como JSON. Devolve o JSON da
 * resposta (null no 204) ou lança ApiError. Cancelamento pelo `signal` lança o AbortError do fetch.
 */
export async function apiFetch(path, { method = 'GET', query, body, signal } = {}) {
  const url = buildUrl(path, query);
  const headers = { Accept: 'application/json' };
  const init = { method, headers, credentials: 'include', signal };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let response;
  let text;
  try {
    response = await fetch(url, init);
    if (!response.ok) throw await errorFromResponse(response);
    // A conexão pode cair no meio do corpo
    text = await response.text();
  } catch (error) {
    if (error instanceof ApiError || error?.name === 'AbortError') throw error;
    throw new ApiError(0, NETWORK_ERROR);
  }
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError(response.status, 'internal_error');
  }
}
