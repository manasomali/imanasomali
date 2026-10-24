# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This is a monorepo. `site/` holds the personal website served at manasomali.com (React 19, React Router, Vite). `apps/` holds the applications the site hosts under `/<name>/` (convention in `apps/README.md`), `packages/` the code they share with the site, and `infra/` the Bash provisioning for the Oracle VM that serves it all. The VM also hosts SQLite databases for other projects. Each area deploys through its own workflow, and a push only triggers the workflows for the paths it touches. There are no npm workspaces: the site and each app have their own `package.json` and lockfile.

## Commands

Website commands run inside `site/`:

```bash
cd site
npm install
npm run dev      # http://localhost:5173 (also the "dev" entry in .claude/launch.json)
npm run lint     # ESLint, --max-warnings 0, so warnings fail it too
npm run build    # outputs to site/dist/
npm run preview
```

There is no test suite. For the website, check changes with `npm run lint`, `npm run build` (both in `site/`) and by looking at the dev server. For infra, CI runs these checks, and you can run them locally:

```bash
shellcheck -x infra/provision.sh infra/scripts/*.sh .github/scripts/*.sh
bash .github/scripts/check-python-version.sh
bash -c 'source infra/lib/common.sh && read_databases infra/databases.txt'
```

CI also runs `nginx -t` against `infra/nginx/site.conf` in an `nginx:1.24` container with stub certificates. See `.github/workflows/infra.yaml` to reproduce it.

## Website architecture (`site/`)

- **Routing**: `site/src/main.jsx` declares every route. Each page lives in `site/src/pages/<Name>/index.jsx` and wraps its content in `PageDefault`. `PageDefault` renders the menu and footer, sets `<title>` (React 19 hoists it into `<head>`), picks the content width (`width="text" | "wide"`) and scrolls to the top on navigation. In production, nginx falls back to `/index.html` (`try_files`), so client-side routes work on reload.
- **i18n**: `i18next-http-backend` fetches translations at runtime from `site/public/locales/{pt,en}/translation.json`. They are not bundled. Fallback is `en`, and `site/src/i18n.js` keeps `<html lang>` in sync. Because the first render suspends until translations load, the app is wrapped in `<Suspense>`. Any visible text must be added to **both** locale files.
- **Content data**: projects and publications are listed in `site/src/data/projects.js` and `site/src/data/publications.js`. Those files hold only links, images, years, authors and file paths. Titles and descriptions are translation keys: `pages.projects.items.<key>` and `components.list_publications.items.<id>`. To add an entry, add it to the data file and to both locale files. Images and PDFs live in `site/public/` and are referenced by absolute path (`/pi.png`, `/documents/...pdf`).
- **Styling**: plain CSS Modules (`styles.module.css` next to each component). Design tokens (colors, type scale, widths) are CSS custom properties in `packages/tokens/tokens.css`, shared with the apps. `site/src/index.css` imports them and holds only the site's global styles. Use the tokens instead of hard-coded colors.
- **Theme**: dark mode follows `prefers-color-scheme` unless the user has picked a theme. The choice is saved in `localStorage.theme` and applied as `data-theme` on `<html>` by an inline script in `site/index.html`, before first paint. `site/src/hooks/useTheme.js` toggles it. Dark token values are defined twice in `packages/tokens/tokens.css`, once under `:root[data-theme='dark']` and once under the media query, so edit both. The `theme` and `i18nextLng` keys are shared with the apps on the same origin; `packages/tokens/README.md` has the contract.
- **Icons**: icons come from `react-icons`. Size them in whole pixels, not `clamp()`/`vw`. Fractional sizes render blurry (see commit c8ffd27).
- ESLint includes `jsx-a11y`, and `react/prop-types` is off.
- SEO metadata (Open Graph, Twitter, JSON-LD Person) is static in `site/index.html`. `site/public/sitemap.xml` is maintained by hand, so update it when you add a route.

## Deploy

- **Website** (`.github/workflows/deploy.yaml`): pushes and PRs that touch `site/**`, `packages/**` or the workflow itself run `npm ci`, `npm run lint` and `npm run build` in `site/` on Node 22. A push to `main` then rsyncs `site/dist/` to `/var/www/html/` with `--delete`.
- **Apps**: each app has its own `.github/workflows/<name>.yaml`, triggered by `apps/<name>/**`, `packages/**` and the workflow itself. It does not use the `infra` concurrency group.
- **Infra** (`.github/workflows/infra.yaml`): pushes and PRs that touch `infra/**` run lint. A push to `main` also rsyncs `infra/` to `/opt/infra` and runs `provision.sh`. Credentials go to it over stdin, never as arguments. `backup-verify.yaml` runs a restore test every week. All infra jobs share the `infra` concurrency group.

## Infra (`infra/`)

Docs and comments in `infra/` are in Portuguese. Keep new ones in Portuguese. Read `infra/README.md` (how to add a project database and backend), `infra/PLANO.md` (design decisions) and `infra/RESTORE.md` (disaster recovery) before you change anything substantial.

- `provision.sh` sources `lib/*.sh` and runs `provision_swap → packages → system → databases → apps → backups → nginx`, then `scripts/smoke-test.sh`. It must stay **idempotent**: a second run with no repo changes must change nothing. Write files with `sync_file` / `sync_content` from `lib/common.sh`. They return 0 only when the content changed, and callers use that to decide whether to restart a service. That is why calls often end in `|| true`.
- `provision_nginx` (`lib/nginx.sh`) installs `infra/nginx/site.conf` plus, for each app, `infra/apps/<name>/nginx.conf` into `/etc/nginx/apps.d/<name>.conf` (inside the 443 `server`) and the optional `nginx-http.conf` into `/etc/nginx/conf.d/<name>.conf` (`http` context, e.g. `limit_req_zone`), replacing `__PORTA__`. All files go in together: if `nginx -t` fails, every one goes back to its previous content and the provision stops. An `add_header` inside a `location` drops the server's headers, so app locations repeat the site's HSTS line.
- `provision_apps` also installs each app's units (`infra/apps/<name>/*.service`, `*.timer`, named `app-<name>.service` or `<name>-*`) into `/etc/systemd/system`, replacing `__PORTA__` with `PORT` from `app.conf`, and runs `daemon-reload` only when a unit changed. It enables the main service and the timers, starts the main service when it is stopped (a `ConditionPathExists` on the `.venv` keeps it down before the first deploy), and restarts what is running only when its unit or config changed. The installed list goes to `/etc/infra/apps/<name>.units`; when a folder leaves `infra/apps/`, the next provision disables those units and moves the app's nginx snippets to `/var/backups/infra`, keeping code and data. Jobs use `OnFailure=infra-unit-failed@%n.service` to log an error line (`journalctl -t infra -p err`).
- `provision_apps` (`lib/apps.sh`) creates, for each folder in `infra/apps/`, `/opt/apps/<name>/` (backend code) and `/var/www/<name>/` (frontend), owned by `DEPLOY_USER` from `config.env` with mode 755, so `app-<name>` can read its code but not change it. `provision_databases` also creates `/var/backups/sqlite/<name>/` (`app-<name>`, 700) for the pre-deploy backup. Use `sync_dir` for folders: like `sync_file`, it returns 0 only when it changed something. The deploy user has full passwordless sudo (`ubuntu` on OCI images), so there is no sudoers rule; the provision only warns if that stops being true.
- Values reach the provision as `KEY=VALUE` lines on stdin (`lib/input.sh`), each key with its own validation; no value may contain a newline, and no value is ever printed, not even in error messages. `write_env_file` writes them in `EnvironmentFile=` syntax (double quotes with `\ " $ `` ` `` escaped when needed) and keeps the current line when a value comes empty. SMTP credentials go to `/etc/infra/smtp.env` (600), shared by all apps. Each app's non-secret config is versioned in `infra/apps/<name>/app.env` (never `SMTP_*`) and installed to `/etc/infra/apps/<name>.env` (644). A change in either restarts `app-<name>` if it is running. `infra/tests/test-input.sh` covers this in CI.
- Scripts that run as root (via systemd or sudo) are copied to `/usr/local/lib/infra/`, and config goes to `/etc/infra/`. They are not run from `/opt/infra`, because the deploy user can write there.
- `databases.txt` lists one SQLite database per line, and each name must match `^[a-z][a-z0-9-]{1,26}$`. Every entry gets a `app-<name>` user, `/var/lib/sqlite/<name>/app.db`, continuous Litestream replication to OCI Object Storage, and daily local snapshots. Removing a line never deletes data.
- The VM has 1 GB of RAM. Never build or `npm install` on it. Build in CI.
- `uv` is installed with a fixed version and SHA256 from `config.env`, like Litestream. It installs each app's Python (`PYTHON_VERSION` in `infra/apps/<name>/app.conf`, an exact `3.x.y`) as a prebuilt download into `UV_PYTHON_INSTALL_DIR=/opt/uv/python`, outside `/home` because the app units run with `ProtectHome=true`. That version must equal `apps/<name>/backend/.python-version`: `.github/scripts/check-python-version.sh` checks it in `infra.yaml` and `ethos.yaml`, and the `uv` job in `infra.yaml` runs `.github/scripts/test-install-uv.sh` on Ubuntu 24.04 before any provision.
- `.gitattributes` forces LF for `infra/**` and `*.sh`, and for text files in `apps/**` and `packages/**` (`text=auto`, so binaries are left alone). Keep it that way: the repo is often edited on Windows.
- Per-project backends use `templates/app.service.tmpl` and `templates/app-nginx.conf.tmpl` (`__PROJETO__` / `__PORTA__` placeholders, route `/api/<name>/`). Record each port in the table in `infra/README.md`.

## Development guidelines

- Whenever you create or modify a code file, review it yourself right away.
- Make sure there are no unused variables, redundant imports or basic security holes.
- Before calling a task done, use the terminal to run the local checks that validate your changes. This repo has no test suite, so that means `npm run lint` and `npm run build` in `site/` for the website, and the `shellcheck` / `databases.txt` checks above for `infra/`.
- Review as a very strict senior reviewer: let no code smell, concurrency problem or security hole through.
- Mentally run the code with extreme inputs, and make sure exceptions are handled.
