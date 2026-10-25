import { useEffect } from 'react';
import { Link, useLocation } from 'react-router';
import PageTitle from '../PageTitle';
import styles from './styles.module.css';

// Documento de texto puro com seções (termos, privacidade e ajuda): título, uma nota opcional
// embaixo dele (`note`, ex.: a versão dos termos), o sumário e as seções. Tudo vai como texto (o
// React escapa tudo), nunca como HTML. Cada seção tem o `id` do JSON, que serve de âncora
// (/termos#account); cada item de `paragraphs` é um parágrafo (texto) ou uma lista (array de
// textos). `language` é o idioma do texto que veio (pode ser o de reserva), para o `lang`.
export default function TextDocument({ language, title, note = null, sections, contentsLabel }) {
  const { hash } = useLocation();

  // Link direto para uma seção: o navegador procura a âncora antes de o texto chegar, e este
  // componente só monta com o texto carregado. Também rola num clique no sumário
  useEffect(() => {
    if (hash.length < 2) return;
    document.getElementById(hash.slice(1))?.scrollIntoView?.();
  }, [hash]);

  return (
    <article lang={language} className={styles.article}>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>
      {note && <p className={styles.note}>{note}</p>}

      <nav aria-label={contentsLabel} className={styles.contents}>
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
