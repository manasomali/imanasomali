import { useTranslation } from 'react-i18next';
import { intlLocale } from '../../i18n';
import styles from './styles.module.css';

// Publication date and tags of a post. `date` is YYYY-MM-DD, read as a calendar day (UTC), so
// it shows the same day in every time zone.
function PostMeta({ date, tags = [] }) {
  const { t, i18n } = useTranslation();
  const day = new Date(`${date}T00:00:00Z`);
  const label = Number.isNaN(day.getTime())
    ? date
    : new Intl.DateTimeFormat(intlLocale(i18n.resolvedLanguage), {
      dateStyle: 'long',
      timeZone: 'UTC',
    }).format(day);

  return (
    <div className={styles.meta}>
      <time dateTime={date}>{label}</time>
      {tags.length > 0 && (
        <ul className={styles.tags} aria-label={t('components.post_meta.tags')}>
          {tags.map((tag) => (
            <li key={tag} className={styles.tag}>{t(`pages.posts.tags.${tag}`)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default PostMeta;
