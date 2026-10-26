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

test('marca e desmarca hoje com duplo clique no dia, uma escrita por duplo clique', async ({ page, request }, testInfo) => {
  await login(page, request, uniqueEmail(testInfo, 'dblclick'));
  await createHabit(page, 'Meditar');
  // Toda escrita de marcação que sai da página
  const writes = [];
  page.on('request', (sent) => {
    const path = new URL(sent.url()).pathname;
    if (sent.method() !== 'GET' && /^\/api\/ethos\/habits\/\d+\/(toggle|marks)/.test(path)) {
      writes.push(`${sent.method()} ${path.replace(/\d+/, ':id')}`);
    }
  });
  const toggled = () =>
    page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        /^\/api\/ethos\/habits\/\d+\/toggle$/.test(new URL(response.url()).pathname),
    );

  // O duplo clique de verdade (mousedown, mouseup e click duas vezes, e o dblclick): os cliques
  // escolhem o dia e o duplo clique marca uma vez, sem selecionar o número do dia como texto
  let cell = await todayCell(page);
  await expect(cell).toHaveAccessibleName(/\. Não marcado$/);
  let saved = toggled();
  await cell.dblclick();
  let response = await saved;
  expect(response.status()).toBe(200);
  expect((await response.json()).marked).toBe(true);
  await expect(cell).toHaveAccessibleName(/\. Escolhido\. Marcado$/);
  await expect(cell).not.toHaveAttribute('data-pending');
  await expect(page.getByRole('button', { name: 'Desmarcar este dia' })).toBeVisible();
  expect(await page.evaluate(() => window.getSelection().toString())).toBe('');
  expect(writes).toEqual(['POST /api/ethos/habits/:id/toggle']);
  await expectAccessible(page);

  // Gravado: depois de recarregar, outro duplo clique desmarca (sem detalhes, sem confirmação)
  await page.reload();
  cell = await todayCell(page);
  await expect(cell).toHaveAccessibleName(/\. Marcado$/);
  saved = toggled();
  await cell.dblclick();
  response = await saved;
  expect((await response.json()).marked).toBe(false);
  await expect(cell).toHaveAccessibleName(/\. Não marcado$/);
  await expect(page.getByRole('button', { name: 'Marcar este dia' })).toBeVisible();
  expect(writes).toHaveLength(2);
  await page.reload();
  await expect(await todayCell(page)).toHaveAccessibleName(/\. Não marcado$/);
});
