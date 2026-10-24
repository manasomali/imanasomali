import { describe, expect, it } from 'vitest';
import { HttpResponse, http } from 'msw';
import { browserTimezone } from '../lib/time';
import { api, server } from '../test/server';
import { apiLocale, fetchMe, verifyCode } from './auth';

describe('auth API', () => {
  it('sends the browser time zone and language on verify (first access)', async () => {
    let body;
    server.use(
      http.post(api('/auth/code/verify'), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ new_account: true });
      }),
    );

    await expect(
      verifyCode({ email: 'ana@example.com', code: '123456', language: 'pt-BR' }),
    ).resolves.toEqual({ new_account: true });
    expect(body).toEqual({
      email: 'ana@example.com',
      code: '123456',
      timezone: browserTimezone(),
      locale: 'pt',
    });
  });

  it('reads the signed-in user', async () => {
    server.use(http.get(api('/auth/me'), () => HttpResponse.json({ id: 1 })));

    await expect(fetchMe()).resolves.toEqual({ id: 1 });
  });

  it.each([
    ['pt', 'pt'],
    ['pt-BR', 'pt'],
    ['PT', 'pt'],
    ['en', 'en'],
    ['en-US', 'en'],
    ['de', 'en'],
    [undefined, 'en'],
  ])('maps the screen language %s to the API locale %s', (language, locale) => {
    expect(apiLocale(language)).toBe(locale);
  });
});
