// i18n pt/en. Como no site: traduções baixadas em runtime de public/locales (não vão no bundle) e
// idioma na chave compartilhada localStorage.i18nextLng, então quem escolhe o idioma no site entra
// no ethos com ele, e vice-versa (contrato em packages/tokens/README.md)

import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import Backend from 'i18next-http-backend';
import LanguageDetector from 'i18next-browser-languagedetector';

export const LANGUAGES = Object.freeze(['pt', 'en']);

// Chave e códigos iguais aos do site. O detector altera o objeto que recebe: cada instância ganha
// uma cópia
export const DETECTION = Object.freeze({
  order: Object.freeze(['localStorage', 'navigator']),
  lookupLocalStorage: 'i18nextLng',
  caches: Object.freeze(['localStorage']),
});

/**
 * Cria e inicia a instância do app. Sem `resources`, baixa as traduções de
 * /ethos/locales/<idioma>/translation.json; os testes passam os JSON direto.
 */
export function createI18n({ resources } = {}) {
  const instance = i18next.createInstance();
  instance.use(LanguageDetector).use(initReactI18next);
  if (!resources) instance.use(Backend);

  // Mantém o <html lang> igual ao idioma em uso
  instance.on('languageChanged', (lng) => {
    document.documentElement.lang = instance.resolvedLanguage || lng;
  });

  instance.init({
    fallbackLng: 'en',
    supportedLngs: [...LANGUAGES],
    // "pt-BR" salvo pelo site (ou vindo do navegador) vira "pt"
    load: 'languageOnly',
    detection: { ...DETECTION, order: [...DETECTION.order], caches: [...DETECTION.caches] },
    resources,
    initAsync: !resources,
    backend: { loadPath: `${import.meta.env.BASE_URL}locales/{{lng}}/translation.json` },
    // O React já escapa o texto
    interpolation: { escapeValue: false },
  });
  return instance;
}
