import { afterEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TERMS_VERSION, loadLegalDocument } from '../../lib/legal';
import { BASENAME, PATHS } from '../../paths';
import { axe } from '../../test/axe';
import { createTestI18n } from '../../test/i18n';
import { renderApp } from '../../test/render';

// Sem handler do MSW: qualquer chamada à API (ex.: /auth/me) falharia o teste. As páginas
// legais abrem sem login

const CASES = [
  ['terms', PATHS.terms, 'en'],
  ['terms', PATHS.terms, 'pt'],
  ['privacy', PATHS.privacy, 'en'],
  ['privacy', PATHS.privacy, 'pt'],
];

afterEach(() => {
  delete Element.prototype.scrollIntoView;
});

describe('legal pages', () => {
  it.each(CASES)('render the %s at %s in %s, without signing in', async (name, path, language) => {
    window.localStorage.setItem('i18nextLng', language);
    createTestI18n();
    const expected = await loadLegalDocument(name, language);
    const { container } = renderApp(path);

    const heading = await screen.findByRole('heading', { level: 1, name: expected.title });
    const article = heading.closest('article');

    expect(article.getAttribute('lang')).toBe(language);
    expect(document.title).toBe(`${expected.title} · ethos`);
    expect(article.textContent).toContain(TERMS_VERSION);

    // Uma seção por item, com o id como âncora e o título no índice
    const contents = within(article).getByRole('navigation');
    for (const section of expected.sections) {
      const element = container.querySelector(`section#${section.id}`);
      expect(within(element).getByRole('heading', { level: 2 }).textContent).toBe(section.title);
      expect(within(contents).getByRole('link', { name: section.title }).getAttribute('href')).toBe(
        `${BASENAME}${path}#${section.id}`,
      );
      // Parágrafos como <p> e listas como <ul>, sempre como texto
      const paragraphs = section.paragraphs.filter((block) => !Array.isArray(block));
      const lists = section.paragraphs.filter((block) => Array.isArray(block));
      expect([...element.querySelectorAll('p')].map((p) => p.textContent)).toEqual(paragraphs);
      expect([...element.querySelectorAll('ul')].map((ul) =>
        [...ul.querySelectorAll('li')].map((li) => li.textContent),
      )).toEqual(lists);
    }
    expect(await axe(container)).toHaveNoViolations();
  });

  it('shows the support email from the build', async () => {
    renderApp(PATHS.privacy);

    await screen.findByRole('heading', { level: 1, name: 'Privacy policy' });

    expect(document.body.textContent).toContain('suporte@manasomali.com');
    expect(document.body.textContent).not.toContain('{{supportEmail}}');
  });

  it('scrolls to the section of a direct link once the text arrives', async () => {
    // O jsdom não tem scrollIntoView
    const scrolled = [];
    Element.prototype.scrollIntoView = function scrollIntoView() {
      scrolled.push(this.id);
    };
    renderApp(`${PATHS.terms}#sharing`);

    await screen.findByRole('heading', { level: 1, name: 'Terms of use' });

    await waitFor(() => expect(scrolled).toContain('sharing'));
  });

  it('follows the language switch', async () => {
    const user = userEvent.setup();
    renderApp(PATHS.terms);
    await screen.findByRole('heading', { level: 1, name: 'Terms of use' });

    await user.click(screen.getByRole('button', { name: 'pt' }));

    const heading = await screen.findByRole('heading', { level: 1, name: 'Termos de uso' });
    expect(heading.closest('article').getAttribute('lang')).toBe('pt');
  });

  it('are linked from the footer of every screen', async () => {
    const user = userEvent.setup();
    renderApp(PATHS.terms);
    await screen.findByRole('heading', { level: 1, name: 'Terms of use' });

    const footer = screen.getByRole('navigation', { name: 'Legal texts' });
    expect(within(footer).getByRole('link', { name: 'Terms of use' }).getAttribute('href')).toBe(
      `${BASENAME}${PATHS.terms}`,
    );

    await user.click(within(footer).getByRole('link', { name: 'Privacy policy' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Privacy policy' })).toBeDefined();
  });
});
