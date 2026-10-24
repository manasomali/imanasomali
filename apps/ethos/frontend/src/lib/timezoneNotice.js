// Aviso de fuso: o fuso da conta (users.timezone) nasce com o do navegador no primeiro acesso e
// depois só muda na tela de conta. Quando o navegador está noutro fuso (ex.: numa viagem), o app
// sugere a troca, sem mudar nada sozinho. "Agora não" vale para aquele par de fusos

import { readItem, writeItem } from './storage';
import { sameTimezone } from './time';

export const DISMISSED_KEY = 'ethos:timezone-notice-dismissed';

function pair(saved, browser) {
  return `${saved}|${browser}`;
}

export function shouldSuggestTimezone(saved, browser) {
  if (!saved || !browser || sameTimezone(saved, browser)) return false;
  return readItem(DISMISSED_KEY) !== pair(saved, browser);
}

export function dismissTimezoneNotice(saved, browser) {
  writeItem(DISMISSED_KEY, pair(saved, browser));
}
