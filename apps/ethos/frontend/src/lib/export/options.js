// Informações que a pessoa escolhe mostrar no relatório e nos exports. Cada uma só aparece num
// hábito que tem o recurso ligado (ethos-plan.md: recurso desligado fica escondido):
// - score: pontuação, limite e sucesso/falha (com `score_enabled`);
// - reward, punishment: recompensa e punição (dependem da pontuação, como no plano);
// - cost: gasto, custo e limite (com `cost_enabled`);
// - duration: minutos (com `duration_enabled`);
// - note: observação de cada marcação (com `notes_enabled`). Começa desligada: é texto livre, que
//   a pessoa pode não querer num arquivo ou numa imagem;
// - author: quem marcou (email), só no CSV e no JSON. A imagem nunca traz emails nem observações.

export const REPORT_FIELDS = Object.freeze([
  'score',
  'reward',
  'punishment',
  'cost',
  'duration',
  'note',
  'author',
]);

/** O que vem marcado na tela. */
export const DEFAULT_OPTIONS = Object.freeze({
  score: true,
  reward: true,
  punishment: true,
  cost: true,
  duration: true,
  note: false,
  author: true,
});

/** Tudo ligado: o "exportar tudo" leva todos os dados. */
export const ALL_OPTIONS = Object.freeze(
  Object.fromEntries(REPORT_FIELDS.map((field) => [field, true])),
);

/** Só as chaves conhecidas, como booleanos; o que faltar fica desligado. */
export function normalizeOptions(options = {}) {
  return Object.fromEntries(REPORT_FIELDS.map((field) => [field, options[field] === true]));
}

/** O que aparece de fato num hábito: a escolha da pessoa e o recurso ligado nele. */
export function visibleFields(habit, options) {
  const scored = habit.score_enabled === true;
  return {
    score: options.score && scored,
    reward: options.reward && scored,
    punishment: options.punishment && scored,
    cost: options.cost && habit.cost_enabled === true,
    duration: options.duration && habit.duration_enabled === true,
    note: options.note && habit.notes_enabled === true,
    author: options.author,
  };
}
