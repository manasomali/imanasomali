import {
  acceptInvite,
  createHabit,
  expect,
  expectAccessible,
  inbox,
  inviteToHabit,
  login,
  test,
  todayCell,
  toggleToday,
  uniqueEmail,
} from './support.js';

test('compartilha um hábito com outra conta, que aceita e marca', async ({ page, otherPage, request }, testInfo) => {
  const ownerEmail = uniqueEmail(testInfo, 'owner');
  const guestEmail = uniqueEmail(testInfo, 'guest');
  const habitName = 'Correr 5 km';

  // O convite só vai para quem já tem conta no imago: a convidada entra primeiro
  await login(otherPage, request, guestEmail);

  await login(page, request, ownerEmail);
  await createHabit(page, habitName);
  await inviteToHabit(page, guestEmail);
  const pending = page.getByRole('region', { name: 'Convites pendentes' });
  await expect(pending.getByText(guestEmail)).toBeVisible();
  await expectAccessible(page);

  // O email do convite chega à convidada pelo imago (o segundo, depois do código de login)
  await expect
    .poll(async () => (await inbox(request, guestEmail)).map((message) => message.subject))
    .toEqual(['Seu código de acesso ao manasomali.com', 'Você recebeu um convite no ethos']);

  await acceptInvite(otherPage, habitName);
  await otherPage.getByRole('link', { name: 'Abrir o hábito' }).click();
  await expect(otherPage.getByRole('heading', { level: 1, name: habitName })).toBeVisible();

  // A convidada pode marcar, e o dono vê a marcação dela
  await toggleToday(otherPage, { marked: true });

  await page.reload();
  const members = page.getByRole('region', { name: 'Quem tem acesso' });
  await expect(members.getByText(guestEmail)).toBeVisible();
  await expect(pending.getByText('Nenhum convite pendente.')).toBeVisible();
  await page.getByRole('navigation', { name: 'Seções do hábito' }).getByRole('link', { name: 'Calendário' }).click();
  await expect(await todayCell(page)).toHaveAccessibleName(/\. Marcado$/);
});
