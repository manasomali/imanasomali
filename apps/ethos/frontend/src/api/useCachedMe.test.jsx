import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { meQueryKey, useCachedMe } from './auth';

// Como o menu: lê o usuário do cache e, quando ele chega, liga a consulta dos convites
function useMenuLikeState() {
  const me = useCachedMe();
  useQuery({ queryKey: ['sharing', 'received'], queryFn: () => [], enabled: Boolean(me) });
  return me;
}

// Um componente por teste: o React só mostra o aviso uma vez por nome de componente na execução
function RenderPhaseProbe() {
  const me = useMenuLikeState();
  return <p>{me ? `me ${me.id}` : 'signed out'}</p>;
}

function FollowProbe() {
  const me = useMenuLikeState();
  return <p>{me ? `me ${me.id}` : 'signed out'}</p>;
}

function renderProbe(Probe, queryClient) {
  return render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <Probe />
      </QueryClientProvider>
    </StrictMode>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useCachedMe', () => {
  it('does not update the component while it renders (React "setState in render" warning)', async () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    const queryClient = new QueryClient();
    renderProbe(RenderPhaseProbe, queryClient);

    // O login limpa o cache (a consulta dos convites some) e depois o usuário chega: no render
    // seguinte, o componente cria de novo a consulta dos convites, e o cache avisa no meio dele
    await act(async () => queryClient.clear());
    await act(async () => queryClient.setQueryData(meQueryKey, { id: 1 }));
    expect(await screen.findByText('me 1')).toBeDefined();

    const renderPhaseUpdates = errors.mock.calls.filter(([message]) =>
      String(message).includes('Cannot update a component'),
    );
    expect(renderPhaseUpdates).toEqual([]);
  });

  it('follows the signed-in user in the cache, and the sign-out that clears it', async () => {
    const queryClient = new QueryClient();
    renderProbe(FollowProbe, queryClient);
    expect(screen.getByText('signed out')).toBeDefined();

    await act(async () => queryClient.setQueryData(meQueryKey, { id: 1 }));
    expect(await screen.findByText('me 1')).toBeDefined();

    await act(async () => queryClient.setQueryData(meQueryKey, { id: 2 }));
    expect(await screen.findByText('me 2')).toBeDefined();

    await act(async () => queryClient.clear());
    expect(await screen.findByText('signed out')).toBeDefined();
  });
});
