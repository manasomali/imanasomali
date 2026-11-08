import { useTranslation } from 'react-i18next';
import PageDefault from '../../components/PageDefault';
import Title from '../../components/Title';
import PostCard from '../../components/PostCard';
import posts from '../../data/posts';
import styles from './styles.module.css';

// newest first; dates are YYYY-MM-DD, so they sort as strings
const sortedPosts = [...posts].sort((a, b) => b.date.localeCompare(a.date));

function Posts() {
  const { t } = useTranslation();
  return (
    <PageDefault title={t('pages.posts.title')}>
      <Title>{t('pages.posts.title')}</Title>
      <p className={styles.intro}>{t('pages.posts.intro')}</p>
      <ul className={styles.list}>
        {sortedPosts.map((post) => (
          <li key={post.slug}>
            <PostCard
              slug={post.slug}
              title={t(`pages.posts.items.${post.slug}.title`)}
              summary={t(`pages.posts.items.${post.slug}.summary`)}
              date={post.date}
              tags={post.tags}
            />
          </li>
        ))}
      </ul>
    </PageDefault>
  );
}

export default Posts;
