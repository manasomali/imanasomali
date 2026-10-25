// Desenho do calendário: a grade (cada mês em semanas de 7 colunas) ou as colunas (cada mês uma
// coluna, com os dias de cima para baixo). A visão é separada da faixa (calendarRange.js): as duas
// desenham a mesma faixa, e trocar uma não mexe na outra. Fica na URL (`?view=grid|columns`) e
// lembrada no navegador (VIEW_STORAGE_KEY), a mesma escolha nas duas abas.

export const CALENDAR_VIEWS = Object.freeze(['grid', 'columns']);

// Quem nunca escolheu vê a grade, o calendário de sempre
export const DEFAULT_CALENDAR_VIEW = 'grid';

// Chave do localStorage com a última visão escolhida
export const VIEW_STORAGE_KEY = 'ethos:calendar-view';

/** Lê uma visão (da URL ou do navegador): uma de CALENDAR_VIEWS, ou null. */
export function parseCalendarView(value) {
  return CALENDAR_VIEWS.includes(value) ? value : null;
}

/** A visão da URL (`param`), senão a lembrada (`stored`), senão DEFAULT_CALENDAR_VIEW. */
export function resolveView(param, stored) {
  return parseCalendarView(param) ?? parseCalendarView(stored) ?? DEFAULT_CALENDAR_VIEW;
}
