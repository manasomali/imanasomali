import { afterEach, describe, expect, it, vi } from 'vitest';
import { configure, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { HELP_SECTIONS, loadHelp } from '../../lib/help';
import { SUPPORT_EMAIL } from '../../lib/legal';
import { BASENAME, PATHS } from '../../paths';
import { mockAlertsApi } from '../../test/alerts';
import { axe } from '../../test/axe';
import { habitFixture, mockHabitsApi } from '../../test/habits';
import { createTestI18n } from '../../test/i18n';
import { meFixture, renderApp } from '../../test/render';
import { mockProgressApi } from '../../test/report';
import { api, server } from '../../test/server';
import { memberFixture, mockSharingApi } from '../../test/sharing';

vi.setConfig({ testTimeout: 15_000 });
configure({ asyncUtilTimeout: 5_000 });

// Sem sessão: só o handler padrão do banner (público, no Layout) responde. Qualquer outra chamada
// à API (ex.: /auth/me) falharia o teste, porque a ajuda abre sem login

afterEach(() => {
  delete Element.prototype.scrollIntoView;
});

function signedIn() {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
}

describe('help page', () => {
  it.each(['en', 'pt'])('renders every section in %s, without signing in', async (language) => {
    window.localStorage.setItem('i18nextLng', language);
    createTestI18n();
    const expected = await loadHelp(language);
    const { container } = renderApp(PATHS.help);

    const heading = await screen.findByRole('heading', { level: 1, name: expected.title });
    const article = heading.closest('article');

    expect(article.getAttribute('lang')).toBe(language);
    expect(document.title).toBe(`${expected.title} · ethos`);
    expect(expected.sections.map((section) => section.id)).toEqual([...HELP_SECTIONS]);

    // Uma seção por item, com o id como âncora e o título no sumário
    const contents = within(article).getByRole('navigation');
    for (const section of expected.sections) {
      const element = container.querySelector(`section#${section.id}`);
      expect(within(element).getByRole('heading', { level: 2 }).textContent).toBe(section.title);
      expect(within(contents).getByRole('link', { name: section.title }).getAttribute('href')).toBe(
        `${BASENAME}${PATHS.help}#${section.id}`,
      );
      // Parágrafos como <p> e listas como <ul>, sempre como texto
      const paragraphs = section.paragraphs.filter((block) => !Array.isArray(block));
      const lists = section.paragraphs.filter((block) => Array.isArray(block));
      expect([...element.querySelectorAll('p')].map((p) => p.textContent)).toEqual(paragraphs);
      expect([...element.querySelectorAll('ul')].map((ul) =>
        [...ul.querySelectorAll('li')].map((li) => li.textContent),
      )).toEqual(lists);
    }
    expect(article.textContent).toContain(SUPPORT_EMAIL);
    expect(article.textContent).not.toContain('{{supportEmail}}');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('scrolls to the section of a direct link once the text arrives', async () => {
    // O jsdom não tem scrollIntoView
    const scrolled = [];
    Element.prototype.scrollIntoView = function scrollIntoView() {
      scrolled.push(this.id);
    };
    renderApp(`${PATHS.help}#alerts`);

    await screen.findByRole('heading', { level: 1, name: 'Help' });

    await waitFor(() => expect(scrolled).toContain('alerts'));
  });

  it('follows the language switch', async () => {
    const user = userEvent.setup();
    renderApp(PATHS.help);
    await screen.findByRole('heading', { level: 1, name: 'Help' });

    await user.click(screen.getByRole('button', { name: 'pt' }));

    const heading = await screen.findByRole('heading', { level: 1, name: 'Ajuda' });
    expect(heading.closest('article').getAttribute('lang')).toBe('pt');
  });

  it('is linked from the main menu, with or without a session', async () => {
    const user = userEvent.setup();
    renderApp(PATHS.terms);
    await screen.findByRole('heading', { level: 1, name: 'Terms of use' });

    // Ícone ao lado do idioma e do tema, no cabeçalho
    const menu = screen.getByRole('banner');
    const link = within(menu).getByRole('link', { name: 'Help' });
    expect(link.getAttribute('href')).toBe(`${BASENAME}${PATHS.help}`);

    await user.click(link);

    expect(await screen.findByRole('heading', { level: 1, name: 'Help' })).toBeDefined();
    expect(within(menu).getByRole('link', { name: 'Help' }).getAttribute('aria-current')).toBe('page');
  });
});

/** O ícone de ajuda de um título: o link, que abre a seção em outra aba. */
function helpLink(topic) {
  const link = screen.getByRole('link', { name: `Help: ${topic} (opens in a new tab)` });
  expect(link.getAttribute('target')).toBe('_blank');
  expect(link.getAttribute('rel')).toBe('noopener');
  return link.getAttribute('href');
}

describe('help icons on the screens', () => {
  it('settings point to the goal and to pausing and archiving', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()], marks: {} });
    const { container } = renderApp('/habits/1/settings');
    await screen.findByRole('heading', { level: 2, name: 'Settings' });

    expect(helpLink('Settings')).toBe(`${BASENAME}${PATHS.help}#goal`);
    expect(helpLink('Pause and archive')).toBe(`${BASENAME}${PATHS.help}#pause-archive`);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('a new habit points to the goal', async () => {
    signedIn();
    mockHabitsApi({ habits: [], marks: {} });
    renderApp(PATHS.newHabit);
    await screen.findByRole('heading', { level: 1, name: 'New habit' });

    expect(helpLink('New habit')).toBe(`${BASENAME}${PATHS.help}#goal`);
  });

  it('alerts point to the alerts', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()], marks: {} });
    mockAlertsApi();
    const { container } = renderApp('/habits/1/alerts');
    await screen.findByRole('form', { name: 'Save alerts' });

    expect(helpLink('Alerts')).toBe(`${BASENAME}${PATHS.help}#alerts`);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('sharing points to the sharing', async () => {
    signedIn();
    const habits = [habitFixture()];
    mockHabitsApi({ habits, marks: {} });
    mockSharingApi({ members: { 1: [memberFixture(1, 'ana@example.com', 'owner')] }, habits });
    const { container } = renderApp('/habits/1/sharing');
    await screen.findByText('ana@example.com');

    expect(helpLink('Sharing')).toBe(`${BASENAME}${PATHS.help}#sharing`);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('the account points to the account', async () => {
    signedIn();
    const { container } = renderApp(PATHS.account);
    await screen.findByRole('heading', { level: 1, name: 'Account' });

    expect(helpLink('Account')).toBe(`${BASENAME}${PATHS.help}#account`);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('the report points to the report', async () => {
    signedIn();
    mockHabitsApi({ habits: [habitFixture()], marks: {} });
    // Depois do mockHabitsApi: /habits/progress não pode cair no /habits/:id
    mockProgressApi();
    renderApp(PATHS.report);
    await screen.findByRole('heading', { level: 1, name: 'Report' });

    expect(helpLink('Report')).toBe(`${BASENAME}${PATHS.help}#report`);
  });
});
