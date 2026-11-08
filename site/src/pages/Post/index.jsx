import { Component, Suspense } from 'react';
import { Link as RouterLink, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FiArrowLeft } from 'react-icons/fi';
import PageDefault from '../../components/PageDefault';
import Title from '../../components/Title';
import Prose from '../../components/Prose';
import PostMeta from '../../components/PostMeta';
import Page404 from '../Page404';
import posts from '../../data/posts';
import styles from './styles.module.css';

// A post's body is a lazy chunk. If it fails to load (offline, or a deploy replaced the
// chunk while this tab still runs the old build), show `fallback` instead of letting the
// error unmount the whole app.
class BodyErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    const { failed } = this.state;
    const { fallback, children } = this.props;
    return failed ? fallback : children;
  }
}

function Post() {
  const { slug } = useParams();
  const { t } = useTranslation();
  const post = posts.find((item) => item.slug === slug);

  if (!post) return <Page404 />;

  const { Body } = post;
  const title = t(`pages.posts.items.${post.slug}.title`);

  return (
    <PageDefault title={title} width="wide">
      <Prose as="article">
        <header className={styles.header}>
          <RouterLink to="/posts" className={styles.back}>
            <FiArrowLeft size={16} aria-hidden />
            {t('pages.post.back')}
          </RouterLink>
          <Title>{title}</Title>
          <p className={styles.lead}>{t(`pages.posts.items.${post.slug}.summary`)}</p>
          <PostMeta date={post.date} tags={post.tags} />
        </header>
        <BodyErrorBoundary
          key={post.slug}
          fallback={(
            <p className={styles.status} role="alert">
              {t('pages.post.error')}
              {' '}
              <button type="button" className={styles.reload} onClick={() => window.location.reload()}>
                {t('pages.post.reload')}
              </button>
            </p>
          )}
        >
          <Suspense fallback={<p className={styles.status}>{t('pages.post.loading')}</p>}>
            <Body />
          </Suspense>
        </BodyErrorBoundary>
      </Prose>
    </PageDefault>
  );
}

export default Post;
