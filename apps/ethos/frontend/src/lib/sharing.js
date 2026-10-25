// Regras do compartilhamento que a tela repete só para mostrar (o backend é quem garante)

/**
 * Vagas de convidados de um hábito (`MAX_GUESTS_PER_HABIT`, que a API manda como `guest_limit`
 * no GET /habits/{id}/members): membros, sem o dono, mais convites pendentes. `left` nunca é
 * negativo (o limite pode ter baixado na config depois dos convites).
 */
export function guestSlots(members, invites, limit) {
  const guests = members.filter((member) => member.role !== 'owner').length;
  const used = guests + invites.length;
  return { used, limit, left: Math.max(0, limit - used) };
}
