import { useTranslation } from 'react-i18next';
import { FiChevronDown, FiDownload, FiExternalLink } from 'react-icons/fi';
import styles from './styles.module.css';

function buildReference({
  titulo, autores, local, revista, evento, ano, link, doi, issn, isbn,
}, accessedLabel) {
  let reference = [autores, titulo, local, revista, evento, ano]
    .filter((part) => part !== '')
    .map((part) => part.replace(/\.$/, ''))
    .join('. ');
  if (doi !== '') {
    reference = `${reference}. DOI: ${doi}`;
  } else if (issn !== '') {
    reference = `${reference}. ISSN: ${issn}`;
  } else if (isbn !== '') {
    reference = `${reference}. ISBN: ${isbn}`;
  }
  return `${reference}. ${accessedLabel}: <${link}>.`;
}

function Publication(props) {
  const { t } = useTranslation();
  const {
    titulo, ano, link, arquivo,
  } = props;

  return (
    <details className={styles.item}>
      <summary className={styles.summary}>
        <span className={styles.year}>{ano}</span>
        <span className={styles.title}>{titulo}</span>
        <FiChevronDown className={styles.chevron} aria-hidden />
      </summary>
      <div className={styles.content}>
        <p className={styles.reference}>{buildReference(props, t('components.publication.accessed'))}</p>
        <div className={styles.actions}>
          <a className={styles.action} href={arquivo} target="_blank" rel="noopener noreferrer">
            <FiDownload aria-hidden />
            {t('components.publication.download')}
          </a>
          <a className={styles.action} href={link} target="_blank" rel="noopener noreferrer">
            <FiExternalLink aria-hidden />
            {t('components.publication.source')}
          </a>
        </div>
      </div>
    </details>
  );
}

export default Publication;
