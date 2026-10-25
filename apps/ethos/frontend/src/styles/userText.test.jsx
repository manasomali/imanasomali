import { describe, expect, it, vi } from 'vitest';
import { configure, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { accountFixture, signedIn as adminSignedIn } from '../test/admin';
import { axe } from '../test/axe';
import { readFrontendFile } from '../test/files';
import { habitFixture, markFixture, mockHabitsApi } from '../test/habits';
import { meFixture, renderApp } from '../test/render';
import { activeBanner, api, receivedInvites, server } from '../test/server';
import { memberFixture, mockSharingApi, pendingInviteFixture, receivedInviteFixture } from '../test/sharing';

// Texto longo do usuário sem onde quebrar (ETH-46): o email de 254 caracteres (o máximo) saía da
// caixa, à direita. O jsdom não mede layout, então o teste confere a regra: o texto está num
// elemento que o src/index.css manda quebrar em qualquer ponto (ou cortar com reticências). A
// largura de verdade (320 px e desktop, sem rolagem horizontal) foi conferida no navegador

// O calendário desenha o ano inteiro (com axe): folga para o CI, como nos testes do calendário
vi.setConfig({ testTimeout: 15_000 });
configure({ asyncUtilTimeout: 5_000 });

const LONG_EMAIL = `${'a'.repeat(64)}@${'b'.repeat(63)}.${'c'.repeat(63)}.${'d'.repeat(57)}.com`;
const OTHER_LONG_EMAIL = `${'e'.repeat(64)}@${'f'.repeat(63)}.${'g'.repeat(63)}.${'h'.repeat(57)}.com`;
// Os máximos da API: nome do hábito (60), observação (140) e texto do banner (280)
const LONG_NAME = 'W'.repeat(60);
const LONG_NOTE = 'N'.repeat(140);
const LONG_BANNER = 'B'.repeat(280);

/** Regras do CSS sem comentários, como [seletores, declarações] (sem @media aninhado). */
function cssRules(css) {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
  return [...text.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selector, body]) => [
    selector.split(',').map((part) => part.trim()),
    body,
  ]);
}

const INDEX_CSS = cssRules(readFrontendFile('src/index.css'));

/** Declarações da regra do src/index.css com exatamente este seletor. */
function declarations(selector) {
  const rule = INDEX_CSS.find(([selectors]) => selectors.length === 1 && selectors[0] === selector);
  return rule?.[1] ?? '';
}

// Elementos que o src/index.css manda quebrar em qualquer ponto
const WRAPS = INDEX_CSS.filter(([, body]) => /overflow-wrap:\s*anywhere/.test(body))
  .flatMap(([selectors]) => selectors)
  .join(', ');

/** O texto quebra dentro da caixa: está num elemento com a regra e não numa linha cortada. */
function expectWraps(element) {
  expect(element.closest(WRAPS), element.outerHTML.slice(0, 120)).not.toBeNull();
  expect(element.closest('.truncate')).toBeNull();
}

/** Elemento cujo próprio texto contém `text` (ex.: "From <email>"). */
function textContaining(text) {
  return screen.getByText((content) => content.includes(text));
}

describe('wrapping rule', () => {
  it('breaks user text anywhere in text elements and in .user-text', () => {
    expect(LONG_EMAIL).toHaveLength(254);
    for (const selector of ['h1', 'h2', 'h3', 'h4', 'p', 'dd', 'label', '.user-text']) {
      expect(WRAPS.split(', ')).toContain(selector);
    }
    // min-width: 0 deixa o item de flex ou grid encolher abaixo da palavra mais longa
    expect(declarations('.user-text')).toMatch(/min-width:\s*0;/);
  });

  it('cuts a single line with an ellipsis in .truncate', () => {
    const truncate = declarations('.truncate');
    expect(truncate).toMatch(/overflow:\s*hidden;/);
    expect(truncate).toMatch(/text-overflow:\s*ellipsis;/);
    expect(truncate).toMatch(/white-space:\s*nowrap;/);
    expect(truncate).toMatch(/min-width:\s*0;/);
  });
});

describe('long user text', () => {
  it('wraps the email in the account page', async () => {
    server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture({ email: LONG_EMAIL }))));
    const { container } = renderApp('/conta');

    expectWraps(await screen.findByText(LONG_EMAIL));
    expect(await axe(container)).toHaveNoViolations();
  });

  it('wraps the typed email in the login code step', async () => {
    server.use(
      http.get(api('/auth/me'), () => HttpResponse.json({ error: 'unauthorized', field: null }, { status: 401 })),
      http.post(api('/auth/code/request'), () => HttpResponse.json({ status: 'accepted' }, { status: 202 })),
    );
    const user = userEvent.setup();
    const { container } = renderApp('/entrar');

    await user.click(await screen.findByLabelText('Email'));
    await user.paste(LONG_EMAIL);
    await user.click(screen.getByRole('button', { name: 'Send code' }));
    await screen.findByLabelText('6-digit code');

    expectWraps(textContaining(`We sent a 6-digit code to ${LONG_EMAIL}.`));
    expect(await axe(container)).toHaveNoViolations();
  });

  it('wraps the author and the note of a mark, and cuts the habit name in the tabs', async () => {
    server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
    const habit = habitFixture({ role: 'viewer', notes_enabled: true, code: null, name: LONG_NAME });
    const mark = markFixture({
      author: { id: 2, email: LONG_EMAIL },
      marked_at: new Date().toISOString(),
      note: LONG_NOTE,
    });
    mockHabitsApi({ habits: [habit], marks: { 1: [mark] } });
    const { container } = renderApp('/habits/1');

    expectWraps(await screen.findByText(LONG_EMAIL));
    expectWraps(screen.getByText(LONG_NOTE));
    expectWraps(screen.getByRole('heading', { level: 1, name: LONG_NAME }));

    // Na aba, o nome numa linha só, com reticências: o texto continua inteiro (o leitor de tela lê
    // tudo) e o title mostra o nome ao passar o mouse
    const tab = within(screen.getByRole('navigation', { name: 'Habits' })).getByRole('link', { name: LONG_NAME });
    expect(tab.getAttribute('title')).toBe(LONG_NAME);
    expect(within(tab).getByText(LONG_NAME).classList.contains('truncate')).toBe(true);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('wraps members, sent invites and the removal question in the sharing tab', async () => {
    server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
    const habits = [habitFixture()];
    mockHabitsApi({ habits });
    mockSharingApi({
      members: {
        1: [
          memberFixture(1, 'ana@example.com', 'owner'),
          memberFixture(2, LONG_EMAIL, 'editor'),
        ],
      },
      invites: { 1: [pendingInviteFixture({ email: OTHER_LONG_EMAIL })] },
      habits,
    });
    const user = userEvent.setup();
    const { container } = renderApp('/habits/1/sharing');

    const member = await screen.findByText(LONG_EMAIL);
    expectWraps(member);
    expectWraps(await screen.findByText(OTHER_LONG_EMAIL));

    await user.click(within(member.closest('li')).getByRole('button', { name: 'Remove' }));
    expectWraps(textContaining(`Remove ${LONG_EMAIL} from this habit?`));
    expect(await axe(container)).toHaveNoViolations();
  });

  it('wraps the sender and the habit name of a received invite', async () => {
    server.use(
      http.get(api('/auth/me'), () => HttpResponse.json(meFixture())),
      receivedInvites([
        receivedInviteFixture({
          habit: { id: 9, name: LONG_NAME, color: 'indigo' },
          owner: { id: 4, email: LONG_EMAIL },
        }),
      ]),
    );
    mockHabitsApi();
    const { container } = renderApp('/convites');

    expectWraps(await screen.findByText(`From ${LONG_EMAIL}`));
    expectWraps(screen.getByRole('heading', { level: 2, name: LONG_NAME }));
    expect(await axe(container)).toHaveNoViolations();
  });

  it('wraps the author and the habit of a history event', async () => {
    server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
    const habit = habitFixture({ code: null, name: LONG_NAME });
    mockHabitsApi({ habits: [habit] });
    server.use(
      http.get(api('/history'), () =>
        HttpResponse.json({
          events: [
            {
              id: 10,
              event: 'mark_created',
              created_at: '2026-03-02T15:00:00Z',
              habit: { id: habit.id, label: habit.label },
              author: { id: 2, email: LONG_EMAIL },
              details: {
                mark_id: 100,
                author_id: 2,
                marked_at: '2026-03-02T15:00:00Z',
                duration_minutes: null,
                cost_cents: null,
                has_note: false,
              },
            },
          ],
          next_cursor: null,
        }),
      ),
      http.get(api('/habits/:id/members'), () =>
        HttpResponse.json({
          members: [
            memberFixture(1, 'ana@example.com', 'owner'),
            memberFixture(2, LONG_EMAIL, 'editor'),
          ],
        }),
      ),
    );
    const { container } = renderApp('/historico');

    expectWraps(await screen.findByText(`By ${LONG_EMAIL}`));
    expectWraps(screen.getByRole('link', { name: LONG_NAME }));
    // O filtro de pessoa lista o email (o <select> nativo não quebra a linha, mas ocupa só a largura
    // do campo)
    expect(await screen.findByRole('option', { name: LONG_EMAIL })).toBeDefined();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('wraps the email in the admin account list and in the typed confirmation', async () => {
    adminSignedIn();
    server.use(
      http.get(api('/admin/users'), () =>
        HttpResponse.json({ users: [accountFixture({ email: LONG_EMAIL })], next_cursor: null }),
      ),
    );
    const user = userEvent.setup();
    const { container } = renderApp('/admin');

    const email = await screen.findByText(LONG_EMAIL);
    expectWraps(email);

    await user.click(within(email.closest('li')).getByRole('button', { name: 'Delete' }));
    expectWraps(textContaining(`To confirm, type the account email: ${LONG_EMAIL}`));
    expect(await axe(container)).toHaveNoViolations();
  });

  it('wraps the email, the habit name, the author and the note in the admin account detail', async () => {
    adminSignedIn();
    const habit = habitFixture({ id: 10, code: null, name: LONG_NAME, notes_enabled: true });
    server.use(
      http.get(api('/admin/users/2/habits'), () =>
        HttpResponse.json({
          user: accountFixture({ email: LONG_EMAIL }),
          habits: [habit],
          marks: [markFixture({ habit_id: 10, author: { id: 2, email: LONG_EMAIL }, note: LONG_NOTE })],
          next_cursor: null,
        }),
      ),
    );
    const user = userEvent.setup();
    const { container } = renderApp('/admin/contas/2');

    await user.click(await screen.findByRole('button', { name: 'Show the content' }));

    expectWraps(await screen.findByRole('heading', { level: 2, name: LONG_EMAIL }));
    const marks = screen.getByRole('heading', { level: 2, name: 'Marks' }).closest('section');
    expectWraps(within(marks).getByText(LONG_EMAIL));
    expectWraps(within(marks).getByText(LONG_NOTE));
    expectWraps(screen.getByText(LONG_NAME, { selector: 'h3 span' }));
    expect(await axe(container)).toHaveNoViolations();
  });

  it('wraps the banner text', async () => {
    server.use(
      activeBanner({
        id: 12,
        text_pt: LONG_BANNER,
        text_en: LONG_BANNER,
        starts_at: '2026-10-20T12:00:00Z',
        ends_at: '2099-11-20T12:00:00Z',
      }),
    );
    const { container } = renderApp('/entrar');

    const banner = await screen.findByRole('region', { name: 'Notice' });
    expectWraps(within(banner).getByText(LONG_BANNER));
    expect(await axe(container)).toHaveNoViolations();
  });
});
