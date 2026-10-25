import { useTranslation } from 'react-i18next';
import { FiArrowRight, FiArrowUpRight } from 'react-icons/fi';
import styles from './styles.module.css';

// `sameTab` is for pages served from this domain but outside the site's router (the apps under
// /<name>/): a plain full page load, so the browser's back button returns here.
// `imageAlt` stays empty when the image only repeats the title (a screenshot next to it).
function Project({
  title, subtitle, year, description, link, image, imageAlt = '', sameTab = false,
}) {
  const { t } = useTranslation();
  const Arrow = sameTab ? FiArrowRight : FiArrowUpRight;
  // non-breaking spaces keep the year on the same line as the subtitle's last word
  const meta = [subtitle, year].filter(Boolean).join('\u00a0·\u00a0');
  return (
    <article className={styles.card}>
      <div className={styles.media}>
        <img src={image} alt={imageAlt} loading="lazy" decoding="async" />
      </div>
      <div className={styles.body}>
        <h2 className={styles.title}>{title}</h2>
        {meta && <p className={styles.meta}>{meta}</p>}
        <p className={styles.description}>{description}</p>
        <a
          className={styles.button}
          href={link}
          target={sameTab ? undefined : '_blank'}
          rel={sameTab ? undefined : 'noopener noreferrer'}
        >
          {t('components.project.access')}
          <span className="visually-hidden">{`: ${title}`}</span>
          <Arrow size={16} aria-hidden />
        </a>
      </div>
    </article>
  );
}

export default Project;
