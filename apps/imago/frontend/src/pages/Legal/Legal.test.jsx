import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SUPPORT_EMAIL, TERMS_VERSION } from '../../lib/legal';
import { BASENAME, PATHS } from '../../paths';
import { axe } from '../../test/axe';
import { createTestI18n } from '../../test/i18n';
import { renderApp } from '../../test/render';
import { trackRequests } from '../../test/server';

// Sem handler do /me: as páginas legais abrem sem login e não chamam a API (uma chamada falharia
// o teste, pelo onUnhandledRequest)
describe('legal pages', () => {
  it.each([
    ['terms', PATHS.terms, 'en', 'Terms of use', 'Version'],
    ['terms', PATHS.terms, 'pt', 'Termos de uso', 'Versão'],
    ['privacy', PATHS.privacy, 'en', 'Privacy policy', 'Version'],
    ['privacy', PATHS.privacy, 'pt', 'Política de privacidade', 'Versão'],
  ])('renders the %s in %s without signing in', async (_, path, language, title, version) => {
    window.localStorage.setItem('i18nextLng', language);
    createTestI18n();
    const requests = trackRequests();
    const { container } = renderApp(path);

    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeDefined();
    expect(document.title).toBe(`${title} · imago`);
    expect(screen.getByText(`${version} ${TERMS_VERSION}`)).toBeDefined();
    expect(container.querySelector('article').getAttribute('lang')).toBe(language);
    // Cada aplicação tem a sua seção, e o email de suporte aparece no contato
    expect(screen.getByRole('heading', { level: 2, name: 'ethos' })).toBeDefined();
    expect(container.textContent).toContain(SUPPORT_EMAIL);
    expect(container.textContent).not.toContain('{{supportEmail}}');
    expect(requests).toEqual([]);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('links each section from the contents, by its id', async () => {
    const user = userEvent.setup();
    const { router } = renderApp(PATHS.privacy);

    const contents = await screen.findByRole('navigation', { name: 'Contents' });
    await user.click(within(contents).getByRole('link', { name: 'Deleting your account' }));

    expect(router.state.location.hash).toBe('#deletion');
    expect(document.getElementById('deletion')).not.toBeNull();
  });

  it('is linked from the footer of every screen', async () => {
    const { container } = renderApp(PATHS.terms);
    await screen.findByRole('heading', { level: 1, name: 'Terms of use' });

    const footer = screen.getByRole('navigation', { name: 'Legal texts' });

    expect(within(footer).getByRole('link', { name: 'Terms of use' }).getAttribute('href')).toBe(
      `${BASENAME}${PATHS.terms}`,
    );
    expect(within(footer).getByRole('link', { name: 'Privacy policy' }).getAttribute('href')).toBe(
      `${BASENAME}${PATHS.privacy}`,
    );
    expect(within(footer).getByRole('link', { name: 'manasomali.com' }).getAttribute('href')).toBe('/');
    expect(await axe(container)).toHaveNoViolations();
  });
});
