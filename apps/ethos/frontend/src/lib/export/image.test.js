import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { habitFixture, markFixture } from '../../test/habits';
import {
  fakeContext,
  fullHabit,
  fullMark,
  imageTheme,
  progressItem,
  reportData,
  translator,
} from '../../test/report';
import { HABIT_COLORS } from '../palette';
import { addDays } from '../time';
import {
  IMAGE_HEIGHT,
  IMAGE_WIDTH,
  drawReport,
  fitText,
  readImageTheme,
  renderReportImage,
  wrapSegments,
} from './image';
import { ALL_OPTIONS } from './options';
import { buildReport } from './report';

// O jsdom não tem canvas: drawReport recebe um contexto 2D falso (fakeContext), que mede o texto
// como uma fonte monoespaçada e grava cada chamada. renderReportImage é testado com getContext e
// toBlob trocados por esse contexto e por um PNG falso.

const TODAY = '2026-03-20';
let en;
let pt;

beforeAll(async () => {
  en = await translator('en');
  pt = await translator('pt');
});

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute('style');
});

function draw(report, { t = en, language = 'en' } = {}) {
  const fake = fakeContext();
  drawReport(fake.ctx, report, { t, language, theme: imageTheme(), today: TODAY });
  return fake;
}

function fullReport(options = ALL_OPTIONS, extra = {}) {
  const marks = [fullMark({ id: 1 }), fullMark({ id: 2, marked_at: '2026-03-05T15:00:00Z' })];
  const costPeriods = [{ first_day: '2026-03-01', last_day: '2026-03-31', spend_cents: 2500, limit_percent: 125 }];
  const periods = [{ first_day: '2026-03-02', last_day: '2026-03-08', value: 60, met: false }];
  return buildReport(
    reportData({ habits: [progressItem(fullHabit(extra), { marks, periods, cost_periods: costPeriods })] }),
    options,
    { today: TODAY },
  );
}

/** Todo texto cabe na imagem, entre as margens. */
function expectInside({ texts, rects }) {
  for (const text of texts) {
    expect(text.x, text.text).toBeGreaterThanOrEqual(0);
    expect(text.x + text.width, text.text).toBeLessThanOrEqual(IMAGE_WIDTH - 72 + 0.001);
    expect(text.y, text.text).toBeGreaterThan(0);
    expect(text.y, text.text).toBeLessThanOrEqual(IMAGE_HEIGHT - 40);
  }
  for (const rect of rects) {
    expect(rect.x + rect.width).toBeLessThanOrEqual(IMAGE_WIDTH);
    expect(rect.y + rect.height).toBeLessThanOrEqual(IMAGE_HEIGHT);
  }
}

const allText = ({ texts }) => texts.map((text) => text.text).join('\n');

/** Quadrados do mapa de calor de um relatório sem marcações: um por dia, logo depois do fundo. */
function heatmapCells(from, to) {
  const habits = [progressItem(fullHabit(), { marks: [] })];
  const report = buildReport(reportData({ from, to, habits }), ALL_OPTIONS, { today: TODAY });
  return draw(report).rects.slice(1, 1 + 7 * 2);
}

describe('report image heat map', () => {
  it('draws each week from Sunday (top) to Saturday (bottom), like the calendar', () => {
    // 1º de março de 2026 foi um domingo: a semana inteira numa coluna, de cima para baixo
    const week = heatmapCells('2026-03-01', '2026-03-07').slice(0, 7);
    expect(new Set(week.map((cell) => cell.x)).size).toBe(1);
    for (let row = 1; row < 7; row += 1) expect(week[row].y).toBeGreaterThan(week[row - 1].y);

    // De segunda a domingo: a segunda na 2ª linha e o domingo abrindo a coluna seguinte
    const goalWeek = heatmapCells('2026-03-02', '2026-03-08').slice(0, 7);
    expect(goalWeek[0].y).toBe(week[1].y);
    expect(goalWeek[6].y).toBe(week[0].y);
    expect(goalWeek[6].x).toBeGreaterThan(goalWeek[0].x);
  });
});

describe('report image', () => {
  it('draws the header, the heat map and every chosen piece of information', () => {
    const fake = draw(fullReport());
    const text = allText(fake);

    expect(fake.rects[0]).toMatchObject({ x: 0, y: 0, width: IMAGE_WIDTH, height: IMAGE_HEIGHT, color: '#ffffff' });
    expect(text).toContain('Habit report');
    expect(text).toContain('Mar 1, 2026 – Mar 31, 2026');
    expect(text).toContain('RUN · Running');
    expect(text).toContain('2 days with marks');
    expect(text).toContain('score 80/100');
    expect(text).toContain('Success');
    expect(text).toContain('spent 25.00');
    expect(text).toContain('this month: 25.00 of 20.00');
    expect(text).toContain('60 min');
    expect(text).toContain('Reward: Pizza');
    expect(text).toContain('Punishment: Run 5 km');
    expect(text).toContain('goal met in 0 of 1 periods');
    expect(text).toContain('Mar 20, 2026');
    // Nada de emails nem observações
    expect(text).not.toContain('@');
    expect(text).not.toContain('Good run');
    // Um quadrado por dia de março (e mais um com a cor nos 2 dias marcados), mais a legenda
    const cells = fake.rects.filter((rect) => rect.width === rect.height && rect.width < 40);
    expect(cells.length).toBe(31 + 2 + 5 + 4);
    expectInside(fake);
  });

  it('paints a custom color (ETH-49) as it is', () => {
    const custom = '#0a1b2c';
    const fake = draw(fullReport(ALL_OPTIONS, { color: custom }));
    const fills = new Set(fake.rects.map((rect) => rect.color));

    // Um hábito só: o mapa de calor usa a cor dele, não a de algum nome da paleta
    expect(fills).toContain(custom);
    expect(fills).not.toContain(imageTheme().habits.teal);
  });

  it('removes what was turned off', () => {
    const text = allText(draw(fullReport({ ...ALL_OPTIONS, cost: false, score: false, reward: false })));

    expect(text).not.toContain('spent');
    expect(text).not.toContain('this month');
    expect(text).not.toContain('score');
    expect(text).not.toContain('Success');
    expect(text).not.toContain('Reward');
    expect(text).toContain('Punishment: Run 5 km');
    expect(text).toContain('60 min');
  });

  it('shows "no data" for a score without value and the status of the habit', () => {
    const report = buildReport(
      reportData({
        habits: [
          progressItem(
            habitFixture({ score_enabled: true, score: { value: null, success: null }, status: 'archived', code: null }),
            { marks: [] },
          ),
        ],
      }),
      ALL_OPTIONS,
      { today: TODAY },
    );
    const text = allText(draw(report));

    expect(text).toContain('Running (archived)');
    expect(text).toContain('score: no data yet');
    expect(text).toContain('no closed period yet');
    expect(text).not.toContain('Success');
    expect(text).not.toContain('Failure');
  });

  it('is written in Portuguese too, inside the image', () => {
    const fake = draw(fullReport(), { t: pt, language: 'pt' });
    const text = allText(fake);

    expect(text).toContain('Relatório de hábitos');
    expect(text).toContain('1 de mar. de 2026 – 31 de mar. de 2026');
    expect(text).toContain('gasto 25,00');
    expect(text).toContain('Sucesso');
    expectInside(fake);
  });

  it('cuts long names and texts instead of overflowing', () => {
    const long = 'A very long habit name that goes on and on '.repeat(5);
    const fake = draw(fullReport(ALL_OPTIONS, { name: long, reward: long, punishment: long, code: null }));

    expect(fake.texts.some((text) => text.text.endsWith('…'))).toBe(true);
    expectInside(fake);
  });

  it('says when there are no habits', () => {
    const report = buildReport(reportData(), ALL_OPTIONS, { today: TODAY });
    expect(allText(draw(report))).toContain('No habits in this report.');
  });

  it('does not break with 10 habits and a whole year of marks', () => {
    const habits = Array.from({ length: 10 }, (_, index) => {
      const id = index + 1;
      const marks = [];
      for (let day = '2025-01-01', n = 0; day <= '2025-12-31'; day = addDays(day, 1), n += 1) {
        // Hábitos com várias marcações por dia em dias alternados
        for (let k = 0; k < (n % 2 === 0 ? 3 : 1); k += 1) {
          marks.push(markFixture({ id: id * 10_000 + n * 3 + k, habit_id: id, marked_at: `${day}T15:0${k}:00Z` }));
        }
      }
      return progressItem(fullHabit({ id, name: `Habit number ${id}`, color: HABIT_COLORS[index] }), { marks });
    });
    const data = reportData({ from: '2025-01-01', to: '2025-12-31', habits });

    const started = performance.now();
    const report = buildReport(data, ALL_OPTIONS, { today: '2026-01-10' });
    const fake = draw(report);
    const elapsed = performance.now() - started;

    // 183 dias pares com 3 marcações e 182 ímpares com 1
    expect(report.habits.every((item) => item.marks.length === 731)).toBe(true);
    // Todos os 10 hábitos cabem, sem "+N"
    for (let id = 1; id <= 10; id += 1) expect(allText(fake)).toContain(`Habit number ${id}`);
    expect(allText(fake)).not.toMatch(/\+\d+ more/);
    // 365 dias (cada um com fundo e cor), sem uma chamada por marcação
    expect(fake.calls.fillRect).toBeLessThan(365 * 2 + 20);
    expectInside(fake);
    // Folga grande para o CI; na prática leva poucas centenas de ms
    expect(elapsed).toBeLessThan(5_000);
  });

  it('summarizes the habits that do not fit and draws 5 years', () => {
    const habits = Array.from({ length: 40 }, (_, index) =>
      progressItem(fullHabit({ id: index + 1, name: `Habit ${index + 1}` }), { marks: [] }),
    );
    const report = buildReport(reportData({ from: '2021-01-01', to: '2025-12-31', habits }), ALL_OPTIONS, {
      today: TODAY,
    });
    const fake = draw(report);

    expect(allText(fake)).toMatch(/\+\d+ more habits/);
    expect(allText(fake)).toContain('Habit 1');
    expect(allText(fake)).not.toContain('Habit 40');
    expectInside(fake);
  });
});

describe('text fitting', () => {
  it('cuts with an ellipsis only when needed', () => {
    const { ctx } = fakeContext();
    ctx.font = '10px mono';

    expect(fitText(ctx, 'short', 100)).toBe('short');
    // 6 px por caractere: cabem 9 caracteres e o "…"
    expect(fitText(ctx, 'abcdefghijklmnop', 60)).toBe('abcdefghi…');
    expect(fitText(ctx, 'abcdef', 5)).toBe('…');
  });

  it('keeps emoji whole', () => {
    const { ctx } = fakeContext();
    ctx.font = '10px mono';

    // Cada família tem 7 pontos de código (42 px no contexto falso): cabe uma e o "…"
    const family = '👩‍👩‍👧‍👦';
    expect(fitText(ctx, family.repeat(4), 50)).toBe(`${family}…`);
  });

  it('wraps segments in lines and cuts the last one', () => {
    const { ctx } = fakeContext();
    ctx.font = '10px mono';

    // 6 px por caractere: "aaaa · bbbb · cccc" tem 18 (108 px)
    expect(wrapSegments(ctx, ['aaaa', 'bbbb', 'cccc'], 108, 2)).toEqual(['aaaa · bbbb · cccc']);
    expect(wrapSegments(ctx, ['aaaa', 'bbbb', 'cccc'], 66, 3)).toEqual(['aaaa · bbbb', 'cccc']);
    expect(wrapSegments(ctx, ['aaaa', 'bbbb', 'cccc', 'dddd'], 42, 2)).toEqual(['aaaa', 'bbbb ·…']);
    expect(wrapSegments(ctx, [], 100, 2)).toEqual([]);
  });
});

describe('renderReportImage', () => {
  function mockCanvas({ ctx = fakeContext().ctx, blob = new Blob(['png'], { type: 'image/png' }) } = {}) {
    const canvases = [];
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function getContext(kind) {
      canvases.push({ canvas: this, kind });
      return ctx;
    });
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback, type) => {
      canvases.at(-1).type = type;
      callback(blob);
    });
    return canvases;
  }

  it('creates a 1080×1350 PNG named after the period', async () => {
    const canvases = mockCanvas();

    const file = await renderReportImage(fullReport(), { t: en, language: 'en', today: TODAY, theme: imageTheme() });

    expect(canvases).toHaveLength(1);
    expect(canvases[0].canvas.width).toBe(1080);
    expect(canvases[0].canvas.height).toBe(1350);
    expect([IMAGE_WIDTH, IMAGE_HEIGHT]).toEqual([1080, 1350]);
    expect(canvases[0].kind).toBe('2d');
    expect(canvases[0].type).toBe('image/png');
    expect(file).toBeInstanceOf(File);
    expect(file.name).toBe('ethos-2026-03-01_2026-03-31.png');
    expect(file.type).toBe('image/png');
  });

  it('reads the colors from the tokens and loads the font first', async () => {
    const fake = fakeContext();
    mockCanvas({ ctx: fake.ctx });
    const style = document.documentElement.style;
    const theme = imageTheme();
    for (const [key, value] of Object.entries(theme.colors)) style.setProperty(`--${key}`, value);
    for (const [name, value] of Object.entries(theme.habits)) style.setProperty(`--habit-${name}`, value);
    style.setProperty('--font', theme.font);
    const load = vi.fn(async () => []);
    document.fonts = { load };

    try {
      await renderReportImage(fullReport(), { t: en, language: 'en', today: TODAY });
    } finally {
      delete document.fonts;
    }

    expect(load).toHaveBeenCalledWith(`700 32px ${theme.font}`);
    expect(fake.rects[0].color).toBe('#ffffff');
    expect(fake.texts.find((text) => text.text === 'Habit report').color).toBe('#000000');
  });

  it('draws with the fallback font when it cannot load', async () => {
    mockCanvas();
    document.fonts = { load: vi.fn(async () => Promise.reject(new Error('offline'))) };
    try {
      await expect(
        renderReportImage(fullReport(), { t: en, language: 'en', today: TODAY, theme: imageTheme() }),
      ).resolves.toBeInstanceOf(File);
    } finally {
      delete document.fonts;
    }
  });

  it('fails clearly without canvas or PNG', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    await expect(
      renderReportImage(fullReport(), { t: en, language: 'en', today: TODAY, theme: imageTheme() }),
    ).rejects.toThrow('canvas');

    vi.restoreAllMocks();
    mockCanvas({ blob: null });
    await expect(
      renderReportImage(fullReport(), { t: en, language: 'en', today: TODAY, theme: imageTheme() }),
    ).rejects.toThrow('PNG');
  });

  it('refuses to draw without the tokens', () => {
    expect(() => readImageTheme(document.documentElement)).toThrow('--fg');
  });
});
