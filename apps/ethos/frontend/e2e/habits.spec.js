import { createHabit, expect, expectAccessible, login, test, todayCell, toggleToday, uniqueEmail } from './support.js';

test('entra pelo código do email, cria um hábito, marca e desmarca hoje', async ({ page, request }, testInfo) => {
  const email = uniqueEmail(testInfo, 'habits');
  await login(page, request, email);
  // O cookie da sessão como em produção (o Chromium trata http://127.0.0.1 como origem segura)
  const cookies = await page.context().cookies();
  expect(cookies).toEqual([
    expect.objectContaining({
      name: '__Host-ethos_session',
      domain: '127.0.0.1',
      path: '/',
      httpOnly: true,
      secure: true,
      sameSite: 'Lax',
    }),
  ]);
  await expect(page.getByText('Você ainda não tem hábitos.')).toBeVisible();
  await expectAccessible(page);

  await createHabit(page, 'Ler 20 páginas');
  await expect(await todayCell(page)).toHaveAccessibleName(/\. Não marcado$/);
  await expectAccessible(page);

  // Hábito toggle: hoje no painel do dia, "Marcar este dia" e depois "Desmarcar este dia". Cada
  // escrita fica gravada (confere recarregando)
  await toggleToday(page, { marked: true });
  await page.reload();
  await expect(await todayCell(page)).toHaveAccessibleName(/\. Marcado$/);

  await toggleToday(page, { marked: false });
  await page.reload();
  await expect(await todayCell(page)).toHaveAccessibleName(/\. Não marcado$/);

  // A aba principal mostra o hábito na lista
  await page.getByRole('navigation', { name: 'Hábitos' }).getByRole('link', { name: 'Todos os hábitos' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Hábitos' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Hábitos' }).getByRole('link', { name: 'Ler 20 páginas' })).toBeVisible();
});
