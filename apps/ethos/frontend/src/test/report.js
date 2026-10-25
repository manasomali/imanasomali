// Fixtures do relatório e do export: itens do GET /habits/progress, dados prontos para
// buildReport, um contexto 2D falso (o jsdom não tem canvas) e um tema de imagem.

import { HttpResponse, http } from 'msw';
import { createTestI18n } from './i18n';
import { habitFixture, markFixture } from './habits';
import { api, server } from './server';

/** Um item de `habits` do GET /habits/progress. */
export function progressItem(habit = habitFixture(), overrides = {}) {
  return {
    habit,
    goal_target: habit.duration_enabled ? habit.goal_count * habit.duration_minutes : habit.goal_count,
    periods: [],
    marks_range: null,
    marks: [],
    ...overrides,
  };
}

/** Dados no formato de fetchReportData (o que buildReport recebe). */
export function reportData({ from = '2026-03-01', to = '2026-03-31', timezone = 'America/Sao_Paulo', habits = [] } = {}) {
  return { from, to, timezone, habits };
}

/** Um hábito com todos os recursos ligados (pontuação, custo com limite, duração, observação). */
export function fullHabit(overrides = {}) {
  return habitFixture({
    id: 1,
    name: 'Running',
    code: 'RUN',
    multi_mark: true,
    duration_enabled: true,
    duration_minutes: 30,
    notes_enabled: true,
    score_enabled: true,
    score_threshold: 70,
    score: { value: 80, success: true },
    reward: 'Pizza',
    punishment: 'Run 5 km',
    cost_enabled: true,
    cost_level: 'mark',
    cost_cents: 500,
    cost_limit_cents: 2000,
    cost_limit_period: 'month',
    ...overrides,
  });
}

/** Uma marcação com tudo preenchido. */
export function fullMark(overrides = {}) {
  return markFixture({ duration_minutes: 30, cost_cents: 1250, note: 'Good run', ...overrides });
}

/** Tema da imagem com valores fixos (nos testes, cores fixas são permitidas). */
export function imageTheme() {
  const habits = {
    red: '#dc2626',
    orange: '#c2410c',
    amber: '#b45309',
    yellow: '#a16207',
    lime: '#4d7c0f',
    green: '#15803d',
    teal: '#0f766e',
    cyan: '#0e7490',
    blue: '#2563eb',
    indigo: '#4f46e5',
    violet: '#7c3aed',
    pink: '#db2777',
  };
  return {
    colors: { fg: '#000000', bg: '#ffffff', muted: '#595959', surface: '#f5f5f5' },
    habits,
    font: "'Fira Mono', monospace",
  };
}

/**
 * Contexto 2D falso: grava as chamadas e mede o texto como fonte monoespaçada (0,6 × o tamanho
 * por caractere). `texts`: cada fillText com a fonte, a posição e a largura medida.
 */
export function fakeContext() {
  const calls = { fillRect: 0, arc: 0, fill: 0, beginPath: 0 };
  const texts = [];
  const rects = [];
  const state = [];
  const ctx = {
    font: '10px sans-serif',
    fillStyle: '#000000',
    globalAlpha: 1,
    textAlign: 'start',
    textBaseline: 'alphabetic',
    save() {
      state.push({ font: this.font, fillStyle: this.fillStyle, globalAlpha: this.globalAlpha });
    },
    restore() {
      Object.assign(this, state.pop());
    },
    measureText(text) {
      const size = Number(/(\d+(?:\.\d+)?)px/.exec(this.font)[1]);
      return { width: Array.from(text).length * size * 0.6 };
    },
    fillText(text, x, y, maxWidth) {
      texts.push({ text, x, y, maxWidth, font: this.font, color: this.fillStyle, width: this.measureText(text).width });
    },
    fillRect(x, y, width, height) {
      calls.fillRect += 1;
      rects.push({ x, y, width, height, color: this.fillStyle, alpha: this.globalAlpha });
    },
    beginPath() {
      calls.beginPath += 1;
    },
    arc() {
      calls.arc += 1;
    },
    fill() {
      calls.fill += 1;
    },
  };
  return { ctx, calls, texts, rects };
}

/** O texto de um Blob/File, com o BOM (o FileReader.readAsText o tiraria). */
export function readFileText(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new TextDecoder('utf-8', { ignoreBOM: true }).decode(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

/** O t do i18next no idioma dado (traduções reais de public/locales). */
export async function translator(language) {
  const i18n = createTestI18n();
  await i18n.changeLanguage(language);
  return i18n.getFixedT(language);
}

/**
 * API falsa do GET /habits/progress: responde com `respond(query)` (padrão: os itens dados,
 * filtrados por habit_ids). Devolve as queries recebidas.
 */
export function mockProgressApi({ items = [], timezone = 'America/Sao_Paulo', respond } = {}) {
  const queries = [];
  server.use(
    http.get(api('/habits/progress'), ({ request }) => {
      const url = new URL(request.url);
      const query = {
        from: url.searchParams.get('from'),
        to: url.searchParams.get('to'),
        habit_ids: url.searchParams.getAll('habit_ids').map(Number),
      };
      queries.push(query);
      if (respond) return respond(query);
      const wanted = query.habit_ids.length > 0 ? new Set(query.habit_ids) : null;
      return HttpResponse.json({
        from: query.from,
        to: query.to,
        timezone,
        habits: items.filter((item) => !wanted || wanted.has(item.habit.id)),
      });
    }),
  );
  return queries;
}
