import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App';
import { createApp } from './bootstrap';
import { createI18n } from './i18n';

createI18n();
const { router, queryClient } = createApp();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App router={router} queryClient={queryClient} />
  </StrictMode>,
);
