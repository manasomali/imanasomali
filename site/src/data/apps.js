// Applications the site hosts under /<name>/ (apps/README.md). Name, subtitle, description and
// image alt text live in public/locales/*/translation.json under pages.apps.items.<key>.
// The link is a full page load: the app is served by nginx, not by the site's router.
const apps = [
  {
    key: 'ethos',
    link: '/ethos/',
    image: '/ethos.svg',
    year: '2026',
  },
];

export default apps;
