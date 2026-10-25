import { readFile } from 'node:fs/promises';
import {
  codeFromEmail,
  createHabit,
  expect,
  expectAccessible,
  goByMenu,
  inbox,
  login,
  test,
  toggleToday,
  uniqueEmail,
} from './support.js';

// O backend aceita 1 código por minuto por email, contando junto o de login e o de exclusão
const EMAIL_CODE_INTERVAL_MS = 60_000;

test('exclui a conta com o código do email', async ({ page, request }, testInfo) => {
  // Espera o minuto entre o código de login e o de exclusão (limite do backend, como em produção)
  test.slow();
  const email = uniqueEmail(testInfo, 'delete');
  await login(page, request, email);
  await createHabit(page, 'Beber água');
  await toggleToday(page, { marked: true });

  await goByMenu(page, 'Conta');
  await expect(page.getByRole('heading', { level: 1, name: 'Conta' })).toBeVisible();
  await page.getByRole('button', { name: 'Excluir minha conta…' }).click();
  const panel = page.getByRole('group', { name: 'O que some com a conta' });
  await expect(panel.getByText('Você é dono de 1 hábito (contando os arquivados).')).toBeVisible();
  await expectAccessible(page);
  await panel.getByRole('button', { name: 'Continuar' }).click();

  // Cópia dos dados antes de excluir (o "Exportar tudo" em CSV)
  const exportStep = page.getByRole('group', { name: 'Leve uma cópia dos seus dados' });
  const downloading = page.waitForEvent('download');
  await exportStep.getByRole('button', { name: 'Exportar tudo (CSV)' }).click();
  const csv = await readFile(await (await downloading).path(), 'utf8');
  expect(csv).toMatch(/^\uFEFFHábito,Data,Horário,Autor/);
  expect(csv).toContain(`Beber água,`);
  await exportStep.getByRole('button', { name: 'Continuar' }).click();

  // Pede o código; enquanto o minuto do código de login não passou, a API responde 429 e a tela
  // mostra o erro. O pedido recusado não cria código, então tentar de novo não muda nada
  const requestStep = page.getByRole('group', { name: 'Código de confirmação' });
  const codeStep = page.getByRole('group', { name: 'Digite o código' });
  const rateLimited = requestStep.getByText('Muitas tentativas. Tente mais tarde.');
  await expect(async () => {
    await requestStep.getByRole('button', { name: 'Enviar código' }).click();
    await expect(codeStep.or(rateLimited)).toBeVisible();
    await expect(codeStep).toBeVisible({ timeout: 1_000 });
  }).toPass({ intervals: [5_000], timeout: EMAIL_CODE_INTERVAL_MS + 30_000 });

  const code = await codeFromEmail(request, email, { count: 2, subject: /excluir sua conta/ });
  await codeStep.getByLabel('Código de 6 dígitos').fill(code);
  await codeStep.getByRole('checkbox', { name: /^Entendo que a conta e os dados somem na hora/ }).check();
  await codeStep.getByRole('button', { name: 'Excluir minha conta' }).click();

  await expect(page.getByRole('heading', { level: 1, name: 'Entrar' })).toBeVisible();
  await expect(page.getByText('Sua conta foi excluída. Enviamos uma confirmação para o seu email.')).toBeVisible();
  await expect
    .poll(async () => (await inbox(request, email)).map((message) => message.subject))
    .toContain('Sua conta do ethos foi excluída');

  // A sessão acabou: a tela inicial manda para o login
  await page.goto('/ethos/');
  await expect(page.getByRole('heading', { level: 1, name: 'Entrar' })).toBeVisible();
});
