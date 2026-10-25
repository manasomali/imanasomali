// Duração de uma marcação ou do hábito, em minutos inteiros

/** Maior duração aceita pela API: um dia (MAX_DURATION_MINUTES em app/habits/schemas.py). */
export const MAX_DURATION_MINUTES = 24 * 60;

/** Lê minutos digitados: inteiro de 1 a MAX_DURATION_MINUTES, ou null. Recusa "1.5", "1e2", "-3". */
export function parseDuration(text) {
  if (typeof text !== 'string') return null;
  const value = text.trim();
  if (!/^\d{1,5}$/.test(value)) return null;
  const minutes = Number(value);
  return minutes >= 1 && minutes <= MAX_DURATION_MINUTES ? minutes : null;
}
