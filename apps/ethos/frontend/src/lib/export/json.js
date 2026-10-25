// JSON do relatório, no formato do plano:
//   { version, generated_at, period: {from, to}, habits: [{ configuração, marks, periods }] }
// O schema completo (campos, tipos e quando cada um aparece) está em ./schema.md, e
// json.test.js valida a saída contra ele. Mudou o formato? Atualize o schema.md e, se um leitor
// antigo deixaria de entender o arquivo, suba EXPORT_VERSION.

export const EXPORT_VERSION = 1;
export const JSON_MIME = 'application/json';

function markOut(mark, show) {
  const out = { id: mark.id, marked_at: mark.marked_at, date: mark.date, time: mark.time };
  if (show.author) out.author = mark.author ? { id: mark.author.id, email: mark.author.email } : null;
  if (show.duration) out.duration_minutes = mark.duration_minutes;
  if (show.cost) out.cost_cents = mark.cost_cents;
  if (show.note) out.note = mark.note;
  return out;
}

function periodOut(period, show) {
  const out = {
    first_day: period.first_day,
    last_day: period.last_day,
    value: period.value,
    met: period.met,
  };
  if (show.cost && Number.isSafeInteger(period.spend_cents)) out.spend_cents = period.spend_cents;
  return out;
}

function habitOut(item) {
  const { habit, show } = item;
  const out = {
    id: habit.id,
    name: habit.name,
    code: habit.code,
    description: habit.description,
    color: habit.color,
    status: habit.status,
    role: habit.role,
    created_at: habit.created_at,
    archived_at: habit.archived_at,
    goal: { ...item.goal },
    multi_mark: habit.multi_mark,
  };
  if (show.duration) out.duration_minutes = habit.duration_minutes;
  if (item.score) out.score = { ...item.score };
  if (show.reward) out.reward = item.reward;
  if (show.punishment) out.punishment = item.punishment;
  if (item.cost) {
    out.cost = {
      level: item.cost.level,
      cents: item.cost.cents,
      limit_cents: item.cost.limitCents,
      limit_period: item.cost.limitPeriod,
      spend_cents: item.cost.spendCents,
    };
  }
  out.marks = item.marks.map((mark) => markOut(mark, show));
  out.periods = item.periods.map((period) => periodOut(period, show));
  if (item.costPeriods) {
    out.cost_periods = item.costPeriods.map((period) => ({
      first_day: period.first_day,
      last_day: period.last_day,
      spend_cents: period.spend_cents,
      limit_percent: period.limit_percent,
    }));
  }
  return out;
}

/** O objeto do export. `generatedAt`: o instante da geração (Date). */
export function toExportObject(report, { generatedAt }) {
  return {
    version: EXPORT_VERSION,
    generated_at: generatedAt.toISOString(),
    timezone: report.timezone,
    period: { from: report.from, to: report.to },
    options: { ...report.options },
    habits: report.habits.map(habitOut),
  };
}

/** O texto do arquivo .json (indentado, com quebra de linha no fim). */
export function toJson(report, { generatedAt }) {
  return `${JSON.stringify(toExportObject(report, { generatedAt }), null, 2)}\n`;
}
