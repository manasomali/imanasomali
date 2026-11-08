// Idioma da conta na API ("pt" ou "en", users.locale) a partir do idioma da tela

/** "pt", "pt-BR" e "PT" viram "pt"; qualquer outro (inclusive ausente), "en", o fallback do i18n. */
export function apiLocale(language) {
  return typeof language === 'string' && /^pt(-|$)/i.test(language) ? 'pt' : 'en';
}
