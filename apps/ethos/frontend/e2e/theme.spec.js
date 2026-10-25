import { readFileSync } from 'node:fs';
import { expect, expectAccessible, openMenu, test } from './support.js';

// --bg dos dois temas, lido de packages/tokens/tokens.css (os tokens do site e do ethos)
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
const TOGGLE = { light: 'Usar tema escuro', dark: 'Usar tema claro' };

test('o tema escolhido no site vale no ethos, e o do ethos vale no site', async ({ page }, testInfo) => {
  // Tema do sistema (prefers-color-scheme) do projeto e a escolha contrária, feita "no site"
  const system = testInfo.project.use.colorScheme;
  const chosen = OPPOSITE[system];
  const html = page.locator('html');
  const body = page.locator('body');

  // Sem escolha salva, o ethos segue o sistema. A página sai com a CSP de produção (nginx.conf)
  const response = await page.goto('/ethos/entrar');
  expect(response.headers()['content-security-policy']).toContain("script-src 'self'");
  await expect(page.getByRole('heading', { level: 1, name: 'Entrar' })).toBeVisible();
  await expect(html).not.toHaveAttribute('data-theme');
  await expect(body).toHaveCSS('background-color', BACKGROUND[system]);
  await expectAccessible(page);

  // O site não sobe no E2E. Ele fica na mesma origem, fora de /ethos/, e guarda a escolha em
  // localStorage.theme: uma página fora de /ethos/ no mesmo servidor faz o papel dele
  await page.goto('/');
  expect(new URL(page.url()).origin).toBe(new URL(testInfo.project.use.baseURL).origin);
  await page.evaluate((theme) => window.localStorage.setItem('theme', theme), chosen);

  await page.goto('/ethos/entrar');
  await expect(html).toHaveAttribute('data-theme', chosen);
  await expect(body).toHaveCSS('background-color', BACKGROUND[chosen]);
  await expectAccessible(page);

  // Trocar o tema no ethos grava a mesma chave, que o site lê
  await openMenu(page);
  await page.getByRole('button', { name: TOGGLE[chosen] }).click();
  await expect(html).toHaveAttribute('data-theme', system);
  expect(await page.evaluate(() => window.localStorage.getItem('theme'))).toBe(system);
  await page.reload();
  await expect(html).toHaveAttribute('data-theme', system);
  await expect(body).toHaveCSS('background-color', BACKGROUND[system]);
});
