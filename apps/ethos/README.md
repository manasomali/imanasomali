# ethos

Aplicação de hábitos servida em `manasomali.com/ethos/`, com API em `manasomali.com/api/ethos/`. Segue a convenção de [apps/README.md](../README.md).

| Pasta | O quê |
|---|---|
| `backend/` | API em Python + FastAPI, gerenciada pelo [uv](https://docs.astral.sh/uv/) |
| `frontend/` | React + Vite, servido em `/ethos/` |

Back e front são independentes: cada um tem as suas dependências e o seu lockfile (`uv.lock` e `package-lock.json`). Nada aqui importa código do site; o que for compartilhado vem de `packages/`.

## Requisitos

- [uv](https://docs.astral.sh/uv/getting-started/installation/). Ele instala sozinho a versão do Python fixada em `backend/.python-version`.
- Node 22 e npm.

## Backend

```bash
cd apps/ethos/backend
uv sync                                    # cria a .venv com as dependências de dev
uv run uvicorn app.main:app --reload --port 8000 --root-path /api/ethos
```

A API sobe em `http://127.0.0.1:8000`. Como em produção, as rotas ficam na raiz (`http://127.0.0.1:8000/health`) e o prefixo público entra pelo `--root-path`: em produção o nginx tira o `/api/ethos` antes de repassar a request, e em dev o proxy do Vite faz o mesmo. A documentação interativa abre pelo proxy, com o front rodando, em `http://localhost:5174/api/ethos/docs`. Direto na porta 8000 ela não carrega, porque busca o `openapi.json` no caminho com prefixo.

No Git Bash (Windows), o MSYS converte `/api/ethos` num caminho do Windows. Rode o comando no PowerShell ou prefixe com `MSYS_NO_PATHCONV=1`.

Testes e lint:

```bash
uv run pytest                              # com cobertura; falha abaixo de 85%
uv run ruff check                          # lint (--fix corrige o que der)
uv run ruff format                         # formata; --check só confere, como no CI
uv run coverage report --fail-under=100 --include=app/auth/security.py   # depois do pytest
```

Alguns módulos precisam de 100% de cobertura (linhas e ramos). A lista fica na variável `FULL_COVERAGE` do passo "Cobertura de 100% nos módulos críticos" do CI, que confere cada um com o `coverage report` acima.

Dependências entram com `uv add <pacote>` (ou `uv add --dev <pacote>`), que atualiza o `pyproject.toml` e o `uv.lock`. Os dois vão juntos no commit.

## Frontend

```bash
cd apps/ethos/frontend
npm ci
npm run dev                                # http://localhost:5174/ethos/
```

O dev server usa a porta 5174 (o site usa a 5173) e falha se ela estiver ocupada. Também dá para subir pela entrada `ethos` do `.claude/launch.json`. Em dev, o Vite repassa `/api/ethos/*` para o backend em `http://127.0.0.1:8000`, sem o prefixo, então suba o backend antes de usar telas que chamam a API.

```bash
npm run lint                               # ESLint com jsx-a11y; qualquer aviso falha
npm test                                   # vitest, roda uma vez e sai
npm run build                              # gera dist/
npm run preview                            # serve o dist/ localmente
```

Os testes rodam no jsdom, com Testing Library. Todo teste de tela também confere acessibilidade com `vitest-axe`, usando o `axe` de `src/test/axe.js`:

```jsx
expect(await axe(container)).toHaveNoViolations();
```

## CI

O workflow [ethos.yaml](../../.github/workflows/ethos.yaml) roda em PRs e em push na `main` que tocam `apps/ethos/**`, `packages/**` ou o próprio workflow. Por enquanto só faz checagens, sem deploy:

- backend: `uv lock --check`, `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest --cov` e 100% de cobertura nos módulos de `FULL_COVERAGE`;
- frontend: `npm ci`, `npm run lint`, `npm run build` e `npm test`.
