import { useTranslation } from 'react-i18next';
import { FiArrowUpRight } from 'react-icons/fi';
import styles from './styles.module.css';

function Project({
  title, description, link, image,
}) {
  const { t } = useTranslation();
  return (
    <article className={styles.card}>
      <div className={styles.media}>
        <img src={image} alt="" loading="lazy" decoding="async" />
      </div>
      <div className={styles.body}>
        <h2 className={styles.title}>{title}</h2>
        <p className={styles.description}>{description}</p>
        <a className={styles.button} href={link} target="_blank" rel="noopener noreferrer">
          {t('components.project.access')}
          <span className="visually-hidden">{`: ${title}`}</span>
          <FiArrowUpRight aria-hidden />
        </a>
      </div>
    </article>
  );
}

export default Project;
