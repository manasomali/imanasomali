import { meFixture } from './render';

/** O admin dos testes (conta 101 do seed, fuso de São Paulo, UTC-3 sem horário de verão). */
export const ADMIN = meFixture({ is_admin: true });

/** Uma conta como no GET /admin/users (AdminUser). */
export function accountFixture(overrides = {}) {
  return {
    id: 102,
    email: 'bia@example.com',
    status: 'active',
    is_active: true,
    is_admin: false,
    timezone: 'America/Sao_Paulo',
    locale: 'pt',
    created_at: '2026-10-01T12:00:00Z',
    last_login_at: '2026-10-20T15:30:00Z',
    ...overrides,
  };
}

/** Resposta do GET /admin/mail (MailStats). */
export function mailFixture(overrides = {}) {
  return {
    window_hours: 24,
    by_app: [
      { app: 'imago', code: 12, account: 1, notification: 0 },
      { app: 'ethos', code: 0, account: 0, notification: 30 },
    ],
    day: { sent: 43, limit: 275, notification_limit: 215 },
    hour: { sent: 5, limit: 60, notification_limit: 45 },
    ...overrides,
  };
}
