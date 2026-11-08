import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BASENAME } from './paths';
import { axe } from './test/axe';
import { renderApp } from './test/render';

// A moldura de todas as telas, numa rota que não existe (sem login e sem chamar a API)
describe('app shell', () => {
  it('shows a not found page inside the layout', async () => {
    const { container } = renderApp('/nada-aqui');

    expect(await screen.findByRole('heading', { level: 1, name: 'Page not found' })).toBeDefined();
    expect(document.title).toBe('Page not found · imago');
    expect(screen.getByRole('link', { name: 'Skip to content' }).getAttribute('href')).toBe('#content');
    expect(screen.getByRole('link', { name: 'Back to your account' }).getAttribute('href')).toBe(BASENAME);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('links to the account and back to the site, outside the /imago basename', async () => {
    renderApp('/nada-aqui');
    await screen.findByRole('heading', { level: 1 });

    const navigation = screen.getByRole('navigation', { name: 'Main navigation' });

    expect(within(navigation).getByRole('link', { name: 'Account' }).getAttribute('href')).toBe(BASENAME);
    expect(within(navigation).getByRole('link', { name: 'manasomali.com' }).getAttribute('href')).toBe('/');
    // Sem sessão carregada, sem o link do admin
    expect(within(navigation).queryByRole('link', { name: 'Admin' })).toBeNull();
    expect(screen.getByRole('link', { name: 'imago' }).getAttribute('href')).toBe(BASENAME);
  });
});

describe('theme and language', () => {
  it('starts with the theme saved by the site and toggles it in the shared key', async () => {
    window.localStorage.setItem('theme', 'dark');
    document.documentElement.dataset.theme = 'dark';
    const user = userEvent.setup();
    renderApp('/nada-aqui');
    await screen.findByRole('heading', { level: 1 });

    await user.click(screen.getByRole('button', { name: 'Use light theme' }));

    expect(window.localStorage.getItem('theme')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(screen.getByRole('button', { name: 'Use dark theme' })).toBeDefined();
  });

  it('switches the screen language and saves it in the shared key', async () => {
    const user = userEvent.setup();
    const { container } = renderApp('/nada-aqui');
    await screen.findByRole('heading', { level: 1, name: 'Page not found' });

    const languages = screen.getByRole('group', { name: 'Language' });
    await user.click(within(languages).getByRole('button', { name: 'pt' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Página não encontrada' })).toBeDefined();
    expect(window.localStorage.getItem('i18nextLng')).toBe('pt');
    expect(document.documentElement.lang).toBe('pt');
    expect(within(languages).getByRole('button', { name: 'pt' }).getAttribute('aria-pressed')).toBe('true');
    expect(await axe(container)).toHaveNoViolations();
  });
});
