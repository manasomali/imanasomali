import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { accountApps, appPath, appTexts } from '../../lib/apps';
import styles from './styles.module.css';

// Aplicações da conta (`apps` do GET /me, na ordem do IMAGO_APPS), com o link de cada uma
// (/<nome>/, fora do basename: navegação de página inteira) e a descrição do translation.json
export default function Apps({ me }) {
  const { t, i18n } = useTranslation();
  const ids = useId();
  const titleId = `${ids}-title`;
  const exists = (key) => i18n.exists(key);
  const apps = accountApps(me.apps);

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.sectionTitle}>
        {t('pages.account.apps.title')}
      </h2>
      <p className={styles.muted}>{t('pages.account.apps.intro')}</p>
      {apps.length === 0 ? (
        <p>{t('pages.account.apps.empty')}</p>
      ) : (
        <ul className={styles.apps}>
          {apps.map((name) => {
            const texts = appTexts(name, t, exists);
            return (
              <li key={name} className={styles.app}>
                <a href={appPath(name)} className={styles.appLink}>
                  {texts.name}
                </a>
                {texts.description && <p className={styles.muted}>{texts.description}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
