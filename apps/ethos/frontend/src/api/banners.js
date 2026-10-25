// Banner público: GET /banners/active, sem login. O Layout busca em toda tela, inclusive nas
// públicas (login, termos)

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';

export const activeBannerQueryKey = ['banners', 'active'];

/** {banner: {id, text_pt, text_en, starts_at, ends_at} | null} */
export function fetchActiveBanner({ signal } = {}) {
  return apiFetch('/banners/active', { signal });
}

/** O banner no ar (ou null). Falha ao buscar não mostra nada: o banner é só um aviso. */
export function useActiveBanner() {
  return useQuery({
    queryKey: activeBannerQueryKey,
    queryFn: fetchActiveBanner,
    staleTime: 5 * 60_000,
    select: (data) => data?.banner ?? null,
  });
}
