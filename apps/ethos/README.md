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
uv run coverage report --fail-under=100 --include=app/audit.py,app/auth/security.py,app/auth/service.py,app/retention.py,app/score.py   # depois do pytest
```

Alguns módulos precisam de 100% de cobertura (linhas e ramos). A lista fica na variável `FULL_COVERAGE` do passo "Cobertura de 100% nos módulos críticos" do CI, que confere cada um com o `coverage report` acima.

Os testes não precisam de `.env`: as fixtures de `tests/conftest.py` montam a config com um SQLite em arquivo temporário (`settings`, `make_settings`, `engine`, `db_session`, `app`, `client`, `make_client`, `smtp_server`, `make_smtp_server`, `outbox`). O banco de teste já vem com o schema completo: as migrações rodam uma vez por execução do pytest (`migrated_template`) e cada teste recebe uma cópia (`database`). Para testar migrações, `make_alembic_config(caminho)` devolve a config do Alembic apontando para outro banco. `tests/factories.py` tem `new_user`, `new_habit`, `save` e `count` para montar dados.

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

### Auditoria e retenção

- `app/audit.py`: `audit.record(session, AuditEvent.X, user_id=..., ip=..., habit_id=..., details={...})` grava um evento no `audit_log` dentro do `write_transaction` que faz a mudança (fora dele, `RuntimeError`). Não faz commit: um rollback desfaz a mudança e o evento juntos. `created_at` é a hora atual.
- Os eventos são uma lista fechada (`AuditEvent`); evento fora dela levanta `AuditError`. Evento novo entra no enum e, se for de auth, em `AUTH_EVENTS`, que define a retenção.
- `details` é um dict JSON pequeno (até 16 KB, 8 níveis). Valor que não é JSON (datetime, set, bytes, NaN...) e qualquer chave cujo nome contém `code`, `token`, `cookie`, `password`, `secret` etc., em qualquer nível, são recusados. Para registrar a mudança de um campo com esse nome (a sigla `habits.code`), o nome vai como valor: `{"changes": [{"field": "code", "old": "AB", "new": "CD"}]}`. O IP é validado e normalizado.
- `audit_log.habit_id` tem `ON DELETE CASCADE`: apagar o hábito apaga a auditoria dele. O evento que precisa sobreviver ao hábito (`habit_deleted`) vai com `habit_id=None` e o id no `details`; `account_deleted` também leva o id da conta no `details`.
- `app/retention.py`: a retenção do plano, aplicada pelo `cleanup` (abaixo). Eventos de auth (`AUTH_EVENTS`) saem depois de 90 dias; o IP de todas as linhas do `audit_log` e de `sessions` vira `NULL` depois de 90 dias (pelo `created_at`); sessões vencidas saem; códigos de login vencidos saem 1 dia depois de criados, porque os limites de envio por hora e por dia contam as linhas de `login_codes`. A auditoria de hábitos, marcações, compartilhamento, conta e admin não é apagada (só o IP). `delete_expired_sessions` e `delete_expired_login_codes` servem também para a limpeza ao criar um código.

### Login por código

Cadastro e login são o mesmo fluxo, sem senha: `POST /auth/code/request` com `{email}` manda um código de 6 dígitos por email, e `POST /auth/code/verify` com `{email, code, timezone, locale}` confere o código, cria a conta no primeiro acesso e abre a sessão.

- `app/auth/service.py`: as regras (100% de cobertura). Email salvo com strip + lower (`normalize_email`). O código vale 10 minutos, uma vez só, por no máximo 5 tentativas (contadas antes de comparar, num BEGIN IMMEDIATE, e gravadas mesmo quando a resposta é erro); pedir outro invalida o anterior. Limite por email de 1 código por minuto e 5 por hora e teto global `MAX_CODE_EMAILS_PER_HOUR`/`_PER_DAY`, todos contados pelas linhas de `login_codes`. Ao bater o teto, um aviso vai para o `SUPPORT_EMAIL`, no máximo 1 por hora: o último aviso é o evento `send_cap_reached` do `audit_log`, lido e gravado na mesma transação. Conta nova nasce com `TERMS_VERSION` aceita e com o fuso e o idioma do navegador; conta existente ignora os dois. `create_session` e `SESSION_LIFETIME` (60 dias) servem às próximas tasks.
- `app/auth/routes.py`: os endpoints. O `request` responde sempre 202 com o mesmo corpo e os mesmos headers (com conta, sem conta, conta inativa, que não recebe email) e 429 `rate_limited` igual para qualquer email. O `verify` responde 400 `invalid_code` para qualquer código recusado e 422 `invalid_timezone` para fuso desconhecido no primeiro acesso.
- `app/auth/cookies.py`: o cookie `__Host-ethos_session` (`HttpOnly; Secure; SameSite=Lax; Path=/`, sem `Domain`), com o token da sessão. No banco fica só o sha256 do token.
- `app/terms.py`: `TERMS_VERSION`, a versão atual dos termos. Fica no código (não no ambiente) e muda no mesmo PR dos textos.
- `app/request_info.py`: IP e User-Agent do cliente para o `audit_log` e `sessions`. O IP é o `request.client.host`: em produção, o uvicorn (`--proxy-headers --forwarded-allow-ips=127.0.0.1`) já o tirou do `X-Forwarded-For` que o nginx monta, pegando o endereço que o nginx viu, e não o que o cliente escreveu no header.

Nos testes, a fixture `outbox` é um backend de email em memória (`create_app(settings, mail_backend=outbox)`), e `tests/auth_helpers.py` tem `login(client, outbox, email)`, que devolve o token da sessão, além de `code_in(email)` e `session_token(response)`. O cookie é `Secure`: o TestClient em `http://testserver` não o manda de volta sozinho.

### Comandos de operação (CLI)

```bash
uv run --env-file .env python -m app.cli --help      # lista os comandos
uv run --env-file .env python -m app.cli cleanup     # aplica a retenção de dados
uv run --env-file .env python -m app.cli create-admin voce@example.com   # torna a conta admin
```

O CLI lê a mesma config do servidor (variáveis de ambiente) e abre o banco de `DATABASE_PATH`, que precisa existir e estar migrado. Em produção roda como `app-ethos`. Código de saída 0 em sucesso, 1 em erro (a mensagem sai no stderr com `erro:`, sem stack trace nem valores) e 2 em uso errado.

| Comando | O quê |
|---|---|
| `cleanup` | Retenção de dados (ver acima), numa transação só. Imprime quantas linhas mudou em cada passo. Pode rodar quantas vezes quiser: a segunda seguida não muda nada. No plano, roda de hora em hora pelo `ethos-alerts.timer`, depois dos alertas. |
| `create-admin <email>` | Liga o `is_admin` de uma conta que já existe e grava `admin_created` no `audit_log` (`user_id` = a conta promovida, `details` = `{"via": "cli"}`), numa transação só. É o único jeito de criar admin: não existe endpoint para isso. O email é normalizado como no login (espaços e maiúsculas não importam). A saída mostra o id da conta, nunca o email. Email sem conta: erro e nada muda (a pessoa precisa entrar no app uma vez antes, o que cria a conta). Conta bloqueada (`is_active=false`): erro e nada muda; desbloqueie antes. Conta que já é admin: avisa, sai com 0 e não grava nada. |

Na VM, o comando roda com o mesmo usuário, o mesmo ambiente e a mesma `.venv` da unit `app-ethos` ([infra/apps/ethos/app-ethos.service](../../infra/apps/ethos/app-ethos.service)):

```bash
sudo systemd-run --quiet --pipe --wait --collect \
  --uid=app-ethos --gid=app-ethos \
  --working-directory=/opt/apps/ethos \
  -p EnvironmentFile=/etc/infra/smtp.env \
  -p EnvironmentFile=/etc/infra/apps/ethos.env \
  /opt/apps/ethos/.venv/bin/python -m app.cli create-admin voce@example.com
```

`sudo -u app-ethos` sozinho não basta: o `/etc/infra/smtp.env` é `0600` do root, e com `EMAIL_BACKEND=smtp` a config exige as `SMTP_*`. Pelo `systemd-run`, o systemd lê os dois `EnvironmentFile=` como root, como faz com a unit, e o comando roda como `app-ethos`, que pode escrever em `/var/lib/sqlite/ethos/app.db`. O `--wait` devolve o código de saída do comando. O mesmo vale para qualquer outro comando do CLI (troque `create-admin voce@example.com`). O email digitado fica no histórico do shell e no log do sudo da VM.

Comando novo: um handler `(context: CommandContext, args) -> int` em `app/cli.py`, registrado em `build_parser`. Erro esperado é `raise CommandError("mensagem")`; o docstring do módulo tem o passo a passo.

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
