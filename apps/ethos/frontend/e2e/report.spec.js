import { readFile } from 'node:fs/promises';
import { createHabit, expect, expectAccessible, goByMenu, login, test, toggleToday, uniqueEmail } from './support.js';

// Hoje no fuso do navegador do E2E (o da conta), como "AAAA-MM-DD"
function todayIn(timeZone) {
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(
    new Date(),
  );
}

test('relatório com o export CSV da marcação de hoje', async ({ page, request }, testInfo) => {
  const email = uniqueEmail(testInfo, 'report');
  const habitName = 'Meditar, 10 min';
  await login(page, request, email);
  await createHabit(page, habitName);
  const cell = await toggleToday(page, { marked: true });
  const today = await cell.getAttribute('data-day');
  expect(today).toBe(todayIn(testInfo.project.use.timezoneId));

  await goByMenu(page, 'Relatório');
  await expect(page.getByRole('heading', { level: 1, name: 'Relatório' })).toBeVisible();
  // Sem período na URL, o relatório é do ano atual até hoje, com todos os hábitos
  await page.getByRole('button', { name: 'Mostrar relatório' }).click();
  const summaries = page.getByRole('list', { name: 'Hábitos do relatório' });
  await expect(summaries.getByText(habitName)).toBeVisible();
  await expectAccessible(page);

  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Baixar CSV' }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(new RegExp(`^ethos-\\d{4}-01-01_${today}\\.csv$`));
  await expect(page.getByRole('status').filter({ hasText: 'Arquivo baixado.' })).toBeVisible();

  const csv = await readFile(await download.path(), 'utf8');
  // BOM, cabeçalho no idioma da tela, CRLF e uma linha por marcação (vírgula no nome: entre aspas)
  expect(csv.startsWith('\uFEFFHábito,Data,Horário,Autor\r\n')).toBe(true);
  const rows = csv.slice(1).split('\r\n');
  expect(rows).toHaveLength(3);
  expect(rows[1]).toMatch(new RegExp(`^"${habitName}",${today},\\d{2}:\\d{2},${email}$`));
  expect(rows[2]).toBe('');
});
