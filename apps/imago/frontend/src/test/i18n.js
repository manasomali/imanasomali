import en from '../../public/locales/en/translation.json';
import pt from '../../public/locales/pt/translation.json';
import { createI18n } from '../i18n';

export const translations = { en, pt };

/** A instância do app (src/i18n.js) com os JSON de public/locales já carregados. */
export function createTestI18n() {
  return createI18n({ resources: { en: { translation: en }, pt: { translation: pt } } });
}
