import { lazy } from 'react';

// Posts listed at /posts and served at /posts/<slug>. Title and summary live in
// public/locales/*/translation.json under pages.posts.items.<slug>, and tag names under
// pages.posts.tags.<tag>. The body is a lazy chunk in src/posts/<slug>/ that carries its own
// text in both languages, so long posts stay out of translation.json, which every page fetches.
// `date` is the publication day (YYYY-MM-DD). Add the URL to public/sitemap.xml too.
const posts = [
  {
    slug: 'playground-gatos',
    date: '2026-11-08',
    tags: ['diy', 'woodworking'],
    Body: lazy(() => import('../posts/playground-gatos')),
  },
];

export default posts;
