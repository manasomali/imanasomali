import { Link as RouterLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FiArrowRight } from 'react-icons/fi';
import PostMeta from '../PostMeta';
import styles from './styles.module.css';

// The title link stretches over the whole card, so the card is one click target and screen
// readers still hear a single link named after the post.
function PostCard({
  slug, title, summary, date, tags,
}) {
  const { t } = useTranslation();
  return (
    <article className={styles.card}>
      <PostMeta date={date} tags={tags} />
      <h2 className={styles.title}>
        <RouterLink to={`/posts/${slug}`} className={styles.link}>{title}</RouterLink>
      </h2>
      <p className={styles.summary}>{summary}</p>
      <span className={styles.more} aria-hidden>
        {t('components.post_card.read')}
        <FiArrowRight size={16} />
      </span>
    </article>
  );
}

export default PostCard;
