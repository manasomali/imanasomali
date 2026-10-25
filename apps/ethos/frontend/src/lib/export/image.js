// Imagem do relatório para redes sociais: PNG 1080×1350 (retrato), desenhado num <canvas> sem
// biblioteca. De cima para baixo: marca, título e período; mapa de calor do período (semanas em
// colunas, domingo a sábado nas linhas, como o calendário); um bloco por hábito com a
// sigla/nome, marcações, períodos da meta cumpridos e, quando escolhidos e ligados no hábito,
// pontuação e sucesso/falha, minutos, gasto e limite, recompensa e punição; rodapé com a data.
// Nunca traz emails nem observações.
//
// Cores e fonte vêm dos tokens e da paleta lidos em runtime (readImageTheme), nunca de valores
// fixos: a imagem sai no tema da tela, com o mesmo contraste garantido pelos tokens e pela paleta
// (src/styles/palette.test.js), nos dois temas. Todo texto passa por `fitText`, que corta com "…"
// o que não cabe na largura, então nenhum idioma estoura a imagem. Muitos hábitos: o tamanho da
// letra diminui até um mínimo legível, depois somem as linhas de recompensa/punição e, por fim, o
// resto vira "+N hábitos".
//
// Testes: o jsdom não tem canvas de verdade. drawReport recebe o contexto 2D, então os testes
// passam um contexto falso que grava as chamadas (src/lib/export/image.test.js) e conferem o
// tamanho, os textos e os limites; renderReportImage cria o <canvas>, carrega a fonte e gera o PNG.

import { weekColumn } from '../calendar';
import { formatShortDay } from '../format';
import { formatMoney } from '../money';
import { HABIT_COLORS } from '../palette';
import { addDays } from '../time';
import { reportFilename } from './files';
import { daysBetween } from './period';
import { habitsPerDay } from './report';

export const IMAGE_WIDTH = 1080;
export const IMAGE_HEIGHT = 1350;
export const IMAGE_MIME = 'image/png';

const PAD = 72;
const CONTENT_WIDTH = IMAGE_WIDTH - 2 * PAD;
// Tamanhos máximos da célula do mapa de calor, do maior para o menor. Fica o maior com que os
// hábitos saem tão bem quanto com o menor (mesma letra, mesmas linhas): poucos hábitos, mapa
// grande; muitos, mapa baixo e mais altura para eles (10 hábitos, o limite de ativos e pausados,
// cabem inteiros). Períodos longos têm células menores que isso, para caber na largura
const CELL_SIZES = [40, 32, 24, 18, 12];
// Topo do mapa de calor e distâncias até a legenda e os hábitos
const HEATMAP_TOP = PAD + 190;
const LEGEND_OFFSET = 40;
const HABITS_OFFSET = 48;
// Linha de base do rodapé e o fim da área dos hábitos
const FOOTER_BASELINE = IMAGE_HEIGHT - PAD + 20;
const HABITS_BOTTOM = FOOTER_BASELINE - 48;
// Opacidade da cor nos 4 níveis do mapa de calor (fração dos hábitos marcados no dia)
const LEVELS = [0.3, 0.55, 0.8, 1];
// Escalas de letra testadas para os hábitos caberem; a última é o mínimo legível
const SCALES = [1, 0.9, 0.8, 0.7];
// Tentativas, em ordem: linhas de recompensa/punição e até 3 linhas de números (nada cortado), depois
// 2 linhas; sem recompensa/punição; números numa linha só
const STAGES = [
  { extras: true, statLines: 3 },
  { extras: true, statLines: 2 },
  { extras: false, statLines: 2 },
  { extras: false, statLines: 1 },
];
const SEPARATOR = ' · ';
const ELLIPSIS = '…';

const COLOR_TOKENS = Object.freeze({
  fg: '--fg',
  bg: '--bg',
  muted: '--muted',
  surface: '--surface',
});

/**
 * Cores e fonte da imagem, lidas dos tokens (packages/tokens) e da paleta (src/styles/palette.css)
 * no tema atual da página. Lança Error se faltar um token (CSS não carregado).
 */
export function readImageTheme(element = globalThis.document.documentElement) {
  const style = globalThis.getComputedStyle(element);
  const read = (name) => {
    const value = style.getPropertyValue(name).trim();
    if (!value) throw new Error(`token ausente: ${name}`);
    return value;
  };
  return {
    colors: Object.fromEntries(
      Object.entries(COLOR_TOKENS).map(([key, name]) => [key, read(name)]),
    ),
    habits: Object.fromEntries(HABIT_COLORS.map((name) => [name, read(`--habit-${name}`)])),
    font: read('--font'),
  };
}

function graphemes(text) {
  if (typeof Intl.Segmenter === 'function') {
    return Array.from(new Intl.Segmenter().segment(text), (part) => part.segment);
  }
  return Array.from(text);
}

/** O texto, cortado com "…" se passar de `maxWidth` na fonte atual do contexto. */
export function fitText(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  const parts = graphemes(text);
  let low = 0;
  let high = parts.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    const candidate = `${parts.slice(0, middle).join('').trimEnd()}${ELLIPSIS}`;
    if (ctx.measureText(candidate).width <= maxWidth) low = middle;
    else high = middle - 1;
  }
  return `${parts.slice(0, low).join('').trimEnd()}${ELLIPSIS}`;
}

/**
 * Junta os trechos com " · " em até `maxLines` linhas de até `maxWidth`; o que sobra entra na
 * última linha, cortada com "…".
 */
export function wrapSegments(ctx, segments, maxWidth, maxLines) {
  const lines = [];
  let current = '';
  for (const segment of segments) {
    const candidate = current ? `${current}${SEPARATOR}${segment}` : segment;
    if (!current || ctx.measureText(candidate).width <= maxWidth) {
      current = candidate;
    } else {
      lines.push(current);
      current = segment;
    }
  }
  if (current) lines.push(current);
  if (lines.length > maxLines) {
    lines.splice(maxLines - 1, lines.length, lines.slice(maxLines - 1).join(SEPARATOR));
  }
  return lines.map((line) => fitText(ctx, line, maxWidth));
}

function setFont(ctx, theme, size, weight) {
  ctx.font = `${weight} ${Math.round(size)}px ${theme.font}`;
}

function drawText(ctx, theme, value, x, y, { size, weight = 500, color, maxWidth }) {
  setFont(ctx, theme, size, weight);
  ctx.fillStyle = color;
  const width = maxWidth ?? IMAGE_WIDTH - PAD - x;
  ctx.fillText(fitText(ctx, value, width), x, y, width);
}

function habitColor(theme, habit) {
  return theme.habits[habit.color] ?? theme.colors.muted;
}

// --- mapa de calor ---

// Semanas em colunas a partir do domingo antes de `from` (WEEK_START, como o calendário; só o
// desenho: os períodos da meta seguem de segunda a domingo); `pitch`: distância entre as células
function heatmapGeometry(report, maxCell) {
  const start = addDays(report.from, -weekColumn(report.from));
  const weeks = Math.ceil((daysBetween(start, report.to) + 1) / 7);
  const pitch = Math.min(maxCell, CONTENT_WIDTH / weeks);
  const gap = pitch >= 6 ? Math.max(1, Math.round(pitch * 0.15)) : 0;
  return { start, pitch, size: pitch - gap };
}

function drawHeatmap(ctx, report, theme, t, top, { start, pitch, size }) {
  const { colors } = theme;
  const counts = habitsPerDay(report);
  const total = report.habits.length;
  // Um hábito: a cor dele; vários: a cor do texto
  const tint = total === 1 ? habitColor(theme, report.habits[0].habit) : colors.fg;

  let index = daysBetween(start, report.from);
  for (let day = report.from; day <= report.to; day = addDays(day, 1)) {
    const x = PAD + Math.floor(index / 7) * pitch;
    const y = top + (index % 7) * pitch;
    ctx.globalAlpha = 1;
    ctx.fillStyle = colors.surface;
    ctx.fillRect(x, y, size, size);
    const marked = counts.get(day) ?? 0;
    if (marked > 0) {
      ctx.globalAlpha = LEVELS[Math.min(LEVELS.length, Math.ceil((marked / total) * LEVELS.length)) - 1];
      ctx.fillStyle = tint;
      ctx.fillRect(x, y, size, size);
    }
    index += 1;
  }
  ctx.globalAlpha = 1;

  // Legenda: dias com marcação à esquerda; "menos ▢▢▢▢▢ mais" à direita
  const baseline = top + 7 * pitch + LEGEND_OFFSET;
  const legendSize = 22;
  setFont(ctx, theme, legendSize, 500);
  const less = t('report.image.less');
  const more = t('report.image.more');
  const square = 20;
  const legendWidth =
    ctx.measureText(less).width + ctx.measureText(more).width + 5 * (square + 6) + 16;
  let x = IMAGE_WIDTH - PAD - legendWidth;
  drawText(ctx, theme, t('report.image.days_marked', { count: counts.size }), PAD, baseline, {
    size: legendSize,
    color: colors.muted,
    maxWidth: Math.max(0, x - PAD - 24),
  });
  drawText(ctx, theme, less, x, baseline, { size: legendSize, color: colors.muted });
  x += ctx.measureText(less).width + 8;
  for (let level = 0; level <= LEVELS.length; level += 1) {
    ctx.globalAlpha = 1;
    ctx.fillStyle = colors.surface;
    ctx.fillRect(x, baseline - square + 2, square, square);
    if (level > 0) {
      ctx.globalAlpha = LEVELS[level - 1];
      ctx.fillStyle = tint;
      ctx.fillRect(x, baseline - square + 2, square, square);
    }
    x += square + 6;
  }
  ctx.globalAlpha = 1;
  drawText(ctx, theme, more, x + 2, baseline, { size: legendSize, color: colors.muted });
}

// --- hábitos ---

function habitTitle(item, t) {
  const { habit } = item;
  let title = habit.code ? `${habit.code} · ${habit.name}` : habit.name;
  if (habit.status !== 'active') title += ` (${t(`report.status.${habit.status}`)})`;
  return title;
}

function statSegments(item, t, language) {
  const segments = [t('report.image.marks', { count: item.marks.length })];
  segments.push(
    item.closedPeriods > 0
      ? t('report.image.periods', { met: item.metPeriods, total: item.closedPeriods })
      : t('report.image.no_periods'),
  );
  if (item.score) {
    segments.push(
      item.score.value === null
        ? t('report.image.score_no_data')
        : t('report.image.score', { value: item.score.value }),
    );
    if (item.score.success !== null) {
      segments.push(item.score.success ? t('report.success') : t('report.failure'));
    }
  }
  if (item.durationMinutes !== null) {
    segments.push(t('report.image.minutes', { count: item.durationMinutes }));
  }
  if (item.cost) {
    segments.push(t('report.image.spend', { value: formatMoney(item.cost.spendCents, language) }));
    const latest = item.cost.latestLimit;
    if (latest && item.cost.limitCents !== null) {
      segments.push(
        t(`report.image.limit_${item.cost.limitPeriod}`, {
          spend: formatMoney(latest.spend_cents, language),
          limit: formatMoney(item.cost.limitCents, language),
        }),
      );
    }
  }
  return segments;
}

function extraSegments(item, t) {
  const segments = [];
  if (item.reward) segments.push(t('report.image.reward', { text: item.reward }));
  if (item.punishment) segments.push(t('report.image.punishment', { text: item.punishment }));
  return segments;
}

function sizesFor(scale) {
  return {
    title: 36 * scale,
    text: 28 * scale,
    titleLine: 46 * scale,
    textLine: 38 * scale,
    gap: 22 * scale,
  };
}

// Linhas de cada hábito (já quebradas e cortadas) na escala e na tentativa dadas
function layoutHabits(ctx, theme, report, t, language, scale, stage) {
  const sizes = sizesFor(scale);
  const indent = Math.round(sizes.title * 0.6) + 14;
  const width = CONTENT_WIDTH - indent;
  setFont(ctx, theme, sizes.text, 500);
  const blocks = report.habits.map((item) => {
    const stats = wrapSegments(ctx, statSegments(item, t, language), width, stage.statLines);
    const extras = stage.extras ? wrapSegments(ctx, extraSegments(item, t), width, 2) : [];
    const lines = [...stats, ...extras];
    return { item, lines, height: sizes.titleLine + lines.length * sizes.textLine + sizes.gap };
  });
  return { sizes, indent, width, blocks };
}

// A melhor arrumação que cabe em `available`: `{layout, rank}`, com `rank` a posição da tentativa
// (0 é tudo na letra maior); sem nenhuma, `{layout: null, rank: Infinity}`
function chooseLayout(ctx, theme, report, t, language, available) {
  let rank = 0;
  for (const stage of STAGES) {
    for (const scale of SCALES) {
      const layout = layoutHabits(ctx, theme, report, t, language, scale, stage);
      const height = layout.blocks.reduce((sum, block) => sum + block.height, 0);
      if (height <= available) return { layout, rank };
      rank += 1;
    }
  }
  return { layout: null, rank: Infinity };
}

function habitsTop(geometry) {
  return HEATMAP_TOP + 7 * geometry.pitch + LEGEND_OFFSET + HABITS_OFFSET;
}

// O maior mapa de calor com que os hábitos saem tão bem quanto com o menor
function planLayout(ctx, theme, report, t, language) {
  let best = null;
  for (const maxCell of CELL_SIZES) {
    const geometry = heatmapGeometry(report, maxCell);
    const choice = chooseLayout(ctx, theme, report, t, language, HABITS_BOTTOM - habitsTop(geometry));
    if (best === null || choice.rank < best.rank) best = { geometry, ...choice };
    if (best.rank === 0) break;
  }
  return best;
}

function drawHabits(ctx, report, theme, t, language, top, chosen) {
  const { colors } = theme;
  const available = HABITS_BOTTOM - top;
  if (report.habits.length === 0) {
    drawText(ctx, theme, t('report.image.no_habits'), PAD, top + 32, { size: 28, color: colors.muted });
    return;
  }

  let layout = chosen;
  let hidden = 0;
  if (!layout) {
    // Nem na menor letra: mostra os que cabem e "+N hábitos"
    layout = layoutHabits(
      ctx,
      theme,
      report,
      t,
      language,
      SCALES[SCALES.length - 1],
      STAGES[STAGES.length - 1],
    );
    const reserve = layout.sizes.textLine + layout.sizes.gap;
    let used = 0;
    let shown = 0;
    while (shown < layout.blocks.length && used + layout.blocks[shown].height + reserve <= available) {
      used += layout.blocks[shown].height;
      shown += 1;
    }
    hidden = layout.blocks.length - shown;
    layout.blocks = layout.blocks.slice(0, shown);
  }

  const { sizes, indent, width } = layout;
  let y = top;
  for (const { item, lines, height } of layout.blocks) {
    const radius = sizes.title * 0.3;
    ctx.fillStyle = habitColor(theme, item.habit);
    ctx.beginPath();
    ctx.arc(PAD + radius, y + sizes.title * 0.62, radius, 0, Math.PI * 2);
    ctx.fill();
    drawText(ctx, theme, habitTitle(item, t), PAD + indent, y + sizes.title, {
      size: sizes.title,
      weight: 700,
      color: colors.fg,
      maxWidth: width,
    });
    lines.forEach((line, index) => {
      const baseline = y + sizes.titleLine + index * sizes.textLine + sizes.text;
      drawText(ctx, theme, line, PAD + indent, baseline, {
        size: sizes.text,
        color: colors.muted,
        maxWidth: width,
      });
    });
    y += height;
  }
  if (hidden > 0) {
    drawText(ctx, theme, t('report.image.more_habits', { count: hidden }), PAD, y + sizes.text, {
      size: sizes.text,
      weight: 700,
      color: colors.fg,
    });
  }
}

/**
 * Desenha o relatório no contexto 2D (de um canvas IMAGE_WIDTH × IMAGE_HEIGHT). `theme`: de
 * readImageTheme; `today`: hoje no fuso do relatório (a data do rodapé); `t` e `language`: o
 * idioma dos textos.
 */
export function drawReport(ctx, report, { t, language, theme, today }) {
  const { colors } = theme;
  ctx.save();
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  ctx.globalAlpha = 1;
  ctx.fillStyle = colors.bg;
  ctx.fillRect(0, 0, IMAGE_WIDTH, IMAGE_HEIGHT);

  drawText(ctx, theme, 'ethos', PAD, PAD + 28, { size: 28, weight: 700, color: colors.muted });
  drawText(ctx, theme, t('report.image.title'), PAD, PAD + 100, { size: 56, weight: 700, color: colors.fg });
  const period = t('report.image.period', {
    from: formatShortDay(report.from, language),
    to: formatShortDay(report.to, language),
  });
  drawText(ctx, theme, period, PAD, PAD + 148, { size: 30, color: colors.muted });

  const plan = planLayout(ctx, theme, report, t, language);
  drawHeatmap(ctx, report, theme, t, HEATMAP_TOP, plan.geometry);
  drawHabits(ctx, report, theme, t, language, habitsTop(plan.geometry), plan.layout);
  const footer = t('report.image.footer', { date: formatShortDay(today, language) });
  drawText(ctx, theme, footer, PAD, FOOTER_BASELINE, { size: 22, color: colors.muted });
  ctx.restore();
}

async function loadFonts(doc, font) {
  if (typeof doc.fonts?.load !== 'function') return;
  try {
    await Promise.all([500, 700].map((weight) => doc.fonts.load(`${weight} 32px ${font}`)));
  } catch {
    // Sem a fonte, o canvas usa a reserva da lista (monoespaçada do sistema)
  }
}

function canvasBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('o canvas não gerou o PNG'));
    }, IMAGE_MIME);
  });
}

/**
 * Gera a imagem do relatório: Promise de um File PNG IMAGE_WIDTH × IMAGE_HEIGHT, com o nome
 * "ethos-<from>_<to>.png". `theme` padrão: o tema atual da página.
 */
export async function renderReportImage(report, { t, language, today, theme, doc = globalThis.document }) {
  const imageTheme = theme ?? readImageTheme(doc.documentElement);
  const canvas = doc.createElement('canvas');
  canvas.width = IMAGE_WIDTH;
  canvas.height = IMAGE_HEIGHT;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas 2D indisponível');
  await loadFonts(doc, imageTheme.font);
  drawReport(ctx, report, { t, language, theme: imageTheme, today });
  const blob = await canvasBlob(canvas);
  return new File([blob], reportFilename(report.from, report.to, 'png'), { type: IMAGE_MIME });
}
