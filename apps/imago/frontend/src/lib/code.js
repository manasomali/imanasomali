// Código de 6 dígitos (login e exclusão de conta) e a espera entre um envio e o próximo

export const CODE_LENGTH = 6;

// A API aceita 1 código por minuto por email (somando login e exclusão)
export const RESEND_SECONDS = 60;

/** Só os dígitos ASCII do que foi digitado ou colado ("123 456" vira "123456"), até 6. */
export function onlyDigits(value) {
  return String(value ?? '').replace(/[^0-9]/g, '').slice(0, CODE_LENGTH);
}

/** Se `value` é um código completo (exatamente 6 dígitos ASCII). */
export function isCompleteCode(value) {
  return typeof value === 'string' && /^[0-9]{6}$/.test(value);
}
