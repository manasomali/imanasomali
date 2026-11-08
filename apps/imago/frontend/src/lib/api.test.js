import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpResponse, http } from 'msw';
import { api, server } from '../test/server';
import { ApiError, NETWORK_ERROR, apiFetch, codeForStatus } from './api';

afterEach(() => {
  vi.restoreAllMocks();
});

async function rejection(promise) {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error('a promessa não falhou');
}

describe('apiFetch', () => {
  it('sends JSON with the session cookie and reads JSON back', async () => {
    let seen;
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    server.use(
      http.patch(api('/me'), async ({ request }) => {
        seen = {
          contentType: request.headers.get('content-type'),
          accept: request.headers.get('accept'),
          body: await request.json(),
        };
        return HttpResponse.json({ id: 7 });
      }),
    );

    await expect(apiFetch('/me', { method: 'PATCH', body: { locale: 'pt' } })).resolves.toEqual({
      id: 7,
    });
    // O MSW não repassa o credentials para o Request que ele monta: confere no fetch
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ method: 'PATCH', credentials: 'include' });
    expect(seen).toEqual({
      contentType: 'application/json',
      accept: 'application/json',
      body: { locale: 'pt' },
    });
  });

  it('builds the query string, repeating list keys and skipping empty values', async () => {
    let url;
    server.use(
      http.get(api('/admin/users'), ({ request }) => {
        url = new URL(request.url);
        return HttpResponse.json({});
      }),
    );

    await apiFetch('/admin/users', {
      query: { email: 'bia@', status: ['active', 'blocked'], limit: undefined, cursor: null },
    });

    expect(url.pathname).toBe('/api/imago/admin/users');
    expect(url.searchParams.get('email')).toBe('bia@');
    expect(url.searchParams.getAll('status')).toEqual(['active', 'blocked']);
    expect(url.searchParams.has('limit')).toBe(false);
    expect(url.searchParams.has('cursor')).toBe(false);
  });

  it('returns null for an empty body (204)', async () => {
    server.use(http.post(api('/auth/logout'), () => new HttpResponse(null, { status: 204 })));

    await expect(apiFetch('/auth/logout', { method: 'POST' })).resolves.toBeNull();
  });

  it('turns an API error body into ApiError', async () => {
    server.use(
      http.post(api('/me/delete/request'), () =>
        HttpResponse.json({ error: 'last_admin', field: null }, { status: 409 }),
      ),
    );

    const error = await rejection(apiFetch('/me/delete/request', { method: 'POST' }));

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: 'last_admin', field: null });
  });

  it('keeps the field of a validation error', async () => {
    server.use(
      http.patch(api('/me'), () =>
        HttpResponse.json({ error: 'invalid_timezone', field: 'timezone' }, { status: 422 }),
      ),
    );

    const error = await rejection(apiFetch('/me', { method: 'PATCH', body: {} }));

    expect(error).toMatchObject({ status: 422, code: 'invalid_timezone', field: 'timezone' });
  });

  it('uses the status when the body is not the API format (nginx 429 in HTML)', async () => {
    server.use(
      http.post(api('/auth/code/request'), () =>
        HttpResponse.html('<html><body>429 Too Many Requests</body></html>', { status: 429 }),
      ),
    );

    const error = await rejection(apiFetch('/auth/code/request', { method: 'POST', body: {} }));

    expect(error).toMatchObject({ status: 429, code: 'rate_limited', field: null });
  });

  it('ignores an error code outside the expected format', async () => {
    server.use(
      http.get(api('/me'), () =>
        HttpResponse.json({ error: '<script>', field: 3 }, { status: 403 }),
      ),
    );

    const error = await rejection(apiFetch('/me'));

    expect(error).toMatchObject({ status: 403, code: 'forbidden', field: null });
  });

  it('reports a network failure as network_error', async () => {
    server.use(http.get(api('/me'), () => HttpResponse.error()));

    const error = await rejection(apiFetch('/me'));

    expect(error).toMatchObject({ status: 0, code: NETWORK_ERROR });
  });

  it('rethrows an abort instead of hiding it', async () => {
    const abort = new DOMException('aborted', 'AbortError');
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(abort);

    await expect(apiFetch('/me', { signal: new AbortController().signal })).rejects.toBe(abort);
  });

  it('reports a body cut in the middle as network_error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.reject(new TypeError('terminated')),
    });

    await expect(apiFetch('/me')).rejects.toMatchObject({ status: 0, code: NETWORK_ERROR });
  });

  it('reports an invalid JSON success body as internal_error', async () => {
    server.use(http.get(api('/me'), () => HttpResponse.text('{not json', { status: 200 })));

    await expect(apiFetch('/me')).rejects.toMatchObject({
      status: 200,
      code: 'internal_error',
    });
  });

  it.each(['me', '//evil.example/x', '', undefined])('refuses the path %s', async (path) => {
    await expect(apiFetch(path)).rejects.toThrow(TypeError);
  });
});

describe('codeForStatus', () => {
  it('maps known statuses like app/errors.py', () => {
    expect(codeForStatus(401)).toBe('unauthorized');
    expect(codeForStatus(503)).toBe('service_unavailable');
  });

  it('falls back by range', () => {
    expect(codeForStatus(418)).toBe('bad_request');
    expect(codeForStatus(502)).toBe('internal_error');
  });
});
