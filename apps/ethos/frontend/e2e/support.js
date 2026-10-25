// Fixtures e passos comuns do E2E. Os seletores são por papel e nome acessível, com os textos em
// pt (o navegador do E2E é pt-BR), como nos testes de tela do vitest
import { randomUUID } from 'node:crypto';
import AxeBuilder from '@axe-core/playwright';
import { test as base, expect } from '@playwright/test';
import { MAIL_URL } from './env.js';

// Código de login e de exclusão: os 6 dígitos sozinhos no texto do email
const CODE_PATTERN = /\b(\d{6})\b/;

// Opções do contexto do projeto (celular ou desktop, tema, idioma, fuso), para a segunda pessoa
const CONTEXT_OPTIONS = [
  'baseURL', 'viewport', 'screen', 'userAgent', 'deviceScaleFactor', 'isMobile', 'hasTouch',
  'colorScheme', 'reducedMotion', 'locale', 'timezoneId',
];

/** Junta as violações da CSP de produção e os erros de JavaScript não tratados da página. */
function watchProblems(page) {
  const problems = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) {
      problems.push(message.text());
    }
  });
  page.on('pageerror', (error) => problems.push(`erro na página: ${error.message}`));
  return problems;
}

/**
 * `page` falha o teste com qualquer violação da CSP de produção (os headers do nginx.conf vão no
 * vite preview) ou erro de JavaScript não tratado. `otherPage` é uma segunda pessoa: outro
 * contexto do navegador (cookies e localStorage próprios), com as mesmas opções do projeto.
 */
export const test = base.extend({
  page: async ({ page }, use) => {
    const problems = watchProblems(page);
    await use(page);
    expect(problems, 'CSP ou erro de JavaScript na página').toEqual([]);
  },
  otherPage: async ({ browser }, use, testInfo) => {
    const options = Object.fromEntries(
      CONTEXT_OPTIONS.filter((key) => testInfo.project.use[key] !== undefined).map((key) => [
        key,
        testInfo.project.use[key],
      ]),
    );
    const context = await browser.newContext(options);
    const page = await context.newPage();
    const problems = watchProblems(page);
    await use(page);
    await context.close();
    expect(problems, 'CSP ou erro de JavaScript na segunda página').toEqual([]);
  },
});

export { expect };

/** Email único por teste e projeto: os limites de envio por email não se cruzam. */
export function uniqueEmail(testInfo, label) {
  const project = testInfo.project.name.replace(/[^a-z0-9]+/gi, '-');
  return `e2e-${label}-${project}-${randomUUID().slice(0, 8)}@example.com`.toLowerCase();
}

/** Os emails que o SMTP falso recebeu para `address` (backend/tests/e2e_stack.py). */
export async function inbox(request, address) {
  const response = await request.get(`${MAIL_URL}/emails`, { params: { to: address } });
  expect(response.ok()).toBe(true);
  return response.json();
}

/**
 * Espera o email número `count` (1 = o primeiro) para `address` e devolve o código dele. O envio
 * sai depois da resposta da API (BackgroundTasks), então a caixa é consultada até ele chegar.
 */
export async function codeFromEmail(request, address, { count = 1, subject } = {}) {
  let message;
  await expect
    .poll(async () => {
      const emails = await inbox(request, address);
      message = emails[count - 1];
      return emails.length;
    }, { message: `email ${count} para ${address}` })
    .toBeGreaterThanOrEqual(count);
  if (subject) expect(message.subject).toMatch(subject);
  const code = message.text.match(CODE_PATTERN)?.[1];
  expect(code, 'código de 6 dígitos no email').toBeTruthy();
  return code;
}

/** Abre o menu no celular (no desktop os links já estão à vista). */
export async function openMenu(page) {
  // O cabeçalho já desenhado: só então a visibilidade do botão do menu diz se é celular
  await expect(page.getByRole('banner').getByRole('link', { name: 'ethos', exact: true })).toBeVisible();
  const toggle = page.getByRole('button', { name: 'Abrir menu' });
  if (await toggle.isVisible()) await toggle.click();
  return page.getByRole('navigation', { name: 'Navegação principal' });
}

/** Vai para uma tela pelo menu principal, como a pessoa faria. */
export async function goByMenu(page, name) {
  const nav = await openMenu(page);
  await nav.getByRole('link', { name, exact: true }).click();
}

/**
 * Entra com `email` (uma conta nova) pela tela de login, lendo o código no SMTP falso, e aceita os
 * termos se o modal aparecer. Termina na tela inicial.
 */
export async function login(page, request, email) {
  await page.goto('/ethos/entrar');
  await expect(page.getByRole('heading', { level: 1, name: 'Entrar' })).toBeVisible();
  await page.getByLabel('Email').fill(email);
  await page.getByRole('button', { name: 'Enviar código' }).click();
  const code = await codeFromEmail(request, email, { subject: /código de acesso/ });
  await page.getByLabel('Código de 6 dígitos').fill(code);
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();

  const home = page.getByRole('heading', { level: 1, name: 'Hábitos' });
  const terms = page.getByRole('dialog', { name: 'Novos termos de uso' });
  await expect(home.or(terms)).toBeVisible();
  // Conta nova nasce com os termos atuais aceitos; o modal só aparece quando a versão muda
  if (await terms.isVisible()) {
    await terms.getByRole('button', { name: 'Aceitar e continuar' }).click();
    await expect(terms).toBeHidden();
  }
  await expect(home).toBeVisible();
}

/** Cria um hábito toggle (o padrão do formulário) e termina na aba dele. */
export async function createHabit(page, name) {
  await page.getByRole('link', { name: 'Novo hábito' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Novo hábito' })).toBeVisible();
  await page.getByLabel('Nome', { exact: true }).fill(name);
  await page.getByRole('button', { name: 'Criar hábito' }).click();
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible();
}

/**
 * O dia de hoje no calendário da aba do hábito, depois de as marcações carregarem (antes disso o
 * clique só escolhe o dia, sem marcar). O aviso de carregamento sai no mesmo desenho do calendário.
 */
export async function todayCell(page) {
  await expect(page.getByRole('group', { name: /^Calendário de / })).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Carregando as marcações…' })).toHaveCount(0);
  return page.locator('[data-day][aria-current="date"]');
}

/**
 * Abre a aba do hábito com hoje escolhido no painel do dia (`?day=` na URL, como o link de um dia).
 * Escolher pela URL, e não clicando no dia, vale tanto com o clique que marca na hora quanto com o
 * que só escolhe o dia (ETH-54): marcar e desmarcar ficam nos botões do painel, nas duas versões.
 */
export async function selectToday(page) {
  const day = await (await todayCell(page)).getAttribute('data-day');
  const url = new URL(page.url());
  url.searchParams.set('day', day);
  await page.goto(url.href);
  return todayCell(page);
}

/**
 * Marca ou desmarca hoje pelo botão do painel do dia (hábito toggle) e espera a resposta da API.
 * A tela muda na hora (escrita otimista): sem esperar a resposta, um reload logo depois
 * cancelaria a escrita.
 */
export async function toggleToday(page, { marked }) {
  const cell = await selectToday(page);
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /^\/api\/ethos\/habits\/\d+\/toggle$/.test(new URL(response.url()).pathname),
  );
  await page.getByRole('button', { name: marked ? 'Marcar este dia' : 'Desmarcar este dia' }).click();
  const response = await saved;
  expect(response.status()).toBe(200);
  expect((await response.json()).marked).toBe(marked);
  await expect(cell).toHaveAccessibleName(marked ? /\. Marcado$/ : /\. Não marcado$/);
  await expect(cell).not.toHaveAttribute('data-pending');
  await expect(page.getByRole('button', { name: marked ? 'Desmarcar este dia' : 'Marcar este dia' })).toBeVisible();
  return cell;
}

/**
 * Nenhuma violação do axe (WCAG 2.1 A e AA) na página. No navegador de verdade o axe mede também
 * o contraste, no tema do projeto. As transições ficam desligadas no E2E (`reducedMotion` no
 * playwright.config.js): uma cor no meio da transição daria um contraste que não existe.
 */
export async function expectAccessible(page) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  const violations = results.violations.map(({ id, help, nodes }) => ({
    id,
    help,
    nodes: nodes.map((node) => ({ target: node.target, summary: node.failureSummary })),
  }));
  expect(violations, `axe em ${page.url()}`).toEqual([]);
}
