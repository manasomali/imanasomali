// Envios de email do GET /admin/mail (MailStats): quanto cada aplicação mandou nas últimas 24 h,
// por tipo, e quanto falta para o teto compartilhado. Notificações param antes do teto (a reserva
// para códigos e emails de conta, imago-plan.md, "envio de email e limite compartilhado")

export const MAIL_KINDS = Object.freeze(['code', 'account', 'notification']);

// Contagem da API: inteiro >= 0; qualquer outra coisa conta como 0
function count(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

/**
 * Uma janela do teto (`day` ou `hour`: {sent, limit, notification_limit}) com o que falta:
 * `{sent, limit, notificationLimit, remaining, notificationRemaining, full, notificationsStopped}`.
 */
export function mailWindow(stats) {
  const sent = count(stats?.sent);
  const limit = count(stats?.limit);
  const notificationLimit = count(stats?.notification_limit);
  return {
    sent,
    limit,
    notificationLimit,
    remaining: Math.max(0, limit - sent),
    notificationRemaining: Math.max(0, notificationLimit - sent),
    full: sent >= limit,
    notificationsStopped: sent >= notificationLimit,
  };
}

/**
 * Tabela por aplicação: `rows` na ordem da API, cada uma com `{app, code, account, notification,
 * total}`, e `totals` com a soma de cada coluna.
 */
export function mailTable(byApp) {
  const rows = (Array.isArray(byApp) ? byApp : [])
    .filter((row) => row !== null && typeof row === 'object' && typeof row.app === 'string')
    .map((row) => {
      const counts = Object.fromEntries(MAIL_KINDS.map((kind) => [kind, count(row[kind])]));
      const total = MAIL_KINDS.reduce((sum, kind) => sum + counts[kind], 0);
      return { app: row.app, ...counts, total };
    });
  const totals = Object.fromEntries(
    [...MAIL_KINDS, 'total'].map((column) => [column, rows.reduce((sum, row) => sum + row[column], 0)]),
  );
  return { rows, totals };
}
