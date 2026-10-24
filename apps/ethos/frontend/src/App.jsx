import { Suspense } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router';

// `router` e `queryClient` vêm de createApp (src/bootstrap.js)
export default function App({ router, queryClient }) {
  return (
    <QueryClientProvider client={queryClient}>
      {/* As traduções chegam por HTTP: a primeira renderização espera por elas */}
      <Suspense fallback={null}>
        <RouterProvider router={router} />
      </Suspense>
    </QueryClientProvider>
  );
}
