import { createHabit, expect, expectAccessible, goByMenu, inbox, login, test, todayCell, toggleToday, uniqueEmail } from './support.js';

test('compartilha um hábito com outra conta, que aceita e marca', async ({ page, otherPage, request }, testInfo) => {
  const ownerEmail = uniqueEmail(testInfo, 'owner');
  const guestEmail = uniqueEmail(testInfo, 'guest');
  const habitName = 'Correr 5 km';

  // O convite só chega a quem já tem conta: a convidada entra primeiro
  await login(otherPage, request, guestEmail);

  await login(page, request, ownerEmail);
  await createHabit(page, habitName);
  await page.getByRole('navigation', { name: 'Seções do hábito' }).getByRole('link', { name: 'Compartilhamento' }).click();
  await expect(page.getByRole('heading', { level: 2, name: 'Compartilhamento' })).toBeVisible();
  const form = page.getByRole('form', { name: 'Convidar alguém' });
  await form.getByLabel('Email').fill(guestEmail);
  await form.getByRole('radio', { name: /^Pode marcar/ }).check();
  await form.getByRole('button', { name: 'Enviar convite' }).click();
  await expect(page.getByText('Convite enviado.')).toBeVisible();
  const pending = page.getByRole('region', { name: 'Convites pendentes' });
  await expect(pending.getByText(guestEmail)).toBeVisible();
  await expectAccessible(page);

  // O email do convite chega à convidada (o segundo, depois do código de login)
  await expect
    .poll(async () => (await inbox(request, guestEmail)).map((message) => message.subject))
    .toEqual(['Seu código de acesso ao ethos', 'Você recebeu um convite no ethos']);

  await goByMenu(otherPage, /^Convites/);
  await expect(otherPage.getByRole('heading', { level: 1, name: 'Convites' })).toBeVisible();
  const invite = otherPage.getByRole('group', { name: `Responder ao convite para ${habitName}` });
  await expectAccessible(otherPage);
  await invite.getByRole('button', { name: 'Aceitar' }).click();
  await expect(otherPage.getByText(`Você entrou em “${habitName}”.`)).toBeVisible();
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
