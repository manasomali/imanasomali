# manasomali.com

Personal website built with React 19, React Router and Vite. Styles are plain CSS Modules over the shared design tokens in [`packages/tokens/tokens.css`](../packages/tokens/tokens.css) (light and dark themes); texts live in `public/locales/{pt,en}/translation.json`.

```bash
npm install
npm run dev     # http://localhost:5173
npm run lint
npm run build   # outputs to dist/
```

- Projects and publications are listed in `src/data/`; their titles and descriptions are translation keys.

# Deploy

Every push to `main` that touches `site/**` or `packages/**` builds this folder and publishes `site/dist/` (`.github/workflows/deploy.yaml`). Pull requests touching the same paths run lint and build only.

[<img alt="Website Deployed for Free with web deploy" src="https://img.shields.io/badge/Website deployed for free with-web deploy-%3CCOLOR%3E?style=for-the-badge&color=2b9348">](https://github.com/SamKirkland/web-deploy)
