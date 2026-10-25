// Banner global (GET /banners/active, sem login): texto no idioma da tela, sempre como texto puro,
// e o "fechar" lembrado no navegador por id do banner. A lista guarda só os últimos
// MAX_DISMISSED ids, para não crescer sem fim; um banner editado continua fechado (mesmo id).
// Também o formulário do admin: validação igual à da API (app/admin/schemas.py) e datas no fuso
// do admin

import { fromDateTimeLocal, toDateTimeLocal } from './datetime';
import { readItem, writeItem } from './storage';

export const DISMISSED_BANNERS_KEY = 'ethos:banners-dismissed';
export const MAX_DISMISSED = 20;

/** Tamanho máximo de cada texto (BANNER_TEXT_MAX_LENGTH em app/models.py). */
export const BANNER_TEXT_MAX_LENGTH = 280;

function isBannerId(value) {
  return Number.isSafeInteger(value) && value > 0;
}

/** Ids dos banners fechados neste navegador; valor salvo inválido vale como lista vazia. */
export function dismissedBanners() {
  const raw = readItem(DISMISSED_BANNERS_KEY);
  if (!raw) return [];
  try {
    const value = JSON.parse(raw);
    return Array.isArray(value) ? value.filter(isBannerId) : [];
  } catch {
    return [];
  }
}

export function isBannerDismissed(id) {
  return dismissedBanners().includes(id);
}

/** Lembra que o banner foi fechado. Devolve false se o navegador não guardou (modo privado). */
export function dismissBanner(id) {
  if (!isBannerId(id)) return false;
  const ids = dismissedBanners().filter((item) => item !== id);
  ids.push(id);
  return writeItem(DISMISSED_BANNERS_KEY, JSON.stringify(ids.slice(-MAX_DISMISSED)));
}

/** O texto do banner no idioma da tela: pt para "pt" e variantes, en para o resto. */
export function bannerText(banner, language) {
  const pt = typeof language === 'string' && language.toLowerCase().startsWith('pt');
  return pt ? banner.text_pt : banner.text_en;
}

/**
 * Tamanho do texto como o backend conta: sem os espaços das pontas e por caractere Unicode
 * (um emoji conta 1, não os 2 do UTF-16 de String.length).
 */
export function bannerTextLength(value) {
  return [...value.trim()].length;
}

/** Texto do banner numa linha só (a API recusa quebra de linha): quebras viram espaço. */
export function singleLine(value) {
  return value.replace(/[\r\n]+/g, ' ');
}

/**
 * Situação do banner para o admin, no instante `now` (ms): "live" (o que aparece agora, id do
 * GET /banners/active), "scheduled" (ainda não começou), "ended" (janela fechada) ou "waiting"
 * (dentro da janela, mas atrás de um banner que começou depois: só um aparece por vez).
 */
export function bannerStatus(banner, now, activeId) {
  if (activeId !== null && activeId !== undefined && banner.id === activeId) return 'live';
  if (Date.parse(banner.ends_at) <= now) return 'ended';
  if (Date.parse(banner.starts_at) > now) return 'scheduled';
  return 'waiting';
}

const TEXT_FIELDS = ['text_pt', 'text_en'];
const DATE_FIELDS = ['starts_at', 'ends_at'];
// A API recusa instantes antes de 1900 (Instant em app/marks/schemas.py)
const MIN_INSTANT = Date.UTC(1900, 0, 1);

/**
 * Estado do formulário: os textos e as datas como valores de datetime-local no fuso do admin. Sem
 * banner (novo), textos vazios, início em `now` e fim em branco.
 */
export function bannerForm(banner, timeZone, now) {
  if (!banner) {
    return { text_pt: '', text_en: '', starts_at: toDateTimeLocal(now, timeZone), ends_at: '' };
  }
  return {
    text_pt: banner.text_pt,
    text_en: banner.text_en,
    starts_at: toDateTimeLocal(banner.starts_at, timeZone),
    ends_at: toDateTimeLocal(banner.ends_at, timeZone),
  };
}

/**
 * Corpo do POST (sem `banner`) ou do PATCH (com o `banner` que está sendo editado) a partir do
 * formulário, e os erros por campo: "required", "too_long", "invalid_date" ou "ends_before_starts".
 * No PATCH vão só os campos que mudaram; data não tocada mantém o instante exato do banner (o
 * campo só mostra até os minutos, e um banner encerrado tem segundos).
 */
export function bannerPayload(form, timeZone, banner = null) {
  const initial = banner ? bannerForm(banner, timeZone) : null;
  const values = {};
  const errors = {};
  for (const name of TEXT_FIELDS) {
    const text = form[name].trim();
    const length = bannerTextLength(text);
    if (length === 0) errors[name] = 'required';
    else if (length > BANNER_TEXT_MAX_LENGTH) errors[name] = 'too_long';
    else if (!banner || text !== banner[name]) values[name] = text;
  }
  const instants = {};
  for (const name of DATE_FIELDS) {
    if (initial && form[name] === initial[name]) {
      instants[name] = Date.parse(banner[name]);
      continue;
    }
    const instant = fromDateTimeLocal(form[name], timeZone);
    if (instant === null || instant.getTime() < MIN_INSTANT) {
      errors[name] = form[name] ? 'invalid_date' : 'required';
      continue;
    }
    instants[name] = instant.getTime();
    values[name] = instant.toISOString();
  }
  if (!errors.starts_at && !errors.ends_at && instants.ends_at <= instants.starts_at) {
    errors.ends_at = 'ends_before_starts';
  }
  return { values, errors };
}
