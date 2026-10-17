# manasomali.com

Personal website built with React 19, React Router and Vite. Styles are plain CSS Modules over the design tokens in `src/index.css` (light and dark themes); texts live in `public/locales/{pt,en}/translation.json`.

```bash
npm install
npm run dev     # http://localhost:5173
npm run lint
npm run build   # outputs to dist/
```

- Projects and publications are listed in `src/data/`; their titles and descriptions are translation keys.
- The modernization plan and its rationale are in [docs/MODERNIZACAO.md](docs/MODERNIZACAO.md).

# Deploy

[<img alt="Website Deployed for Free with web deploy" src="https://img.shields.io/badge/Website deployed for free with-web deploy-%3CCOLOR%3E?style=for-the-badge&color=2b9348">](https://github.com/SamKirkland/web-deploy)

# Infra

The VM also hosts SQLite databases for other projects, with automated provisioning and backups. See [infra/README.md](infra/README.md).
