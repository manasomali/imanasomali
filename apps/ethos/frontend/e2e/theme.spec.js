import { readFileSync } from 'node:fs';
import { expect, expectAccessible, openMenu, test } from './support.js';

// --bg dos dois temas, lido de packages/tokens/tokens.css (os tokens do site, do imago e do ethos)
const TOKENS = readFileSync(new URL('../../../../packages/tokens/tokens.css', import.meta.url), 'utf8');

function background(selector) {
  const block = TOKENS.slice(TOKENS.indexOf(`${selector} {`));
  const hex = block.match(/--bg:\s*#([0-9a-f]{6});/i)?.[1];
  if (!hex) throw new Error(`tokens.css sem --bg em ${selector}`);
  const [r, g, b] = [0, 2, 4].map((start) => Number.parseInt(hex.slice(start, start + 2), 16));
  return `rgb(${r}, ${g}, ${b})`;
}

const BACKGROUND = { light: background(':root'), dark: background(":root[data-theme='dark']") };
const OPPOSITE = { light: 'dark', dark: 'light' };
// O botão do tema diz o tema para o qual ele troca
const TOGGLE = { light: 'Usar tema escuro', dark: 'Usar tema claro' };
// Uma tela pública de cada aplicação (sem login, sem redirecionar)
const PAGES = [
  { path: '/imago/entrar', heading: 'Entrar' },
  { path: '/ethos/ajuda', heading: 'Ajuda' },
];

/** Abre a tela e confere o tema dela (`null`: sem escolha salva, segue o sistema). */
async function expectTheme(page, { path, heading }, { chosen, shown }) {
  const response = await page.goto(path);
  // A CSP de produção, do nginx.conf da aplicação
  expect(response.headers()['content-security-policy'], path).toContain("script-src 'self'");
  await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
  const html = page.locator('html');
  if (chosen === null) await expect(html).not.toHaveAttribute('data-theme');
  else await expect(html).toHaveAttribute('data-theme', chosen);
  await expect(page.locator('body')).toHaveCSS('background-color', BACKGROUND[shown]);
}

test('o tema escolhido vale no site, no imago e no ethos (mesma origem)', async ({ page }, testInfo) => {
  // Tema do sistema (prefers-color-scheme) do projeto e a escolha contrária
  const system = testInfo.project.use.colorScheme;
  const chosen = OPPOSITE[system];

  // Sem escolha salva, o imago e o ethos seguem o sistema
  for (const screen of PAGES) {
    await expectTheme(page, screen, { chosen: null, shown: system });
    await expectAccessible(page);
  }

  // O site não sobe no E2E. Ele fica na mesma origem, fora das aplicações, e guarda a escolha em
  // localStorage.theme: uma página fora delas no mesmo nginx (um 404) faz o papel dele
  await page.goto('/site-do-e2e');
  expect(new URL(page.url()).origin).toBe(new URL(testInfo.project.use.baseURL).origin);
  await page.evaluate((theme) => window.localStorage.setItem('theme', theme), chosen);
  for (const screen of PAGES) {
    await expectTheme(page, screen, { chosen, shown: chosen });
    await expectAccessible(page);
  }

  // Trocar no topo do imago grava a mesma chave, que o ethos lê
  await expectTheme(page, PAGES[0], { chosen, shown: chosen });
  await page.getByRole('button', { name: TOGGLE[chosen] }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', system);
  expect(await page.evaluate(() => window.localStorage.getItem('theme'))).toBe(system);
  await expectTheme(page, PAGES[1], { chosen: system, shown: system });

  // E trocar no menu do ethos vale no imago
  await openMenu(page);
  await page.getByRole('button', { name: TOGGLE[system] }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', chosen);
  await expectTheme(page, PAGES[0], { chosen, shown: chosen });
});
