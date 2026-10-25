import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { configure, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { axe } from '../../test/axe';
import { habitFixture, mockHabitsApi } from '../../test/habits';
import {
  fakeContext,
  fullHabit,
  fullMark,
  imageTheme,
  mockProgressApi,
  progressItem,
  readFileText,
} from '../../test/report';
import { meFixture, renderApp } from '../../test/render';
import { api, server } from '../../test/server';

vi.setConfig({ testTimeout: 15_000 });
configure({ asyncUtilTimeout: 5_000 });

// Sexta, 20 de março de 2026, 12:00 em São Paulo
const NOW = new Date('2026-03-20T15:00:00Z');

const running = fullHabit();
const reading = habitFixture({ id: 2, name: 'Reading', code: null, color: 'blue' });
const old = habitFixture({ id: 3, name: 'Old habit', code: null, status: 'archived', archived_at: '2026-02-01T12:00:00Z' });

function progressItems() {
  const item = (habit, range, extra) => {
    const value = progressItem(habit, { marks_range: range, ...extra });
    delete value.marks;
    return value;
  };
  return [
    item(running, { first_day: '2026-03-02', last_day: '2026-03-05' }, {
      periods: [
        { first_day: '2026-03-02', last_day: '2026-03-08', value: 60, met: false, spend_cents: 2500 },
        { first_day: '2026-03-09', last_day: '2026-03-15', value: 90, met: true, spend_cents: 0 },
      ],
      cost_periods: [{ first_day: '2026-03-01', last_day: '2026-03-31', spend_cents: 2500, limit_percent: 125 }],
    }),
    item(reading, null),
    item(old, null),
  ];
}

/** Sessão, hábitos, marcações e progresso. Devolve as queries do progresso e as requests. */
function setup() {
  server.use(http.get(api('/auth/me'), () => HttpResponse.json(meFixture())));
  const { requests } = mockHabitsApi({
    habits: [running, reading],
    archived: [old],
    marks: {
      1: [
        fullMark({ id: 1, marked_at: '2026-03-02T15:00:00Z', note: '=SOMA()' }),
        fullMark({ id: 2, marked_at: '2026-03-05T15:00:00Z' }),
      ],
    },
  });
  // Depois do mockHabitsApi: /habits/progress não pode cair no /habits/:id
  const progress = mockProgressApi({ items: progressItems() });
  return { progress, requests };
}

/** URLs de blob e cliques de download (o jsdom não implementa nenhum dos dois). */
function captureDownloads() {
  const blobs = new Map();
  URL.createObjectURL = vi.fn((blob) => {
    const url = `blob:test/${blobs.size + 1}`;
    blobs.set(url, blob);
    return url;
  });
  URL.revokeObjectURL = vi.fn();
  const downloads = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click() {
    downloads.push({ name: this.download, blob: blobs.get(this.getAttribute('href')) });
  });
  return downloads;
}

/** Canvas falso e os tokens no <html> (o jsdom não carrega o CSS). */
function mockCanvas() {
  const fake = fakeContext();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(fake.ctx);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback) => {
    callback(new Blob(['png'], { type: 'image/png' }));
  });
  const theme = imageTheme();
  const style = document.documentElement.style;
  for (const [key, value] of Object.entries(theme.colors)) style.setProperty(`--${key}`, value);
  for (const [name, value] of Object.entries(theme.habits)) style.setProperty(`--habit-${name}`, value);
  style.setProperty('--font', theme.font);
  return fake;
}

async function findSummary(name) {
  const list = await screen.findByRole('list', { name: 'Habits in the report' });
  return within(list).getByRole('heading', { name: new RegExp(name) }).closest('li');
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete URL.createObjectURL;
  delete URL.revokeObjectURL;
  delete navigator.canShare;
  delete navigator.share;
  document.documentElement.removeAttribute('style');
});

describe('report screen', () => {
  it('shows this year of every habit, with what each one has turned on', async () => {
    const { progress } = setup();
    const { container } = renderApp('/relatorio');

    const card = await findSummary('Running');

    expect(progress).toEqual([{ from: '2026-01-01', to: '2026-03-20', habit_ids: [] }]);
    expect(screen.getByRole('heading', { level: 1, name: 'Report' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Report from Jan 1, 2026 to Mar 20, 2026' })).toBeTruthy();
    const details = within(card);
    expect(details.getByText('Marks').nextSibling.textContent).toBe('2');
    expect(details.getByText('Closed periods with the goal met').nextSibling.textContent).toBe('1 of 2');
    expect(details.getByText('Score').nextSibling.textContent).toBe('80/100 (threshold 70)');
    expect(details.getByText('Result').nextSibling.textContent).toBe('Success');
    expect(details.getByText('Time').nextSibling.textContent).toBe('60 min');
    expect(details.getByText('Spent in the period').nextSibling.textContent).toBe('25.00');
    expect(details.getByText('Limit').nextSibling.textContent).toBe('20.00 per monthLatest period: 25.00 (125%)');
    expect(details.getByText('Reward').nextSibling.textContent).toBe('Pizza');
    // Sem pontuação nem custo: nada disso aparece
    const plain = within(await findSummary('Reading'));
    expect(plain.queryByText('Score')).toBeNull();
    expect(plain.queryByText('Spent in the period')).toBeNull();
    expect(within(await findSummary('Old habit')).getByText('archived')).toBeTruthy();
    // Todos os hábitos marcados, inclusive o arquivado
    expect(screen.getByRole('checkbox', { name: 'All habits, archived ones included' }).checked).toBe(true);
    expect(screen.getByRole('checkbox', { name: 'Old habit (archived)' }).checked).toBe(true);
    expect(screen.getByRole('link', { name: 'Report' }).getAttribute('aria-current')).toBe('page');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('starts with the habit of the URL and changes the period on submit', async () => {
    const { progress } = setup();
    const user = userEvent.setup();
    const { router } = renderApp('/relatorio?habit_id=1');

    await findSummary('Running');
    expect(progress).toEqual([{ from: '2026-01-01', to: '2026-03-20', habit_ids: [1] }]);
    expect(screen.getByRole('checkbox', { name: 'All habits, archived ones included' }).checked).toBe(false);
    expect(screen.getByRole('checkbox', { name: 'Reading' }).checked).toBe(false);

    await user.click(screen.getByRole('button', { name: 'Last 12 months' }));
    await user.click(screen.getByRole('checkbox', { name: 'Reading' }));
    await user.click(screen.getByRole('button', { name: 'Show report' }));

    await waitFor(() => expect(progress).toHaveLength(2));
    expect(progress[1]).toEqual({ from: '2025-03-21', to: '2026-03-20', habit_ids: [1, 2] });
    expect(router.state.location.search).toBe('?from=2025-03-21&to=2026-03-20&habit_id=1&habit_id=2');
  });

  it('does not go past 5 years nor run without a habit', async () => {
    const { progress } = setup();
    const user = userEvent.setup();
    renderApp('/relatorio');
    await findSummary('Running');

    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2020-01-01' } });
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2025-01-01' } });
    expect(screen.getByText('The period can cover at most 5 years.')).toBeTruthy();
    expect(screen.getByLabelText('From').getAttribute('aria-invalid')).toBe('true');
    await user.click(screen.getByRole('button', { name: 'Last 5 years' }));
    expect(screen.queryByText('The period can cover at most 5 years.')).toBeNull();
    expect(screen.getByLabelText('From').value).toBe('2021-03-21');

    await user.click(screen.getByRole('checkbox', { name: 'All habits, archived ones included' }));
    await user.click(screen.getByRole('button', { name: 'Show report' }));

    expect(screen.getByRole('alert').textContent).toBe('Choose at least one habit.');
    expect(progress).toHaveLength(1);
  });

  it('downloads the CSV without the columns turned off', async () => {
    setup();
    const downloads = captureDownloads();
    const user = userEvent.setup();
    renderApp('/relatorio');
    const card = await findSummary('Running');

    await user.click(screen.getByRole('button', { name: 'Download CSV' }));
    await user.click(screen.getByRole('checkbox', { name: 'Spending and limit' }));
    await user.click(screen.getByRole('checkbox', { name: 'Notes (CSV and JSON)' }));
    await user.click(screen.getByRole('button', { name: 'Download CSV' }));

    expect(within(card).queryByText('Spent in the period')).toBeNull();
    expect(downloads.map((download) => download.name)).toEqual([
      'ethos-2026-01-01_2026-03-20.csv',
      'ethos-2026-01-01_2026-03-20.csv',
    ]);
    const [before, after] = await Promise.all(downloads.map((download) => readFileText(download.blob)));
    expect(before.split('\r\n').slice(0, 2)).toEqual([
      '﻿Habit,Date,Time,Author,Duration (min),Cost',
      'Running,2026-03-02,12:00,ana@example.com,30,12.50',
    ]);
    expect(after.split('\r\n').slice(0, 3)).toEqual([
      '﻿Habit,Date,Time,Author,Duration (min),Note',
      "Running,2026-03-02,12:00,ana@example.com,30,'=SOMA()",
      'Running,2026-03-05,12:00,ana@example.com,30,Good run',
    ]);
    expect(screen.getByText('File downloaded.')).toBeTruthy();
  });

  it('downloads the JSON of the report', async () => {
    setup();
    const downloads = captureDownloads();
    const user = userEvent.setup();
    renderApp('/relatorio?habit_id=1');
    await findSummary('Running');

    await user.click(screen.getByRole('button', { name: 'Download JSON' }));

    const value = JSON.parse(await readFileText(downloads[0].blob));
    expect(downloads[0].name).toBe('ethos-2026-01-01_2026-03-20.json');
    expect(value.period).toEqual({ from: '2026-01-01', to: '2026-03-20' });
    expect(value.habits.map((habit) => habit.id)).toEqual([1]);
    expect(value.habits[0].marks[0]).not.toHaveProperty('note');
  });

  it('creates the image and downloads it where sharing files is not supported', async () => {
    setup();
    const downloads = captureDownloads();
    const fake = mockCanvas();
    const user = userEvent.setup();
    const { container } = renderApp('/relatorio');
    await findSummary('Running');

    await user.click(screen.getByRole('button', { name: 'Create image' }));

    const preview = await screen.findByRole('img', { name: 'Preview of the report image' });
    expect(preview.getAttribute('src')).toBe('blob:test/1');
    expect(fake.texts.some((text) => text.text === 'Habit report')).toBe(true);
    expect(screen.queryByRole('button', { name: 'Share image' })).toBeNull();
    expect(await axe(container)).toHaveNoViolations();

    await user.click(screen.getByRole('button', { name: 'Download image' }));

    expect(downloads).toEqual([{ name: 'ethos-2026-01-01_2026-03-20.png', blob: expect.any(File) }]);
    expect(screen.getByText('File downloaded.')).toBeTruthy();

    // Mudar uma informação descarta a imagem pronta
    await user.click(screen.getByRole('checkbox', { name: 'Reward' }));
    expect(screen.queryByRole('img', { name: 'Preview of the report image' })).toBeNull();
  });

  it('shares the image where the browser shares files', async () => {
    setup();
    captureDownloads();
    mockCanvas();
    navigator.canShare = vi.fn(() => true);
    navigator.share = vi.fn(async () => {});
    const user = userEvent.setup();
    renderApp('/relatorio');
    await findSummary('Running');

    await user.click(screen.getByRole('button', { name: 'Create image' }));
    await user.click(await screen.findByRole('button', { name: 'Share image' }));

    expect(navigator.share).toHaveBeenCalledWith({
      files: [expect.any(File)],
      title: 'My habits on ethos',
    });
    expect(navigator.share.mock.calls[0][0].files[0].type).toBe('image/png');
    expect(await screen.findByText('Image shared.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download image' })).toBeTruthy();
  });

  it('says when the image cannot be created', async () => {
    setup();
    captureDownloads();
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const user = userEvent.setup();
    renderApp('/relatorio');
    await findSummary('Running');

    await user.click(screen.getByRole('button', { name: 'Create image' }));

    expect(await screen.findByText('Could not create the image in this browser.')).toBeTruthy();
  });

  it('exports everything, archived habits and all time included', async () => {
    const { progress } = setup();
    const downloads = captureDownloads();
    const user = userEvent.setup();
    renderApp('/relatorio?habit_id=2');
    await findSummary('Reading');

    await user.click(screen.getByRole('button', { name: 'Export everything (JSON)' }));

    expect(await screen.findByText('Export downloaded.')).toBeTruthy();
    // Hoje (descobre os hábitos), depois da criação mais antiga (5/1/2026) até hoje
    expect(progress.slice(1)).toEqual([
      { from: '2026-03-20', to: '2026-03-20', habit_ids: [] },
      { from: '2026-01-05', to: '2026-03-20', habit_ids: [] },
    ]);
    const value = JSON.parse(await readFileText(downloads[0].blob));
    expect(value.habits.map((habit) => habit.id)).toEqual([1, 2, 3]);
    expect(value.habits[0].marks[0].note).toBe('=SOMA()');
  });

  it('shows the error of the API and retries', async () => {
    setup();
    let fail = true;
    server.use(
      http.get(api('/habits/progress'), () =>
        // 403 não repete sozinho (o 5xx repetiria, com espera)
        fail ? HttpResponse.json({ error: 'forbidden', field: null }, { status: 403 }) : undefined,
      ),
    );
    const user = userEvent.setup();
    renderApp('/relatorio');

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('You do not have permission');
    fail = false;
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));

    expect(await findSummary('Running')).toBeTruthy();
  });

  it('is linked from the habit tab, with the habit chosen', async () => {
    setup();
    const user = userEvent.setup();
    const { router } = renderApp('/habits/1');

    const sections = await screen.findByRole('navigation', { name: 'Habit sections' });
    await user.click(within(sections).getByRole('link', { name: 'Report' }));

    expect(router.state.location.pathname).toBe('/ethos/relatorio');
    expect(router.state.location.search).toBe('?habit_id=1');
  });
});
