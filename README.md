# imanasomali

Monorepo for [manasomali.com](https://manasomali.com): the personal website, the applications it hosts and the provisioning of the VM that serves them all.

| Folder | What it is | Workflow |
|---|---|---|
| [site/](site/README.md) | Personal website (React 19, React Router, Vite), published at `/` | `deploy.yaml` |
| [apps/](apps/README.md) | Applications served under `/<name>/`, with an API under `/api/<name>/` | `<name>.yaml` |
| [packages/](packages/README.md) | Code shared by the site and the applications | triggers the workflows that use it |
| [infra/](infra/README.md) | Bash provisioning of the Oracle VM: nginx, SQLite databases, backups | `infra.yaml`, `backup-verify.yaml` |

Each area is independent: its own `package.json` and lockfile, no npm workspaces. An application never imports code from the site or from another application; only `packages/` is shared. A push runs only the workflows of the paths it touches, so a push that touches several areas runs several workflows in parallel, in no guaranteed order.

To add an application, follow the convention in [apps/README.md](apps/README.md).
