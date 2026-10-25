import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import { loadLegalDocument } from '../../lib/legal';
import styles from './styles.module.css';

// Termos de uso (name="terms") e política de privacidade (name="privacy"), abertos sem login.
// O texto é puro e vai como texto (o React escapa tudo), nunca como HTML. Cada seção tem o `id`
// do JSON, que serve de âncora (/termos#account)
export default function Legal({ name }) {
  const { t, i18n } = useTranslation();
  const { hash } = useLocation();
  const language = i18n.resolvedLanguage;
  const legal = useQuery({
    queryKey: ['legal', name, language],
    queryFn: () => loadLegalDocument(name, language),
    // O texto faz parte do build: não muda enquanto a aba está aberta
    staleTime: Infinity,
  });
  const loaded = legal.data !== undefined;

  // Link direto para uma seção: o navegador procura a âncora antes de o texto chegar
  useEffect(() => {
    if (!loaded || hash.length < 2) return;
    document.getElementById(hash.slice(1))?.scrollIntoView?.();
  }, [loaded, hash]);

  if (!loaded) {
    return (
      <>
        <PageTitle title={t(`pages.${name}.title`)} />
        {legal.isError ? (
          <ErrorMessage error={legal.error} onRetry={() => legal.refetch()} />
        ) : (
          <p role="status">{t('common.loading')}</p>
        )}
      </>
    );
  }

  const { title, version, sections } = legal.data;
  return (
    <article lang={legal.data.language} className={styles.article}>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.version}>{t('legal.version', { version })}</p>

      <nav aria-label={t('legal.contents')} className={styles.contents}>
        <ol>
          {sections.map((section) => (
            <li key={section.id}>
              <Link to={`#${section.id}`}>{section.title}</Link>
            </li>
          ))}
        </ol>
      </nav>

      {sections.map((section) => (
        <section
          key={section.id}
          id={section.id}
          aria-labelledby={`${section.id}-title`}
          className={styles.section}
        >
          <h2 id={`${section.id}-title`}>{section.title}</h2>
          {section.paragraphs.map((block, index) =>
            Array.isArray(block) ? (
              <ul key={index}>
                {block.map((item, itemIndex) => (
                  <li key={itemIndex}>{item}</li>
                ))}
              </ul>
            ) : (
              <p key={index}>{block}</p>
            ),
          )}
        </section>
      ))}
    </article>
  );
}
