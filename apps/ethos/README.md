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
cp .env.example .env                       # config local; o .env fica fora do git
uv run --env-file .env alembic upgrade head   # cria ou atualiza o banco (DATABASE_PATH)
uv run --env-file .env uvicorn app.main:app --reload --port 8000 --root-path /api/ethos
```

A API sobe em `http://127.0.0.1:8000`. Como em produção, as rotas ficam na raiz (`http://127.0.0.1:8000/health`) e o prefixo público entra pelo `--root-path`: em produção o nginx tira o `/api/ethos` antes de repassar a request, e em dev o proxy do Vite faz o mesmo. A documentação interativa abre pelo proxy, com o front rodando, em `http://localhost:5174/api/ethos/docs`. Direto na porta 8000 ela não carrega, porque busca o `openapi.json` no caminho com prefixo.

No Git Bash (Windows), o MSYS converte `/api/ethos` num caminho do Windows. Rode o comando no PowerShell ou prefixe com `MSYS_NO_PATHCONV=1`.

Testes e lint:

```bash
uv run pytest                              # com cobertura; falha abaixo de 85%
uv run ruff check                          # lint (--fix corrige o que der)
uv run ruff format                         # formata; --check só confere, como no CI
uv run coverage report --fail-under=100 --include=app/auth/security.py,app/score.py   # depois do pytest
```

Alguns módulos precisam de 100% de cobertura (linhas e ramos). A lista fica na variável `FULL_COVERAGE` do passo "Cobertura de 100% nos módulos críticos" do CI, que confere cada um com o `coverage report` acima.

Os testes não precisam de `.env`: as fixtures de `tests/conftest.py` montam a config com um SQLite em arquivo temporário (`settings`, `make_settings`, `engine`, `db_session`, `app`, `client`, `make_client`, `smtp_server`, `make_smtp_server`). O banco de teste já vem com o schema completo: as migrações rodam uma vez por execução do pytest (`migrated_template`) e cada teste recebe uma cópia (`database`). Para testar migrações, `make_alembic_config(caminho)` devolve a config do Alembic apontando para outro banco.

Dependências entram com `uv add <pacote>` (ou `uv add --dev <pacote>`), que atualiza o `pyproject.toml` e o `uv.lock`. Os dois vão juntos no commit.

### Configuração

Toda a config vem de variáveis de ambiente, lidas e validadas por `app/config.py` na subida. Variável obrigatória faltando ou valor inválido derruba o servidor com a lista do que está errado (sem mostrar os valores). Em produção, a unit `app-ethos` lê `/etc/infra/apps/ethos.env` (versionado em [infra/apps/ethos/app.env](../../infra/apps/ethos/app.env)) e `/etc/infra/smtp.env` (credenciais SMTP, dos secrets do GitHub). Localmente, o `uv run --env-file .env` carrega o `.env`; o app nunca lê o arquivo sozinho.

O `.env.example` já serve para desenvolver: `APP_ENV=dev`, `EMAIL_BACKEND=console` (o email sai no log, sem SMTP) e o banco em `ethos-dev.db`, criado na pasta do backend na primeira conexão. Variável vazia conta como não definida. Para testar o envio de verdade, use `EMAIL_BACKEND=smtp` e preencha as `SMTP_*`. Com `APP_ENV=prod`, o app recusa o email de console e exige `APP_URL` com https.

Os nomes do `.env.example` são exatamente os do `infra/apps/ethos/app.env` mais os do `smtp.env` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`), e um teste confere. Variável nova entra nos três lugares: `app/config.py`, `.env.example` e `infra/apps/ethos/app.env` (ou no `smtp.env`, se for credencial). A mudança no `app.env` vai num PR anterior ao do código que a exige.

### Banco, erros e logs

- `app/db.py`: engine síncrona do SQLAlchemy, com `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON` e `secure_delete=ON` em toda conexão nova. Endpoints que usam o banco são `def` (nunca `async def`) e recebem a sessão do request por `SessionDep`. Toda escrita vai dentro de `with write_transaction(session):`, que abre a transação com `BEGIN IMMEDIATE`; escrita do ORM fora dele é recusada.
- `app/models.py`: as tabelas (SQLAlchemy 2). Datas sempre em UTC: as colunas recusam `datetime` sem fuso e devolvem com `tzinfo=UTC`; compare com parâmetros, nunca com `datetime('now')` do SQLite. Dinheiro em centavos inteiros (`*_cents`). Enums e tamanhos fixos do plano têm `CHECK` no banco, com os valores nas classes `StrEnum` do módulo (`GoalType`, `HabitColor`...). Apagar um usuário apaga em cascata o que é dele (sessões, códigos, hábitos com tudo o que está neles, participações, convites, alertas) e deixa `NULL` a autoria em dados de outras pessoas (`marks.user_id`, `audit_log.user_id`, `banners.created_by`).
- `app/errors.py`: catálogo de códigos (`ErrorCode`). Toda resposta de erro sai como `{"error": "<codigo>", "field": "<campo>" | null}`, inclusive a validação do FastAPI (422). Erro de regra: `raise ApiError(409, ErrorCode.CONFLICT, field="email")`. Código novo também ganha tradução no front.
- `app/logs.py`: uma linha por request (método, rota declarada, status e duração), `INFO` em produção. Nunca IP, query string, corpo, headers nem cookies. Nos módulos, use `logging.getLogger(__name__)` e não logue email, código, token nem cookie.

### Migrações

O schema é criado e alterado só pelo [Alembic](https://alembic.sqlalchemy.org/), com `alembic.ini` e `migrations/` na pasta do backend. O banco vem da variável `DATABASE_PATH`, a mesma do app; nada de caminho fixo no `alembic.ini`. Rode na pasta do backend:

```bash
uv run --env-file .env alembic upgrade head      # aplica as migrações que faltam
uv run --env-file .env alembic current           # revisão em que o banco está
uv run --env-file .env alembic downgrade -1      # desfaz a última
uv run --env-file .env alembic check             # modelos e banco batem? (precisa estar em head)
```

- Cada execução roda numa transação só, com `BEGIN IMMEDIATE`: ou aplica todas as migrações pedidas ou nenhuma. As chaves estrangeiras ficam desligadas durante a migração (senão recriar uma tabela no modo batch dispararia os `ON DELETE`) e são conferidas com `PRAGMA foreign_key_check` antes do commit.
- Só modo online: `--sql` é recusado.
- Migração nova: `uv run alembic revision --rev-id 0002 -m "descricao curta"` cria `migrations/versions/0002_descricao_curta.py`. Escreva o `upgrade` e o `downgrade` à mão (o autogenerate erra em SQLite), com `op.batch_alter_table` para alterar tabela e nomes completos nas constraints (`op.f("ck_habits_...")`, conforme a `NAMING_CONVENTION` de `app/models.py`). Não importe `app.models` na migração. Mude `app/models.py` no mesmo PR.
- `tests/test_migrations.py` sobe e desce as migrações num banco vazio e compara o banco migrado com os modelos (colunas, tipos, `CHECK`, chaves estrangeiras com o `ON DELETE`, índices e `AUTOINCREMENT`). Se ele falhar, a migração e os modelos divergiram.

### Email

O pacote `app/mail/` tem tudo o que o app envia por email:

- `catalog.py`: o catálogo fechado, um tipo por email com os dados que o texto usa (`LoginCode`, `DeleteCode`, `Invite`, `Alert` com `GoalAlert`/`CostAlert`, `AccountDeleted`, `AccessLost`, `HabitDeleted`, `EmailChangedOld`, `EmailChangedNew`, `SendCapReached`). Não tem email em massa nem link de descadastro. O módulo não lê o banco: quem chama passa destinatário, idioma e dados.
- `templates.py`: os textos em pt e en, em texto puro e HTML simples. Todo texto é escapado no HTML (nome de hábito com `<script>` sai como texto). O assunto é fixo por tipo e idioma, sem código nem dado do usuário. Os links saem do `APP_URL`; a tela de alertas fica em `APP_URL` + `/habits/{id}/alerts`.
- `language.py`: `pick_locale(users.locale, Accept-Language)`, com `en` quando nada bate.
- `backends.py`: `SmtpBackend` (STARTTLS obrigatório antes do login, certificado verificado; sem STARTTLS nada sai) e `ConsoleBackend`, que escreve destinatário, assunto e texto (com o código) no stderr para quem desenvolve entrar sem SMTP. A config recusa `console` fora de `APP_ENV=dev`.
- `sender.py`: `Mailer`, criado na subida do app (`MailerDep` nos endpoints), e `schedule_email(background_tasks, mailer, to, locale, email)`, chamado depois que o `write_transaction` fechou. O envio roda depois da resposta; se o endpoint levantar exceção, nada sai. Fora de request (CLI), use `mailer.send(...)`, que devolve `False` em falha.

Falha de envio nunca derruba o request: vira uma linha de erro com o tipo do email e do erro (`email login_code não enviado (SMTPNotSupportedError)`), sem destinatário, código nem corpo. Email novo entra no `catalog.py` e nos textos pt e en do `templates.py`; um teste confere que os dois idiomas têm as mesmas chaves e que todo o catálogo renderiza.

Nos testes, a fixture `smtp_server` sobe um servidor SMTP falso (`tests/fake_smtp.py`, aiosmtpd) com STARTTLS e login obrigatórios, como o provedor. Para o app enviar por ele: `create_app(settings, mail_backend=smtp_server.backend())`; os emails recebidos ficam em `smtp_server.received`.

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

O workflow [ethos.yaml](../../.github/workflows/ethos.yaml) roda em PRs e em push na `main` que tocam `apps/ethos/**`, `packages/**`, o próprio workflow ou os arquivos de infra que os testes conferem (`infra/apps/ethos/app.conf`, `infra/apps/ethos/app.env` e `infra/provision.sh`). Por enquanto só faz checagens, sem deploy:

- backend: `uv lock --check`, `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest --cov` e 100% de cobertura nos módulos de `FULL_COVERAGE`;
- frontend: `npm ci`, `npm run lint`, `npm run build` e `npm test`.
