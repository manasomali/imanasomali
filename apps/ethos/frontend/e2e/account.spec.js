import { readFile } from 'node:fs/promises';
import {
  acceptInvite,
  codeFromEmail,
  createHabit,
  expect,
  expectAccessible,
  goByMenu,
  inbox,
  inviteToHabit,
  login,
  loginPath,
  test,
  toggleToday,
  uniqueEmail,
  waitForPath,
  watchProblems,
} from './support.js';

// O imago aceita 1 código por minuto por email, contando junto o de login e o de exclusão
const EMAIL_CODE_INTERVAL_MS = 60_000;
// A exclusão nas aplicações e os emails saem depois da resposta (BackgroundTasks)
const BACKGROUND_TIMEOUT_MS = 30_000;

test('exclui a conta pela tela de conta do imago, com o código do email, e os dados somem do ethos', async ({ page, otherPage, request }, testInfo) => {
  // Espera o minuto entre o código de login e o de exclusão (limite do imago, como em produção)
  test.slow();
  const email = uniqueEmail(testInfo, 'delete');
  const guestEmail = uniqueEmail(testInfo, 'delete-guest');
  const habitName = 'Beber água';

  // O dono entra primeiro: o minuto até o código de exclusão já começa a contar
  await login(page, request, email);
  await login(otherPage, request, guestEmail);
  await createHabit(page, habitName);
  await toggleToday(page, { marked: true });
  // A convidada entra no hábito do dono: depois da exclusão, ele some para ela também
  await inviteToHabit(page, guestEmail);
  await acceptInvite(otherPage, habitName);

  // A conta é a do imago: o menu do ethos leva para lá
  await goByMenu(page, 'Conta');
  await waitForPath(page, '/imago/');
  await expect(page.getByRole('heading', { level: 1, name: 'Conta' })).toBeVisible();
  await page.getByRole('button', { name: 'Excluir minha conta…' }).click();
  const warning = page.getByRole('group', { name: 'O que some com a conta' });
  await expect(warning.getByRole('listitem').filter({ hasText: /^ethos: os hábitos dos quais você é dono/ })).toBeVisible();
  await expectAccessible(page);
  await warning.getByRole('button', { name: 'Continuar' }).click();

  // Cópia dos dados antes de excluir: o link do ethos abre o relatório noutra aba, com o
  // "Exportar tudo (CSV)"
  const exportStep = page.getByRole('group', { name: 'Leve uma cópia dos seus dados' });
  const opening = page.context().waitForEvent('page');
  await exportStep.getByRole('link', { name: 'Exportar tudo do ethos (na tela de relatório)' }).click();
  const reportPage = await opening;
  const reportProblems = watchProblems(reportPage);
  await waitForPath(reportPage, '/ethos/relatorio');
  await expect(reportPage.getByRole('heading', { level: 1, name: 'Relatório' })).toBeVisible();
  const downloading = reportPage.waitForEvent('download');
  await reportPage.getByRole('button', { name: 'Exportar tudo (CSV)' }).click();
  const csv = await readFile(await (await downloading).path(), 'utf8');
  // BOM e o cabeçalho em pt
  expect(csv.startsWith('\uFEFFHábito,Data,Horário,Autor')).toBe(true);
  expect(csv).toContain(`${habitName},`);
  await reportPage.close();
  expect(reportProblems, 'CSP ou erro de JavaScript no relatório').toEqual([]);
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
  await codeStep.getByRole('checkbox', { name: /^Entendo que a conta e os dados/ }).check();
  await codeStep.getByRole('button', { name: 'Excluir minha conta', exact: true }).click();

  await waitForPath(page, '/imago/entrar');
  await expect(page.getByRole('heading', { level: 1, name: 'Entrar' })).toBeVisible();
  await expect(page.getByText('A sua conta foi excluída de todas as aplicações.')).toBeVisible();

  // O imago só confirma a exclusão depois que o ethos apagou os dados (a tarefa delete)
  await expect
    .poll(async () => (await inbox(request, email)).map((message) => message.subject), {
      timeout: BACKGROUND_TIMEOUT_MS,
    })
    .toContain('Sua conta do manasomali.com foi excluída');
  // O ethos apagou o hábito do dono: a convidada recebe o aviso e o hábito some da lista dela
  await expect
    .poll(async () => (await inbox(request, guestEmail)).map((message) => message.subject), {
      timeout: BACKGROUND_TIMEOUT_MS,
    })
    .toContain('Aviso sobre hábitos compartilhados no ethos');
  const habits = await (await otherPage.request.get('/api/ethos/habits')).json();
  expect(habits.habits.map((habit) => habit.name)).toEqual([]);
  await otherPage.goto('/ethos/');
  await expect(otherPage.getByText('Você ainda não tem hábitos.')).toBeVisible();

  // A sessão do dono acabou: o ethos manda para o login
  expect(await page.context().cookies()).toEqual([]);
  await page.goto('/ethos/');
  await waitForPath(page, loginPath('/ethos/'));
});
