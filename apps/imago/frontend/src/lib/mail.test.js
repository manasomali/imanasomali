import { describe, expect, it } from 'vitest';
import { MAIL_KINDS, mailTable, mailWindow } from './mail';

describe('mail window', () => {
  it('says how much is left before the cap and before notifications stop', () => {
    expect(mailWindow({ sent: 43, limit: 275, notification_limit: 215 })).toEqual({
      sent: 43,
      limit: 275,
      notificationLimit: 215,
      remaining: 232,
      notificationRemaining: 172,
      full: false,
      notificationsStopped: false,
    });
  });

  it('stops notifications at their limit, before the cap', () => {
    const values = mailWindow({ sent: 50, limit: 60, notification_limit: 45 });

    expect(values).toMatchObject({ remaining: 10, notificationRemaining: 0, full: false, notificationsStopped: true });
  });

  it('never goes below zero, even past the cap', () => {
    const values = mailWindow({ sent: 280, limit: 275, notification_limit: 215 });

    expect(values).toMatchObject({ remaining: 0, notificationRemaining: 0, full: true, notificationsStopped: true });
  });

  it('counts anything that is not a non-negative integer as zero', () => {
    expect(mailWindow(undefined)).toMatchObject({ sent: 0, limit: 0, remaining: 0, full: true });
    expect(mailWindow({ sent: -3, limit: '275', notification_limit: 1.5 })).toMatchObject({
      sent: 0,
      limit: 0,
      notificationLimit: 0,
    });
  });
});

describe('mail table', () => {
  it('keeps the order of the API, with the total of each row and column', () => {
    const { rows, totals } = mailTable([
      { app: 'imago', code: 12, account: 1, notification: 0 },
      { app: 'ethos', code: 0, account: 0, notification: 30 },
    ]);

    expect(rows).toEqual([
      { app: 'imago', code: 12, account: 1, notification: 0, total: 13 },
      { app: 'ethos', code: 0, account: 0, notification: 30, total: 30 },
    ]);
    expect(totals).toEqual({ code: 12, account: 1, notification: 30, total: 43 });
  });

  it('skips malformed rows and counts missing kinds as zero', () => {
    const { rows, totals } = mailTable([null, 'x', { code: 3 }, { app: 'ethos', notification: 2 }]);

    expect(rows).toEqual([{ app: 'ethos', code: 0, account: 0, notification: 2, total: 2 }]);
    expect(totals.total).toBe(2);
    expect(mailTable(undefined)).toEqual({ rows: [], totals: { code: 0, account: 0, notification: 0, total: 0 } });
  });

  it('has the kinds of mail_log', () => {
    expect(MAIL_KINDS).toEqual(['code', 'account', 'notification']);
  });
});
