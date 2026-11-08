import { describe, expect, it, vi } from 'vitest';
import { ApiError, NETWORK_ERROR } from './api';
import { createQueryClient, shouldRetry } from './queryClient';

describe('shouldRetry', () => {
  it('retries network failures and 5xx up to twice', () => {
    expect(shouldRetry(0, new ApiError(0, NETWORK_ERROR))).toBe(true);
    expect(shouldRetry(1, new ApiError(503, 'service_unavailable'))).toBe(true);
    expect(shouldRetry(2, new ApiError(503, 'service_unavailable'))).toBe(false);
  });

  it.each([401, 403, 404, 409, 422, 429])('never retries %s', (status) => {
    expect(shouldRetry(0, new ApiError(status, 'x'))).toBe(false);
  });

  it('never retries errors that did not come from the API', () => {
    expect(shouldRetry(0, new Error('bug'))).toBe(false);
  });
});

describe('createQueryClient', () => {
  it('calls onUnauthorized when a query gets 401', async () => {
    const onUnauthorized = vi.fn();
    const client = createQueryClient({ onUnauthorized });

    await client
      .fetchQuery({ queryKey: ['me'], queryFn: () => Promise.reject(new ApiError(401, 'unauthorized')) })
      .catch(() => {});

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('calls onUnauthorized when a mutation gets 401', async () => {
    const onUnauthorized = vi.fn();
    const client = createQueryClient({ onUnauthorized });
    const mutation = client.getMutationCache().build(client, {
      mutationFn: () => Promise.reject(new ApiError(401, 'unauthorized')),
    });

    await mutation.execute().catch(() => {});

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('does not call onUnauthorized for other errors', async () => {
    const onUnauthorized = vi.fn();
    const client = createQueryClient({ onUnauthorized });

    await client
      .fetchQuery({ queryKey: ['x'], queryFn: () => Promise.reject(new ApiError(403, 'forbidden')) })
      .catch(() => {});
    await client
      .fetchQuery({ queryKey: ['y'], queryFn: () => Promise.reject(new Error('bug')), retry: false })
      .catch(() => {});

    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it('works without a handler', async () => {
    const client = createQueryClient();

    await expect(
      client.fetchQuery({ queryKey: ['me'], queryFn: () => Promise.reject(new ApiError(401, 'unauthorized')) }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
