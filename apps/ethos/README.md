# ethos

Aplicação de hábitos servida em `manasomali.com/ethos/`, com API em `manasomali.com/api/ethos/`. Segue a convenção de [apps/README.md](../README.md).

| Pasta | O quê |
|---|---|
| `backend/` | API em Python + FastAPI, gerenciada pelo [uv](https://docs.astral.sh/uv/) |
| `frontend/` | React + Vite, servido em `/ethos/` |

Back e front são independentes: cada um tem as suas dependências e o seu lockfile (`uv.lock` e `package-lock.json`). Nada aqui importa código do site; o que for compartilhado vem de `packages/`, como os tokens de design e os scripts do deploy ([packages/deploy/](../../packages/deploy/README.md), ver [Deploy](#deploy)).

## Requisitos

- [uv](https://docs.astral.sh/uv/getting-started/installation/). Ele instala sozinho a versão do Python fixada em `backend/.python-version`.
- Node 22 e npm.

## Backend

```bash
cd apps/ethos/backend
uv sync                                    # cria a .venv com as dependências de dev
cp .env.example .env                       # config local; o .env fica fora do git
uv run --env-file .env alembic upgrade head   # cria ou atualiza o banco (DATABASE_PATH)
uv run --env-file .env python -m app.cli seed # opcional: dados de exemplo das contas do seed do imago
uv run --env-file .env uvicorn app.main:app --reload --port 3001 --root-path /api/ethos
```

A API sobe em `http://127.0.0.1:3001`, a porta de produção. Como em produção, as rotas ficam na raiz (`http://127.0.0.1:3001/health`) e o prefixo público entra pelo `--root-path`: o nginx tira o `/api/ethos` antes de repassar a request.

O login é do [imago](../imago/README.md): o ethos só sabe quem é o usuário pelos headers `X-User-*` que o nginx põe depois de perguntar ao imago (ver "Identidade"). Para usar o app em dev, suba também o backend do imago (porta 3003) e o nginx de dev ([apps/imago/dev/README.md](../imago/dev/README.md)), e abra `http://localhost:8080/ethos/`. O `INTERNAL_API_TOKEN` do `.env` do ethos precisa ser o mesmo do `ethos:` no `IMAGO_APP_TOKENS` do `.env` do imago. A documentação interativa abre pelo nginx de dev, em `http://localhost:8080/api/ethos/docs`; direto na porta 3001 ela não carrega, porque busca o `openapi.json` no caminho com prefixo. Ela (`/docs`, `/redoc` e o schema em `/openapi.json`) só existe com `APP_ENV=dev`, como no `.env.example`: fora de dev os três respondem 404, porque o schema listaria para qualquer um todas as rotas, inclusive as de admin.

No Git Bash (Windows), o MSYS converte `/api/ethos` num caminho do Windows. Rode o comando no PowerShell ou prefixe com `MSYS_NO_PATHCONV=1`.

Testes e lint:

```bash
uv run pytest                              # com cobertura; falha abaixo de 85%
uv run ruff check                          # lint (--fix corrige o que der)
uv run ruff format                         # formata; --check só confere, como no CI
uv run coverage report --fail-under=100 --include=app/admin/accounts.py,app/admin/banners.py,app/alerts/service.py,app/audit.py,app/habits/access.py,app/habits/scoring.py,app/habits/service.py,app/history/service.py,app/identity.py,app/imago_client.py,app/internal/reapply.py,app/internal/service.py,app/marks/schemas.py,app/marks/service.py,app/pagination.py,app/progress/service.py,app/score.py,app/sharing/quota.py,app/sharing/service.py   # depois do pytest
```

Alguns módulos precisam de 100% de cobertura (linhas e ramos). A lista fica na variável `FULL_COVERAGE` do passo "Cobertura de 100% nos módulos críticos" do CI, que confere cada um com o `coverage report` acima.

Os testes não precisam de `.env` nem de um imago rodando: as fixtures de `tests/conftest.py` montam a config com um SQLite em arquivo temporário (`settings`, `make_settings`, `engine`, `db_session`, `imago`, `app`, `client`, `make_client`, `make_account`, `selects`, `smtp_server`). O banco de teste já vem com o schema completo: as migrações rodam uma vez por execução do pytest (`migrated_template`) e cada teste recebe uma cópia (`database`). Para testar migrações, `make_alembic_config(caminho)` devolve a config do Alembic apontando para outro banco. `tests/factories.py` tem `new_user` (uma linha de `app_users`, com ids a partir de 1001), `new_habit`, `new_member`, `new_invite`, `new_mark`, `new_pause`, `new_alert`, `save` e `count` para montar dados.

Dependências entram com `uv add <pacote>` (ou `uv add --dev <pacote>`), que atualiza o `pyproject.toml` e o `uv.lock`. Os dois vão juntos no commit.

### Configuração

Toda a config vem de variáveis de ambiente, lidas e validadas por `app/config.py` na subida. Variável obrigatória faltando ou valor inválido derruba o servidor com a lista do que está errado (sem mostrar os valores). Em produção, a unit `app-ethos` lê `/etc/infra/apps/ethos.env` (versionado em [infra/apps/ethos/app.env](../../infra/apps/ethos/app.env)) e `/etc/infra/internal/ethos.env` (o `INTERNAL_API_TOKEN`, gerado pelo provision na VM, `0600` do root). Localmente, o `uv run --env-file .env` carrega o `.env`; o app nunca lê o arquivo sozinho.

- `IMAGO_INTERNAL_URL`: a origem da API interna do imago (`http://127.0.0.1:3003`), só esquema (http ou https), host e porta, sem caminho, query nem usuário.
- `INTERNAL_API_TOKEN`: o token Bearer do ethos na API interna, de 32 a 256 caracteres base64url (`A-Z`, `a-z`, `0-9`, `-` e `_`). O mesmo valor vale nos dois sentidos: o ethos o manda nas chamadas ao imago e o confere nas chamadas do imago a `/internal/*`.

O `.env.example` já serve para desenvolver: `APP_ENV=dev`, o banco em `ethos-dev.db` (criado na pasta do backend na primeira conexão), o imago em `127.0.0.1:3003` e um token de dev. Variável vazia conta como não definida. Com `APP_ENV=prod`, o app exige `APP_URL` com https.

Os nomes do `.env.example` são exatamente os do `infra/apps/ethos/app.env` mais o `INTERNAL_API_TOKEN`, e um teste confere (`tests/test_env_files.py`). As variáveis do login próprio de antes do imago (`EMAIL_BACKEND`, `MAIL_FROM`, `SUPPORT_EMAIL`, `MAX_CODE_EMAILS_PER_HOUR`, `MAX_CODE_EMAILS_PER_DAY` e as `SMTP_*` do `smtp.env`) são ignoradas: o PR de infra B da ETH-64 as tira do `app.env` e das units, e até lá o teste as tolera no `app.env` (`LEGACY_ENV_VARS`, que sai num deploy seguinte). Variável nova entra nos três lugares: `app/config.py`, `.env.example` e `infra/apps/ethos/app.env` (segredo vai no `internal/ethos.env`, gerado na VM). A mudança no `app.env` vai num PR anterior ao do código que a exige.

### Banco, erros e logs

- `app/db.py`: engine síncrona do SQLAlchemy, com `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON` e `secure_delete=ON` em toda conexão nova. Endpoints que usam o banco são `def` (nunca `async def`) e recebem a sessão do request por `SessionDep`. Toda escrita vai dentro de `with write_transaction(session):`, que abre a transação com `BEGIN IMMEDIATE`; escrita do ORM fora dele é recusada.
- `app/models.py`: as tabelas (SQLAlchemy 2). Datas sempre em UTC: as colunas recusam `datetime` sem fuso e devolvem com `tzinfo=UTC`; compare com parâmetros, nunca com `datetime('now')` do SQLite. Dinheiro em centavos inteiros (`*_cents`). Enums e tamanhos fixos do plano têm `CHECK` no banco, com os valores nas classes `StrEnum` do módulo (`GoalType`, `HabitColor`...). `app_users` (`AppUser`) é a cópia local das contas do imago (ver "Identidade"), com o mesmo id (sem AUTOINCREMENT). Apagar uma linha de `app_users` apaga em cascata o que é dela (hábitos com tudo o que está neles, participações, alertas) e deixa `NULL` a autoria em dados de outras pessoas (`marks.user_id`, `audit_log.user_id`, `banners.created_by`). `sessions`, `login_codes` e `audit_log.ip` são do login de antes do imago: ficam vazias (a migração 0005 as esvaziou), sem uso no código, e saem numa migração seguinte.
- `app/errors.py`: catálogo de códigos (`ErrorCode`). Toda resposta de erro sai como `{"error": "<codigo>", "field": "<campo>" | null}`, inclusive a validação do FastAPI (422). Erro de regra: `raise ApiError(409, ErrorCode.CONFLICT, field="email")`. Código novo também ganha tradução no front.
- `app/logs.py`: uma linha por request (método, rota declarada, status e duração), `INFO` em produção. Nunca IP, query string, corpo, headers nem cookies. Nos módulos, use `logging.getLogger(__name__)` e não logue email, token, cookie nem valor de header `X-User-*` (no máximo o nome do header e o id numérico do usuário).

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
- **0005 (`app_users`, ETH-64)**: a passagem do login para o imago. Renomeia `users` para `app_users` e `id` para `user_id` (os ids continuam: são os mesmos do imago, que importou as contas pelo `export-users` antes deste deploy) e recria a tabela no formato novo (`user_id`, `email`, `locale`, `timezone`, `first_seen_at` = o antigo `created_at`, `updated_at`), sem `is_active`, `is_admin`, termos, último login nem o `UNIQUE` do email, que agora são do imago. Tira a chave estrangeira de `habit_invites.invited_user_id` (o convidado pode ter conta no imago sem nunca ter aberto o ethos). Apaga do `audit_log` os eventos de login e de conta (`code_requested`, `login`, `login_failed`, `logout`, `logout_all`, `delete_code_requested`, `send_cap_reached`, `terms_accepted`, `profile_updated`, `account_deleted`, `admin_created`, `user_blocked`, `user_unblocked`, `email_changed`) e todos os IPs, e esvazia `sessions` e `login_codes`. As chaves estrangeiras que apontam para `app_users` mantêm o nome antigo (`fk_<tabela>_<coluna>_users`): o SQLite não renomeia constraint sem recriar cada tabela. **Não é aditiva** (a exceção da ETH-64 à regra do deploy): o código de antes dela não funciona com o banco migrado, e o `downgrade` é recusado enquanto houver conta em `app_users` (a mensagem diz o que fazer). Voltar para antes dela é restaurar o `pre-deploy-<sha>.db` do deploy que a aplicou (ver "Rollback"). O teste dela roda num banco populado (contas, hábitos, convites com e sem conta, auditoria com IP) e confere ids, chaves estrangeiras (`PRAGMA foreign_key_check` vazio) e que nenhum IP sobra.

### Auditoria

- `app/audit.py`: `audit.record(session, AuditEvent.X, user_id=..., habit_id=..., details={...})` grava um evento no `audit_log` dentro do `write_transaction` que faz a mudança (fora dele, `RuntimeError`). Não faz commit: um rollback desfaz a mudança e o evento juntos. `created_at` é a hora atual. Sem IP: a auditoria do ethos não guarda o IP de ninguém.
- Os eventos são uma lista fechada (`AuditEvent`: hábitos, marcações, compartilhamento, `alert_updated`, `admin_viewed_habits` e banners); evento fora dela levanta `AuditError`. Os de login, sessão, termos e conta são do imago.
- `details` é um dict JSON pequeno (até 16 KB, 8 níveis). Valor que não é JSON (datetime, set, bytes, NaN...) e qualquer chave cujo nome contém `code`, `token`, `cookie`, `password`, `secret` etc., em qualquer nível, são recusados. Para registrar a mudança de um campo com esse nome (a sigla `habits.code`), o nome vai como valor: `{"changes": [{"field": "code", "old": "AB", "new": "CD"}]}`.
- `audit_log.mark_id` é uma coluna gerada (VIRTUAL, migração 0002) com o `details.mark_id` dos eventos de marcação, indexada para o histórico de uma marcação. O app nunca a grava: o SQLite a calcula do `details`.
- `habits.color` (migração 0004): o `CHECK` aceita um nome da paleta (`HabitColor`) ou `#rrggbb` em minúsculas (`CUSTOM_COLOR_GLOB`). A migração só relaxa o `CHECK` (recria a tabela no modo batch, guardando o AUTOINCREMENT e o contador do `sqlite_sequence`). O `downgrade` é recusado enquanto houver hábito com cor própria, com a mensagem de como trocar as cores antes; nada muda até lá.
- `alerts.last_evaluated_at` (migração 0003) guarda a última avaliação de cada alerta pelo `run-alerts` (ou o último salvar da configuração), para cada ocorrência da hora escolhida ser avaliada uma vez só, com ou sem email (veja "Alertas").
- `audit_log.habit_id` tem `ON DELETE CASCADE`: apagar o hábito apaga a auditoria dele. O evento que precisa sobreviver ao hábito (`habit_deleted`) vai com `habit_id=None` e o id no `details`.
- Retenção: o ethos não apaga auditoria por prazo. O `cleanup` (eventos de login, IPs, sessões e códigos vencidos) saiu com o login próprio: isso agora é do imago. A auditoria de hábitos, marcações, compartilhamento e admin fica até o hábito ou a conta saírem.

### Identidade (login pelo imago)

O login, a conta, os termos e as sessões são do [imago](../imago/README.md), a conta única do manasomali.com (ETH-60, ETH-64). O ethos não tem tela nem endpoint de login: em cada request de `/api/ethos/`, o nginx pergunta ao imago quem é a pessoa (`auth_request`) e repassa a resposta nos headers `X-User-Id`, `X-User-Email`, `X-User-Locale`, `X-User-Timezone` e `X-User-Admin` (`1`, só para admin). O nginx sempre define os cinco, o que apaga qualquer `X-User-*` mandado pelo navegador; isso só é seguro porque o ethos escuta em 127.0.0.1 e só o nginx chega nele. Sem sessão válida, conta ativa e termos aceitos, o imago não manda nenhum.

- `app/identity.py` (100% de cobertura): `CurrentUser` é o `Identity` do request (id, email, idioma, fuso e `is_admin`, lidos dos headers dele: admin e fuso valem na hora) e `AdminUser` exige `X-User-Admin: 1` (senão 403 `forbidden`). Sem os headers, 401 `not_authenticated`. Header malformado (id fora de 1 a 2^53 - 1, email que não é ASCII minúsculo, idioma fora de `pt`/`en`, fuso que não existe, admin diferente de `1`, header repetido, id sem os outros): também 401, com um aviso no log que cita o nome do header, nunca o valor. As rotas públicas (`/health`, `/banners/active`) não pedem login.
- `app_users`: a cada request com login, a linha da pessoa é criada (primeiro acesso) ou atualizada quando email, idioma ou fuso mudaram; senão nada é gravado. A conferência é uma leitura, e a escrita relê a linha dentro do `BEGIN IMMEDIATE`: dois requests ao mesmo tempo no primeiro acesso não colidem. O imago também avisa as mudanças pela API interna (abaixo), para o email e o fuso valerem nos alertas mesmo sem a pessoa abrir o ethos.
- `GET /me`: `{id, email, locale, timezone, is_admin}`, dos headers. Email, idioma e fuso mudam na conta do imago (`/imago/`).
- CSRF: o `RequestGuardMiddleware` recusa com 403 `forbidden` toda request que não seja GET, HEAD ou OPTIONS sem exatamente um header `Origin` igual à origem do `APP_URL` (`settings.app_origin`: esquema + host + porta se não for a padrão), antes de ler o corpo. A exceção é `/internal/*` (abaixo). Nos testes, o `make_client` manda esse `Origin` em todo request; `make_client(app, origin=False)` não manda.
- Cookie antigo: quem ainda manda o `__Host-ethos_session` (o login de antes do imago) recebe o mesmo cookie com `Max-Age=0`, que o apaga (`LegacySessionCookieMiddleware`), em qualquer resposta.

Nos testes, `make_account(email, admin=False)` salva a pessoa em `app_users`, a registra no imago falso e devolve `Account(user, headers)`, com os headers `X-User-*` (`identity_headers(user, admin=...)` em `tests/identity_helpers.py`).

### API interna e imago

`app/imago_client.py` (100% de cobertura) fala com a API interna do imago (`IMAGO_INTERNAL_URL`, direto em 127.0.0.1, com `Authorization: Bearer <INTERNAL_API_TOKEN>`, timeout de 5 s, sem seguir redirect nem ler proxy do ambiente):

- `send_mail(user_id, kind, subject=..., text=..., html=...)` → `POST /internal/mail`: o imago põe o email atual da pessoa e envia. 202 aceito (`ACCEPTED`); 204 destinatário inativo ou em exclusão (`SKIPPED`); 429 teto de envio compartilhado (`REFUSED`, aviso no log); outro status ou erro de rede (`FAILED`). Nunca levanta exceção; o log tem só o tipo do email e o status ou o tipo do erro, nunca o destinatário.
- `lookup_user(email)` → `POST /internal/users/lookup`: `ImagoUser(id, locale)` de uma conta ativa, ou `None` (404). Falha (rede, status inesperado, corpo inválido) levanta `ImagoUnavailableError`.

`app/internal/` é a API que o imago chama, só direto em `127.0.0.1:3001` (o nginx responde 404 para `/api/ethos/internal/`). Toda rota exige `Authorization: Bearer <INTERNAL_API_TOKEN>`, comparado com `hmac.compare_digest` no `RequestGuardMiddleware`, antes de ler o corpo, e de novo na dependência do router (sem ele ou errado: 401 `unauthorized`, com `WWW-Authenticate: Bearer`), sem checagem de `Origin`:

| Endpoint | O quê |
|---|---|
| `POST /internal/users/{id}/refresh` | Corpo `{email, locale, timezone}`. Atualiza a linha de `app_users` se algo mudou; id desconhecido não cria linha (ela nasce no primeiro request da pessoa). 200 `{"status": "ok"}`; valor inválido, 422. |
| `POST /internal/users/{id}/delete` | Apaga os dados da pessoa no ethos (ver "Exclusão de conta"). 200 `{"status": "deleted"}`, também para id desconhecido e numa segunda chamada. |

`id` de 1 a 2^53 - 1 (fora disso, 422). Nos testes, a fixture `imago` (`tests/fake_imago.py`) é o imago falso, ligado ao app por um `MockTransport` do httpx2: `imago.add_account(id, email, locale)` para o lookup, `mail_status`, `lookup_status` e `error` para simular respostas e falhas, e `imago.mails`/`mails_to(id)` com os emails aceitos.

### Hábitos

O pacote `app/habits/` tem a configuração dos hábitos e o acesso a eles:

- `access.py` (100% de cobertura): `get_habit_access(session, habit_id, user_id)` devolve o hábito e o papel de quem pede (`owner`, `editor` ou `viewer`) ou 404 `not_found`, igual para id que não existe e para hábito de outra pessoa (a API nunca revela que ele existe). `require_owner(access)` dá 403 `forbidden` para editor e viewer. `require_writable(access)` dá 409 `habit_archived` em hábito arquivado, que é só leitura (confira o papel antes: quem não pode escrever recebe 403). `HabitId` é o id no caminho (1 até o maior inteiro do SQLite; fora disso, 422).
- `scoring.py` (100% de cobertura): converte os modelos para as dataclasses do `score.py` e lê marcações e pausas em lote. `evaluate_habits(session, hábitos, fuso, now=...)` calcula a pontuação de vários hábitos com duas consultas.
- `schemas.py`: os tamanhos e formatos do plano. Nome de 1 a 60 caracteres, descrição até 500, recompensa e punição até 140, sigla de 1 a 4 letras (A-Z) ou números salva em maiúsculas, cor: um dos 12 nomes da paleta ou uma cor própria `#rrggbb` (ETH-49; `#ABCDEF` é salva como `#abcdef`; `#fff` e nomes fora da paleta são recusados). Espaços nas pontas saem, texto opcional vazio vira `null`, caracteres de controle e de direção do texto são recusados, booleanos e inteiros são estritos e campo desconhecido é recusado.
- `service.py` (100% de cobertura): as regras. `check_config` confere a configuração inteira depois de cada mudança: N ≥ 1 em `min` e `exact` e N ≥ 0 em `max`, teto de N (dias do período no toggle: 7, 28 ou 365; `MAX_MARKS_PER_DAY` × dias com várias por dia), minutos com a duração ligada, valor do custo no nível hábito, limite de custo e período juntos, e recompensa e punição só com a pontuação ligada. Desligar um recurso não apaga o valor dele, que volta ao religar. `MAX_HABITS_PER_USER` conta os ativos e pausados do dono dentro da transação da criação e do desarquivamento (409 `habit_limit_reached`).
- Pausar e arquivar (só o dono; pedir o estado atual não muda nada nem grava evento): pausar abre um intervalo em `habit_pauses` e retomar o fecha; fora do arquivo, `paused` tem exatamente uma pausa aberta (o índice único `uq_habit_pauses_open` impede duas). Pausado continua marcável, e a pontuação ignora os períodos com pausa. Arquivar grava `archived_at` (a pontuação congela nessa data) e deixa o hábito só leitura: editar, pausar e retomar dão 409 `habit_archived`; apagar continua. A pausa aberta de um hábito pausado fica aberta no arquivo. Desarquivar volta ao status de antes: `paused` se há pausa aberta; senão `active`, e o tempo arquivado vira a pausa fechada `[archived_at, agora)`, para não contar como meta não cumprida.
- `routes.py`: `GET /habits` (os do usuário e os compartilhados com ele, com o `role`; ativos e pausados, ou só os arquivados com `?archived=true`), `POST /habits` (201), `GET /habits/{id}`, `PATCH /habits/{id}` (mudança parcial; `null` só nos campos opcionais) `DELETE /habits/{id}` (204) e `POST /habits/{id}/pause`, `/resume`, `/archive` e `/unarchive` (sem corpo, devolvem o hábito). Editar, apagar, pausar e arquivar são só do dono. A pontuação (`score: {value, success}`, `null` em "sem dados") vem só com `score_enabled`, no fuso de quem pede; desligada, a chave nem aparece. Ela considera do período da criação até o atual, inclusive, sem os períodos com pausa: o atual entra com o valor de agora, mesmo incompleto (no meio da semana, uma meta mínima ainda não atingida conta como não cumprida, e a pontuação oscila ao longo do período), e o da criação entra também, só com as marcações a partir da criação (senão ele contaria enquanto é o atual e sumiria ao fechar). Arquivado congela no período do arquivamento, com o valor até `archived_at`. "Sem dados" só quando não sobra período (ex.: pausado desde a criação). Regras completas no docstring de `app/score.py`.
- Auditoria: `habit_created`, `habit_updated` com `{"changes": [{"field", "old", "new"}]}` (a descrição só com o `field`), `habit_deleted` com `habit_id=None` e `{"habit_id": n}` (mais `recent_invites`, os convites do hábito nas últimas 24 h, que continuam contando no limite de convites do dono), e `habit_paused`, `habit_resumed`, `habit_archived` e `habit_unarchived`. Apagar o hábito apaga em cascata as marcações, pausas, membros, convites, alertas e a auditoria dele, e os membros recebem o email `HabitDeleted` depois do commit.

Nos testes, a fixture `make_account(email, admin=False)` cria uma pessoa em `app_users` com os headers `X-User-*` (`Account(user, headers)`); `tests/habit_helpers.py` tem os atalhos da API de hábitos (`VALID`, `create`, `created`, `stored`, `events`, `share`, `NOT_FOUND`, `FORBIDDEN`, `invalid`); e `tests/factories.py` tem `new_member`, `new_invite`, `new_mark`, `new_pause` e `new_alert` para montar compartilhamento, marcações, pausas e alertas direto no banco.

### Marcações

O pacote `app/marks/` tem as marcações (`schemas.py`, `service.py` com 100% de cobertura, e `routes.py`). Todos os endpoints exigem `CurrentUser` e ficam debaixo do hábito:

| Endpoint | O quê |
|---|---|
| `POST /habits/{id}/toggle` | Hábito toggle. Corpo `{day_start, day_end, marked_at}`: o início e o fim do dia clicado no fuso do navegador (o fim é a meia-noite seguinte), e o instante a gravar, dentro do dia (agora, se o dia é hoje; 12:00 local, se é um dia passado). Se o dia já tem marcação (de qualquer membro), apaga todas e responde `{"marked": false, "mark": null}`; senão, cria uma e responde `{"marked": true, "mark": {...}}`. Sempre 200. |
| `POST /habits/{id}/marks` | Hábito com várias por dia. Corpo `{marked_at, note?, duration_minutes?, cost_cents?}`; 201 com a marcação. |
| `GET /habits/{id}/marks?from=&to=` | Marcações com `marked_at` em `[from, to)`, por `marked_at` e id: `{"marks": [...], "next_cursor"}`. Intervalo de até 367 dias (um ano do calendário com folga para o fuso). Página de até `limit` marcações (1 a 1000, padrão 1000); com `next_cursor` não nulo, repita com `&cursor=<next_cursor>` e o mesmo intervalo. Todo papel lê, inclusive em arquivado. |
| `PATCH /habits/{id}/marks/{mark_id}` | Muda só `note`, `duration_minutes` e `cost_cents` (campo ausente não muda; `null` apaga a observação ou o custo). `marked_at` ou qualquer outro campo no corpo: 422, e nada muda. |
| `DELETE /habits/{id}/marks/{mark_id}` | 204. |

A marcação sai como `{id, habit_id, author, marked_at, duration_minutes, cost_cents, note, created_at, updated_at}`, com datas em UTC (`...Z`). `author` é `{id, email}` de quem criou, ou `null` quando a conta foi apagada: a tela mostra "usuário removido". Os valores de recursos desligados vêm como estão guardados; o front os esconde conforme a configuração do hábito.

Regras (`service.py`):

- Datas com fuso em ISO 8601 (sem fuso, número ou antes de 1900: 422). `marked_at` até 1 minuto no futuro (tolerância de relógio); dias antes da criação do hábito são aceitos (a pontuação os ignora).
- Toggle: o intervalo do dia tem de 23 h a 25 h (horário de verão), senão 422 `day_end`; `marked_at` fora dele, 422 `marked_at`. A leitura e a escrita vão no mesmo `BEGIN IMMEDIATE`: clique duplo ou dois membros ao mesmo tempo deixam o dia com uma marcação ou nenhuma, nunca duas. A marcação nasce com a duração padrão do hábito (com a duração ligada) e o custo do hábito (com o custo ligado), editáveis depois.
- Várias por dia: `MAX_MARKS_PER_DAY` conta as marcações do hábito, de todos os membros, no dia de `marked_at` no fuso de quem marca (`X-User-Timezone`), na mesma transação da inserção (409 `mark_limit_reached`).
- Endpoint do modo errado (toggle num hábito com várias por dia, ou `POST /marks` num toggle): 409 `mark_mode_mismatch`.
- Observação só com `notes_enabled`, até `MAX_NOTE_LENGTH` caracteres, mesmas regras de texto da descrição do hábito. Duração só com `duration_enabled`, de 1 a 1440 minutos; sem ela, a padrão do hábito. Custo só com `cost_enabled`: no nível hábito é sempre o valor fixo do hábito (mandar outro, na criação ou no PATCH, dá 422); no nível marcação, o valor mandado ou, sem ele, o padrão do hábito. O custo fica gravado na marcação: mudar o do hábito não muda as antigas. Campo de recurso desligado: 422 com o campo.
- Escrita: dono e editor, em marcações de qualquer pessoa; viewer, 403 `forbidden`; sem acesso, 404 `not_found`; arquivado, 409 `habit_archived` (pausado aceita). A ordem é 404, 403, 409 (arquivado, modo), 422 e 409 (limite).
- Auditoria: `mark_created`, `mark_updated` e `mark_deleted` com `habit_id`, quem fez (`user_id`) e, no `details`, `{mark_id, author_id, marked_at, duration_minutes, cost_cents, has_note}` (criar e apagar; o toggle que desmarca grava um `mark_deleted` por marcação) ou `{mark_id, changes: [{field, old, new}]}` (editar). O texto da observação nunca vai para a auditoria: só `{"field": "note"}` ou `has_note`.

Nos testes, `tests/test_marks.py` tem os testes de concorrência com threads de verdade contra o banco em arquivo (`run_parallel(engine, chamadas, ação)`, que chama o `service` em sessões separadas, juntas por um `threading.Barrier`).

### Progresso (relatório e export)

O pacote `app/progress/` (`schemas.py`, `service.py` com 100% de cobertura, e `routes.py`) entrega os dados do relatório: `GET /habits/progress?from=YYYY-MM-DD&to=YYYY-MM-DD[&habit_ids=1&habit_ids=2]`. Exige `CurrentUser`; todo papel lê. O router é registrado antes do de `/habits` no `create_app`, senão `/habits/progress` cairia em `/habits/{habit_id}` (422).

- `from` e `to`: datas locais (só `YYYY-MM-DD`), inclusivas, no fuso de quem pede (`X-User-Timezone`), de 1900-01-01 a 2999-12-31. O intervalo cobre no máximo 5 anos de dias: de 2021-01-01 vai até 2025-12-31; 2026-01-01 já é "5 anos e 1 dia" (422 `validation_error` em `to`, como `to` antes de `from`). De 29/2, o aniversário num ano não bissexto é 1/3.
- `habit_ids`: repetido na query, até 100 (ids repetidos contam uma vez). Sem ele, todos os hábitos que o usuário acessa, inclusive os arquivados (eles guardam histórico e entram no "exportar tudo"). Hábito sem acesso, ou que não existe, some da resposta, sem erro: a API não revela que ele existe.
- Resposta: `{"from", "to", "timezone", "habits": [...]}`, por id. Cada item tem `habit` (o mesmo objeto do `GET /habits/{id}`, com `score: {value, success}` só com a pontuação ligada), `goal_target` (N, ou N × `duration_minutes` com a duração ligada), `periods` (`[{first_day, last_day, value, met, spend_cents}]`), `marks_range` (`{first_day, last_day}`: os dias locais da primeira e da última marcação do hábito em todo o tempo, não só no intervalo; `null` sem marcação; o "exportar tudo" do front parte dele) e, só com o custo ligado e um limite, `cost_periods` (`[{first_day, last_day, spend_cents, limit_percent}]`).
- Cálculos só pelo `score.py`, no fuso de quem pede. `periods` vem do `summarize_periods`: os períodos da meta que tocam o intervalo, inteiros (com o valor e o gasto do período todo), sem filtro de criação ou pausa. A pontuação vem do `evaluate`: é a pontuação atual do hábito, a mesma do `GET /habits`, não recortada pelo intervalo (as marcações de antes da criação vêm na leitura, mas o `score.py` as tira da pontuação).
- Gasto (só com `cost_enabled`; desligado, `spend_cents` e `cost_periods` nem aparecem): soma do `cost_cents` gravado em cada marcação, igual nos níveis hábito e marcação. `cost_periods` usa os períodos do limite (`cost_limit_period`, que pode ser diferente da meta); `limit_percent` é o gasto em porcentagem do limite, arredondado meio para cima só com inteiros (pode passar de 100; `null` com limite 0).
- Sem N+1: hábitos, marcações e pausas são lidos em lote (5 consultas com a sessão, em qualquer número de hábitos). A fixture `selects` do `conftest.py` conta os SELECT nos testes.

### Compartilhamento

O pacote `app/sharing/` tem os convites e os membros (`quota.py` e `service.py` com 100% de cobertura, `schemas.py` e `routes.py`). Papéis: o dono (`habits.owner_id`) configura, convida, troca papel e remove; `editor` marca e edita marcações de qualquer pessoa; `viewer` só vê. Todos os endpoints exigem `CurrentUser`; sem acesso ao hábito, 404 `not_found`; com acesso mas sem o papel, 403 `forbidden`.

| Endpoint | Quem | O quê |
|---|---|---|
| `POST /habits/{id}/invites` | dono | Corpo `{email, role}` (`editor` ou `viewer`). Sempre 202 `{"status": "sent"}`: com ou sem conta no imago, a si mesmo, a quem já é membro ou já tem convite pendente (esses três não mudam nada). Arquivado: 409 `habit_archived`. Imago fora do ar: 503 `service_unavailable`, e nada é gravado. |
| `GET /habits/{id}/invites` | dono | `{"invites": [{id, email, role, created_at}]}`, os pendentes (sem dizer se o email tem conta). |
| `DELETE /habits/{id}/invites/{invite_id}` | dono | 204, cancela o pendente. |
| `GET /habits/{id}/members` | todos | `{"members": [{user: {id, email}, role, joined_at}], "guest_limit": n}`, o dono primeiro (com a data de criação do hábito). `guest_limit` é o `MAX_GUESTS_PER_HABIT` (membros + pendentes), para a tela mostrar as vagas. |
| `PATCH /habits/{id}/members/{user_id}` | dono | Corpo `{role}`; devolve o membro. De editor para viewer, os alertas dele no hábito saem na mesma transação. |
| `DELETE /habits/{id}/members/{user_id}` | dono | 204. As marcações do membro ficam; os alertas dele no hábito saem. |
| `POST /habits/{id}/leave` | editor e viewer | 204, como remover. O dono recebe 403 (ele apaga o hábito). |
| `GET /invites` | convidado | `{"invites": [{id, habit: {id, name, color}, owner: {id, email}, role, created_at}]}`, os pendentes recebidos. |
| `POST /invites/{invite_id}/accept` | convidado | O hábito, como no `GET /habits/{id}`, com o papel novo. |
| `POST /invites/{invite_id}/decline` | convidado | 204. |

Regras (`service.py`):

- O convite não expira e não tem status: a linha de `habit_invites` existe enquanto está pendente e sai ao ser aceito, recusado ou cancelado.
- Quem tem conta é o imago: a rota confere o acesso e os limites, pergunta ao imago pelo email (`lookup_user`, fora de qualquer transação) e grava o convite ligado ao id da conta (`invited_user_id`, sem chave estrangeira). O email do convite é ASCII, como o do imago (espaços e maiúsculas não importam).
- Email sem conta ativa no imago (inexistente, bloqueada ou em exclusão): o convite fica pendente para sempre, com `invited_user_id` vazio, e nunca é entregue, nem se a conta for criada (ou desbloqueada) depois. Aceitar ou recusar um convite que não é do usuário (de outra conta, sem conta ou inexistente) dá o mesmo 404.
- Para não revelar quem tem conta, os ramos com e sem conta fazem as mesmas consultas e escritas, com o mesmo SQL (há teste), e o email ao convidado sai pelo imago depois da resposta (`BackgroundTasks`). O `details` da auditoria não leva o email nem o `invited_user_id`.
- Limites, conferidos dentro do `BEGIN IMMEDIATE` (requests em paralelo não passam deles), todos 409: `MAX_INVITES_PER_DAY` por dono, somando todos os hábitos (`invite_limit_reached`), `MAX_GUESTS_PER_HABIT`, membros + pendentes (`guest_limit_reached`), e `MAX_SHARED_HABITS_PER_USER` ao aceitar (`shared_habit_limit_reached`; o convite continua pendente). O hábito compartilhado conta só no `MAX_HABITS_PER_USER` do dono.
- `MAX_INVITES_PER_DAY` conta os eventos `invite_created` do dono nas últimas 24 h (janela móvel), porque as linhas de convite somem (`quota.py`). A retenção não apaga esses eventos. Como a auditoria do hábito sai com ele, o `habit_deleted` leva `recent_invites` e a conta soma esse número por 24 h depois da exclusão: apagar o hábito não devolve convites.
- Em hábito arquivado, só convidar é recusado; cancelar, aceitar, recusar, sair, remover e trocar papel continuam.
- Auditoria (todos com `habit_id`): `invite_created`, `invite_canceled`, `invite_accepted` e `invite_declined` com `{invite_id, role}`; `member_left` com `{role}`; `member_removed` com `{member_id, role}`; `member_role_changed` com `{member_id, changes: [{field: "role", old, new}]}`.

`tests/test_permissions.py` tem a matriz de permissões (dono, editor, viewer, estranho e sem sessão) de todos os endpoints de hábito, e quem vê o hábito nas listas (`/habits`, `/habits/progress`, `/history`).

### Histórico

O pacote `app/history/` (`service.py` com 100% de cobertura, `schemas.py` e `routes.py`) entrega o histórico dos hábitos, lido do `audit_log`: `GET /history`, do mais recente ao mais antigo. Exige `CurrentUser`; todo papel lê. O cursor das listagens (`"<microssegundos>.<id>"`, opaco para o cliente) fica em `app/pagination.py`, usado também pelas marcações.

- Eventos: só os de hábito (`habit_created`, `habit_updated`, `habit_paused`, `habit_resumed`, `habit_archived`, `habit_unarchived`), de marcação (`mark_*`) e de compartilhamento (`invite_*`, `member_*`), a lista `HistoryEvent`. Nunca os de admin nem `alert_updated` (a configuração de alerta é de cada membro). `habit_deleted` (com `habit_id` nulo) não aparece: a auditoria do hábito sai com ele.
- Acesso: os eventos dos hábitos que o usuário acessa agora (dono, editor ou viewer), inclusive arquivados e inclusive o que aconteceu antes de ele entrar. Quem sai ou é removido deixa de ver na hora. `invite_created`, `invite_canceled` e `invite_declined` só aparecem para o dono, como a lista de convites; `invite_accepted` aparece para todos.
- Filtros, opcionais e combináveis: `habit_id` (sem acesso ou inexistente: lista vazia, sem revelar nada), `user_id` (quem fez), `event` (repetido: `&event=mark_created&event=mark_deleted`; fora da lista, 422), `mark_id` (os eventos de uma marcação: quem criou, editou e apagou, e quando; usa o índice de `audit_log.mark_id`) e `from`/`to` (datas locais `YYYY-MM-DD`, inclusivas, no fuso de quem pede, como no progresso; `to` antes de `from`, 422).
- Paginação: `limit` de 1 a 200 (padrão 50), ordem `created_at` desc e `id` desc; com `next_cursor` não nulo, repita com `&cursor=<next_cursor>` e os mesmos filtros. A página seguinte continua depois da última linha vista: eventos novos entre uma página e outra não repetem nem pulam itens.
- Resposta: `{"events": [{id, event, created_at, habit: {id, label}, author: {id, email} | null, details}], "next_cursor"}`. `author: null` é "usuário removido". `details` sai filtrado por uma lista de chaves por evento (`PUBLIC_DETAILS`): o JSON gravado nunca é repassado inteiro, e o IP nunca sai.
- Uma consulta por página (hábito e autor em JOIN), sem N+1.

### Exclusão de conta

A exclusão é pedida e coordenada pelo imago (pela pessoa na conta dela ou pelo admin no painel do imago), que chama `POST /internal/users/{id}/delete` em cada aplicação. `delete_user_data` (`app/internal/service.py`, 100% de cobertura) apaga a parte do ethos numa transação só (`BEGIN IMMEDIATE`): ou tudo ou nada. É idempotente: id desconhecido ou repetido apaga o que sobrar e não falha.

- Apaga: os hábitos dela (com as marcações dos convidados, pausas, membros, convites enviados, alertas e a auditoria deles), os convites recebidos (pelo id e, se o ethos conhece o email dela, os feitos para esse email antes de a conta existir), os `habit_deleted` gravados por ela e a linha de `app_users` (o CASCADE leva as participações em hábitos de outras pessoas e os alertas).
- Anonimiza: as marcações dela em hábitos de outras pessoas (`user_id` nulo, "usuário removido"); as linhas do `audit_log` que ficam com o `user_id` dela (viram nulas); os ids dela em `author_id` e `member_id` dos eventos de hábito (viram `null`, porque o histórico os mostra); e todo texto com "@" no `details` das linhas que citam a pessoa (pelo `user_id`, pelo email ou por `target_user_id`, a pessoa alvo do `admin_viewed_habits`). `banners.created_by` vira nulo.
- Emails: "você perdeu acesso" para cada membro dos hábitos dela (um por membro, com todos os hábitos), lidos antes de apagar e mandados pelo imago depois do commit. O "conta excluída" é do imago.
- Log: só `dados da conta <id> apagados`, quando havia linha em `app_users`. O registro das exclusões a reaplicar depois de um restore é o journal do imago, que as refaz pela API interna; o `reapply-deletions` do ethos fica para as exclusões de antes da passagem (ver "Comandos de operação").

### Alertas

O pacote `app/alerts/` (`service.py` com 100% de cobertura, `schemas.py` e `routes.py`) tem os alertas por email: a configuração de cada membro num hábito e a avaliação de hora em hora (`run-alerts`, abaixo).

| Endpoint | Quem | O quê |
|---|---|---|
| `GET /habits/{id}/alerts` | dono e editor | A configuração do usuário logado: `{goal_enabled, cost_enabled, hour, frequency, weekday, last_sent_at}`. Sem nada salvo, a padrão: as duas chaves desligadas, `hour` 20, `daily`, `weekday` e `last_sent_at` nulos. Arquivado também lê. |
| `PUT /habits/{id}/alerts` | dono e editor | Troca a configuração inteira (`{goal_enabled, cost_enabled, hour, frequency, weekday}`) e devolve a nova. Arquivado: 409 `habit_archived` (pausado salva). |

- Viewer: 403 `forbidden` ao ler e ao salvar (quem tem papel de visualização não liga alertas). Sem acesso, 404 `not_found`. Cada membro tem a sua configuração, independente das outras.
- Validação (422 com o `field`): booleanos e inteiros estritos; `hour` de 0 a 23 (hora cheia, no fuso do usuário); `frequency` `daily` ou `weekly`; `weekday` de 0 (segunda) a 6 (domingo), obrigatório no semanal e proibido no diário; campo desconhecido é recusado.
- Salvar só grava o que mudou, com `alert_updated` (`{"changes": [{field, old, new}]}`) na auditoria. O evento não aparece no `GET /history`: a configuração é pessoal.
- Rebaixar um editor para viewer, remover o membro ou ele sair apaga os alertas dele no hábito, na mesma transação (`app/sharing/service.py`).

A avaliação (`run_alerts`):

- Hora: a hora cheia escolhida, no fuso do usuário (`app_users.timezone`, a cópia do imago), todo dia (diário) ou só no dia da semana escolhido (semanal). Cada ocorrência é avaliada uma vez, na primeira execução do `run-alerts` a partir dela no mesmo dia local: uma execução atrasada (o timer das 09:00 rodou às 10:05, ou a VM ficou fora umas horas) ainda avalia o alerta das 09:00; o dia que passa inteiro sem execução perde a ocorrência. Avaliação sem nada a avisar não se repete mais tarde no mesmo dia (`alerts.last_evaluated_at`). Salvar a configuração depois da hora de hoje deixa o alerta para a próxima ocorrência.
- Horário de verão: a hora que não existe (02:00 quando o relógio pula para 03:00) dispara às 03:00; a hora que se repete (01:00 duas vezes) dispara só na primeira.
- Regras, no período atual e só com a chave ligada: meta pelo `score.evaluate` (`min` atrasado no ritmo, `floor(N × fração do período)` com inteiros; `max` atingiu ou passou de N; `exact` passou ou atrasado); custo pelo `score.check_cost` (aviso a partir de 80% do limite, alerta ao passar). Nada dispara no período em que o hábito foi criado (a pontuação conta esse período; o ritmo, não), nem num período com pausa. Hábito pausado ou arquivado não é avaliado. Conta bloqueada ou em exclusão no imago é avaliada, mas o imago não manda nada (204) e o envio não é tentado de novo.
- No máximo um email por membro e hábito por dia local (`last_sent_at`), juntando meta e custo num email só (`Alert`), no idioma do usuário, com o link para `APP_URL/habits/{id}/alerts`.
- Sem email duplicado: o alerta é relido e reavaliado dentro de um `BEGIN IMMEDIATE`, que grava `last_evaluated_at` e `last_sent_at` antes do envio; o envio (pelo imago) sai depois do commit, fora da trava. Execuções repetidas ou ao mesmo tempo mandam um email só. Se o imago recusa pelo teto de envio compartilhado (429) ou o envio falha (rede, timeout, 5xx), outra transação desfaz a marcação e a próxima execução tenta de novo; se o processo morre entre o commit e o envio, aquele email se perde (um alerta a menos, nunca um repetido).
- Falha num alerta (imago fora do ar, fuso inválido, erro inesperado) vira uma linha de log com os ids do hábito e do usuário e o tipo do erro (nunca email, nome do hábito ou a mensagem da exceção) e não impede os outros.

### Admin e banners

O pacote `app/admin/` (`accounts.py` e `banners.py` com 100% de cobertura, `schemas.py` e `routes.py`) tem o painel de admin do ethos. Bloquear, trocar o email, apagar e tornar admin são do imago (painel `/imago/admin`). Todo `/admin/...` exige `AdminUser` (o `X-User-Admin: 1` do request; a dependência está também no router, então rota nova nunca fica aberta): sem login, 401 `not_authenticated`; usuário comum, 403 `forbidden`. Pessoa ou banner que não existe: 404 `not_found`. Listas paginadas por cursor, `limit` de 1 a 200 (padrão 50).

| Endpoint | O quê |
|---|---|
| `GET /admin/users` | `{"users": [{id, email, locale, timezone, first_seen_at, habit_count, mark_count}], "next_cursor"}`: quem já abriu o ethos (`app_users`), do primeiro acesso mais novo ao mais antigo. Filtros: `email` (trecho, sem curingas; espaços e maiúsculas não importam) e `first_seen_from`/`first_seen_to` (datas locais inclusivas no fuso do admin; fim antes do início, 422 em `first_seen_to`). |
| `GET /admin/users/{id}/habits` | `{"user", "habits", "marks", "next_cursor"}`: a pessoa, os hábitos de que ela é dona em qualquer status (como no `GET /habits/{id}`, `role` owner, sem `score`) e uma página das marcações deles, de todos os autores, com as observações, das mais recentes às mais antigas. `habit_id` filtra um hábito dela (de outra pessoa: 404). Cada chamada grava `admin_viewed_habits`, na mesma transação da leitura. `id` de 1 a 2^53 - 1. |
| `GET /admin/banners` | `{"banners": [{id, text_pt, text_en, starts_at, ends_at, created_by, created_at, updated_at}], "next_cursor"}`, todos, dos criados por último aos primeiros. |
| `POST /admin/banners` | 201. Corpo `{text_pt, text_en, starts_at, ends_at}`. |
| `PATCH /admin/banners/{id}` | Qualquer parte dos mesmos campos (`null` e campo desconhecido: 422). |
| `POST /admin/banners/{id}/end` | Fecha a janela agora. Agendado que ainda não começou: nunca aparece (`starts_at` vira 1 µs antes do fim). Já encerrado: nada muda. |
| `GET /banners/active` | Público, sem login: `{"banner": {id, text_pt, text_en, starts_at, ends_at} \| null}`. |

- Contagens: `habit_count` são os hábitos de que a pessoa é dona (todos os status) e `mark_count` as marcações que ela fez em qualquer hábito; saem de subconsultas na consulta da página (uma consulta, sem N+1).
- Banner: texto de 1 a 280 caracteres por idioma, sem espaços nas pontas, uma linha só (controles e quebra de linha: 422), guardado como veio (HTML não é interpretado; o front mostra como texto). Janela `[starts_at, ends_at)` em UTC, com o fim depois do início (senão 422 `ends_at`). Com mais de um na janela, aparece o que começou por último (empate: o criado depois).
- Auditoria, com `user_id` = o admin: `admin_viewed_habits` `{target_user_id, habit_id?}` (a pessoa alvo em `target_user_id`, por onde a exclusão dela acha a linha e tira os emails). Banners: `banner_created` `{banner_id, text_pt, text_en, starts_at, ends_at}`, `banner_updated` e `banner_ended` `{banner_id, changes: [{field, old, new}]}`. Ação que não muda nada (editar com os mesmos valores) não grava.

### Comandos de operação (CLI)

```bash
uv run --env-file .env python -m app.cli --help      # lista os comandos
uv run --env-file .env python -m app.cli run-alerts  # avalia os alertas na hora e manda os emails pelo imago
uv run --env-file .env python -m app.cli reapply-deletions exclusoes.log   # depois de um restore (exclusões de antes do imago)
uv run --env-file .env python -m app.cli seed        # dados de exemplo (só em dev)
```

O CLI lê a mesma config do servidor (variáveis de ambiente) e abre o banco de `DATABASE_PATH`, que precisa existir e estar migrado. Em produção roda como `app-ethos`. Código de saída 0 em sucesso, 1 em erro (a mensagem sai no stderr com `erro:`, sem stack trace nem valores) e 2 em uso errado.

| Comando | O quê |
|---|---|
| `run-alerts` | Avalia os alertas cuja hora chegou e manda os emails pelo imago (ver "Alertas"). Imprime quantos alertas avaliou, quantos emails o imago aceitou, quantos ele recusou pelo teto de envio (429) e quantas falhas teve. Sai com 0 mesmo com falha num alerta (imago fora do ar, por exemplo): a falha é logada, não para os outros e é tentada de novo na próxima execução. Só erro geral (config inválida, banco inacessível na leitura inicial) sai com 1, e aí o `OnFailure=` do timer grava a linha de erro no journald. Pode rodar quantas vezes quiser: a segunda seguida não manda nada. Roda de hora em hora pelo `ethos-alerts.timer`. |
| `reapply-deletions [arquivo]` | Depois de restaurar um backup do ethos, apaga de novo os dados das contas excluídas **antes da passagem do login para o imago** (ETH-64), que o journald do `app-ethos` registrou (passo a passo em [infra/RESTORE.md](../../infra/RESTORE.md#restaurar-o-banco-de-uma-app-ethos)). As exclusões de depois da passagem são do imago, que as refaz pelo journal dele e pela API interna (`POST /internal/users/{id}/delete`). Lê do arquivo ou do stdin (`-`, o padrão; recusa um terminal) as linhas do `journalctl -u app-ethos -o cat`: só as `INFO app.auth.deletion: conta <id> excluída` (o formato do login antigo) valem, as outras (requests, uvicorn, alembic, systemd) são ignoradas; aceita também ids soltos, um por linha. Para antes de mexer no banco (sai com 1, nada apagado) se a entrada estiver vazia (ex.: `journalctl` sem `sudo`), se uma linha citar a exclusão fora desse formato (ex.: `journalctl` sem `-o cat`) ou se uma linha só de dígitos não for um id válido (inteiro de 1 a 2^53 - 1). Id repetido conta uma vez. Cada id passa por `delete_user_data` (a mesma exclusão da API interna, ver "Exclusão de conta"), numa transação própria, **sem email** (todos já foram avisados na exclusão original). Id sem linha em `app_users` ainda tira os convites recebidos ligados a ele. Imprime as linhas lidas, as contas no log e quantas apagou e quantas não tinham linha em `app_users`. Pode rodar quantas vezes quiser: a segunda seguida não apaga nada. Falha no meio (banco): as já apagadas ficam, e rodar de novo termina. |
| `seed` | Só com `APP_ENV=dev` (fora dele: erro, sai com 1 e não grava nada). Cria, numa transação só, as linhas de `app_users` das contas do `seed` do imago, com os mesmos ids (101 `ana@example.com`, 102 `bia@example.com`, 103 `caio@example.com`), 8 hábitos que variam os tipos (toggle e várias por dia; meta mínima, máxima e exata; duração, observação, pontuação, custo nos dois níveis; ativo, pausado e arquivado; compartilhado com editor e viewer) e as marcações dos últimos 60 dias, pelas mesmas regras e com a mesma auditoria da API. Entre pelo `/imago/entrar` com essas contas (o `seed` do imago as cria). Não duplica: se algum desses ids já existe, avisa, sai com 0 e não grava nada. Para recriar, apague o banco de dev e rode `alembic upgrade head` de novo. |

Na VM, o comando roda com o mesmo usuário, o mesmo ambiente e a mesma `.venv` da unit `app-ethos` ([infra/apps/ethos/app-ethos.service](../../infra/apps/ethos/app-ethos.service)):

```bash
sudo journalctl -u app-ethos -o cat > exclusoes.log
sudo systemd-run --quiet --pipe --wait --collect \
  --uid=app-ethos --gid=app-ethos \
  --working-directory=/opt/apps/ethos \
  -p EnvironmentFile=/etc/infra/internal/ethos.env \
  -p EnvironmentFile=/etc/infra/apps/ethos.env \
  /opt/apps/ethos/.venv/bin/python -m app.cli reapply-deletions < exclusoes.log
```

`sudo -u app-ethos` sozinho não basta: o `/etc/infra/internal/ethos.env` é `0600` do root, e a config exige o `INTERNAL_API_TOKEN`. Pelo `systemd-run`, o systemd lê os dois `EnvironmentFile=` como root, como faz com a unit, e o comando roda como `app-ethos`, que pode escrever em `/var/lib/sqlite/ethos/app.db`. O `--wait` devolve o código de saída do comando, e o `--pipe` liga a ele o stdin, o stdout e o stderr do terminal (o `reapply-deletions` lê o journal por ele). O mesmo vale para qualquer outro comando do CLI. Para outro banco (um ensaio numa cópia), passe `/usr/bin/env DATABASE_PATH=<cópia>` antes do Python: um `-E DATABASE_PATH=...` do `systemd-run` perde para o `EnvironmentFile=`.

Comando novo: um handler `(context: CommandContext, args) -> int` em `app/cli.py`, registrado em `build_parser`. Erro esperado é `raise CommandError("mensagem")`; o docstring do módulo tem o passo a passo.

### Email

O pacote `app/mail/` monta os emails do ethos; quem envia é o imago (`POST /internal/mail`, por `app/imago_client.py`), com o remetente, o SMTP e o teto de envio dele:

- `catalog.py`: o catálogo fechado, um tipo por email com os dados que o texto usa (`Invite`, `Alert` com `GoalAlert`/`CostAlert`, `AccessLost`, `HabitDeleted`). Os emails de login, de conta e de troca de email são do imago. Não tem email em massa nem link de descadastro. O módulo não lê o banco: quem chama passa destinatário, idioma e dados.
- `templates.py`: os textos em pt e en, em texto puro e HTML simples. Todo texto é escapado no HTML (nome de hábito com `<script>` sai como texto). O assunto é fixo por tipo e idioma, sem dado do usuário. Os links saem do `APP_URL`; a tela de alertas fica em `APP_URL` + `/habits/{id}/alerts`, e o rodapé leva à conta do manasomali.com (`settings.account_url`, a origem do `APP_URL` + `/imago/`).
- `language.py`: `pick_locale(locale)`, o idioma da conta, com `en` quando não bate.
- `sender.py`: `Mailer`, criado na subida do app (`MailerDep` nos endpoints), e `schedule_email(background_tasks, mailer, user_id, locale, email)`, chamado depois que o `write_transaction` fechou. O destinatário é o id da pessoa no imago, nunca um endereço: o imago põe o email atual dela. O envio roda depois da resposta; se o endpoint levantar exceção, nada sai. Fora de request (CLI), `mailer.send(...)` devolve o `MailOutcome`.

Falha de envio nunca derruba o request: vira uma linha de log com o tipo do email e o status ou o tipo do erro (`email invite não enviado (ConnectError)`), sem destinatário nem corpo. Email novo entra no `catalog.py` e nos textos pt e en do `templates.py`; um teste confere que os dois idiomas têm as mesmas chaves e que todo o catálogo renderiza.

Nos testes, os emails que o app manda ficam em `imago.mails` (a fixture do imago falso). A fixture `smtp_server` (`tests/fake_smtp.py`, aiosmtpd com STARTTLS e login obrigatórios) só serve ao stack do E2E.

## Frontend

```bash
cd apps/ethos/frontend
npm ci
npm run dev                                # dev server na 5174; use o app pelo nginx de dev, em http://localhost:8080/ethos/
```

O dev server usa a porta 5174 (o site usa a 5173) e falha se ela estiver ocupada. Também dá para subir pela entrada `ethos` do `.claude/launch.json`. Ele não repassa a API: o backend só sabe quem é o usuário pelos headers que o nginx põe depois de perguntar ao imago. Use o app pelo nginx de dev (`bash apps/imago/dev/nginx.sh up --vite`, com os backends do imago e do ethos rodando; ver [apps/imago/dev/README.md](../imago/dev/README.md)), que serve este dev server em `http://localhost:8080/ethos/`, com HMR. Direto na 5174, as telas abrem, mas as chamadas da API falham.

```bash
npm run lint                               # ESLint com jsx-a11y; qualquer aviso falha
npm test                                   # vitest com cobertura, roda uma vez e sai
npm run build                              # gera dist/
npm run preview                            # serve o dist/ localmente
```

### Estrutura

| Caminho | O quê |
|---|---|
| `index.html` | Carrega `/ethos/theme-init.js` no `<head>`, sem `defer`, antes do app |
| `public/theme-init.js` | Aplica o tema salvo (`localStorage.theme`) como `data-theme` antes da primeira pintura. É arquivo, não script inline, por causa da CSP (`script-src 'self'`) |
| `public/locales/{pt,en}/translation.json` | Traduções, baixadas em runtime (não vão no bundle) |
| `src/main.jsx` | Inicia o i18n, cria o router e o QueryClient (`createApp`) e monta o `App` |
| `src/bootstrap.js` | `createApp()`: router com `basename="/ethos"` e QueryClient ligados (401 em qualquer chamada leva para o login do imago) |
| `src/routes.jsx` | Todas as rotas. Tela que exige login é filha de `RequireSession`; a ajuda, pública, fica fora. As rotas do login de antes do imago (`LEGACY_REDIRECTS`) levam às páginas do imago pelo `ExternalRedirect`. O painel de admin é filho de `RequireAdmin`; a aba do hábito (`/habits/:habitId`) tem as seções como rotas filhas do `HabitLayout` |
| `src/paths.js` | `BASENAME` e `PATHS` (`/`, `/convites`, `/ajuda`, `/habits/new`, `/habits/:habitId`, `/relatorio`, `/historico`, `/admin`, `/admin/contas/:userId`, `/admin/banners`), `adminUserPath(id)`, `HABIT_SECTION` (seções da aba do hábito), `habitPath(id, seção, query)`, `parseHabitId`, `reportPath({from, to, habitIds})`, `historyPath(habitId)` (o histórico já filtrado pelo hábito) e `helpPath(seção)` (a ajuda já na âncora da seção; seção desconhecida lança `RangeError`). Do imago, fora do basename: `IMAGO_PATHS` (`/imago/entrar`, a conta `/imago/`, `/imago/termos`, `/imago/privacidade` e `/imago/admin`, sempre em `<a href>` comum, nunca no `<Link>` do router) e `LEGACY_REDIRECTS` (`/entrar`, `/termos`, `/privacidade` e `/conta` do ethos → as páginas do imago). Use as constantes, nunca o caminho escrito à mão |
| `src/i18n.js` | `createI18n()`, `LANGUAGES` e a detecção do idioma (mesma chave do site, `i18nextLng`; `pt-BR` vira `pt`) |
| `src/index.css` | Estilos globais. Importa as fontes, `@tokens/tokens.css` (alias para `packages/tokens`) e a paleta |
| `src/styles/palette.css` | As 12 cores dos hábitos (`--habit-<nome>`) nos dois temas, o texto claro e o escuro sobre uma cor própria (`--habit-text-light`/`--habit-text-dark`) e o `--habit-color-text` de cada elemento com cor |
| `src/api/me.js` | `useMe()`/`fetchMe()` (`GET /me`, chave `meQueryKey`: id, email, idioma, fuso e `is_admin`, dos headers do imago) e `useCachedMe()` (o usuário já carregado, lido do cache sem buscar: para o que aparece também nas telas públicas, como o menu) |
| `src/api/banners.js` | `useActiveBanner()` (`GET /banners/active`, sem login, chave `activeBannerQueryKey`) |
| `src/api/alerts.js` | Alerta do usuário no hábito (`GET/PUT /habits/{id}/alerts`, chaves `alertKeys`): `useAlert(id)`, `useSaveAlert(id)` (409 `habit_archived`, 403 e 404 buscam o hábito de novo), `fetchAlert`, `saveAlert` |
| `src/api/admin.js` | Endpoints de `/admin` (chaves em `adminKeys`): `useAppUsers`, `useUserHabits`, `useBanners`, `createBanner`, `updateBanner`, `endBanner` |
| `src/api/habits.js` | `useHabits({archived})`, `useHabit(id)`, `fetchHabits`, `fetchHabit`, `canMark(habit)` e as chaves `habitKeys`; escritas do dono: `useCreateHabit`, `useUpdateHabit(id)`, `useHabitStatus(id)` (`mutate('pause' \| 'resume' \| 'archive' \| 'unarchive')`), `useDeleteHabit(id)` + `forgetHabit` (depois de sair da aba), `habitSaved` |
| `src/api/sharing.js` | Compartilhamento (chaves em `sharingKeys`): `useMembers(habitId, {enabled})` (`{members, guest_limit}`), `useHabitInvites(habitId, {enabled})`, `useReceivedInvites({enabled, fresh})`, `sendInvite`, `cancelInvite`, `changeMemberRole`, `removeMember`, `leaveHabit`, `acceptInvite`, `declineInvite` |
| `src/api/marks.js` | Marcações por ano (`useMarks(id, anos, fuso)` e `useMarksOfHabits(hábitos, anos, fuso)`, com os anos da faixa do calendário; `fetchYearMarks`, `yearMarksQuery`), escritas otimistas (`useToggleMark`, `useCreateMark`, `useDeleteMark`) e `useUpdateMark`, `afterMarksChanged`, chaves `markKeys` |
| `src/api/history.js` | `useHistory(query)` (`GET /history`, páginas por cursor, chaves `historyKeys`) e `seenHistoryAuthors(queryClient)`; os membros do filtro de autor vêm de `useMembers` (`src/api/sharing.js`) |
| `src/api/progress.js` | `fetchProgress({from, to, habitIds})` (`GET /habits/progress`, em grupos de 100 ids) e as chaves `reportKeys` do relatório |
| `src/api/report.js` | Dados do relatório e do export (abaixo, em "Relatório e export"): `useReportData`, `fetchReportData`, `fetchAllReportData`, `exportAllFile` |
| `src/components/` | `Layout` (pular para o conteúdo, menu, banner, `<main>`, rodapé com os links dos termos e da privacidade do imago), `Menu` (links, convites pendentes, link do admin só para `is_admin`, link da conta do imago, volta ao site, idioma, ícone da ajuda, tema; sem "Sair", que fica na conta do imago), `Banner`, `RequireSession`, `RequireAdmin`, `ExternalRedirect` (troca a página por um endereço fora do app, com um link para quem não tem JavaScript rodando), `TimezoneNotice`, `ErrorMessage`, `PageTitle`, `TextDocument` (texto puro com sumário e âncoras: a ajuda), `HelpLink`/`WithHelp` (ícone de ajuda ao lado de um título); do calendário: `Calendar` (desenha os meses de uma faixa, `range.months`, na visão escolhida, com o foco itinerante e as setas limitados a `range.first`/`range.last`; + `MonthGrid`, um mês em semanas com o cabeçalho dos dias da semana, `MonthColumn`, um mês numa coluna, e `DayCell`), `CalendarNav` (nome da faixa, anterior/próximo, a escolha do tipo da faixa e a da visão), `DayPanel`, `MarkItem`, `ConfirmUnmark` (segundo passo de desmarcar um dia com detalhes), `HabitTabs`, `HabitNav`, `HabitScore`; `HabitForm` (configuração do hábito, para criar e editar; a cor fica no `ColorField`), `HabitSwatch` (bolinha com a cor de um hábito); do relatório: `ExportAll` |
| `src/pages/` | Telas: `Home` (calendário de todos os hábitos), `Habit` (`HabitLayout`, a aba do hábito), `HabitCalendar`, `HabitSettings` (configuração), `HabitAlerts` (alertas), `NewHabit` (criar), `HabitSharing` (compartilhamento), `Invites` (convites recebidos), `Report` (relatório e export, num chunk à parte por `LazyReport`), `History` (histórico), `Help` (ajuda, sem login), `Admin/` (usuários, conteúdo dos hábitos de uma pessoa e banners), `NotFound`. Login, termos, privacidade e conta são páginas do imago |
| `src/hooks/` | `useTheme` (tema atual e a troca), `useCalendarParams` (faixa, dia e visão na URL; tipo da faixa e visão lembrados no navegador), `useHabitContext` (o hábito dentro das seções da aba), `useHabitColor` (ref que pinta um elemento com a cor de um hábito) |
| `src/help/{pt,en}.json` | Texto da ajuda (abaixo, em "Ajuda") |
| `src/lib/` | Utilitários sem React, com cobertura mínima de 80% (abaixo) |
| `src/test/` | Setup dos testes: MSW (`server`, `api(path)`, `activeBanner(banner)`), `renderApp(path)`, `meFixture()`, `createTestI18n()`, `axe`, `readFrontendFile()`; o `setup.js` troca `page.assign` e `page.replace` por mocks em cada teste (a navegação para o imago); do painel de admin, `src/test/admin.js` (`ADMIN`, `signedIn`, `appUserFixture`, `bannerFixture`, `trackRequests`, `adminRequests`); do compartilhamento, `src/test/sharing.js` (`mockSharingApi`, `memberFixture`, `pendingInviteFixture`, `receivedInviteFixture`, `writes`); dos alertas, `src/test/alerts.js` (`alertFixture`, `mockAlertsApi({alerts, fail})`) |
| `tests/` | Testes do build de produção, no Node |
| `e2e/`, `playwright.config.js` | E2E com o Playwright contra o stack local (abaixo, em "E2E"); fora do `npm test` |
| `build-targets.js` | Converte o `browserslist` do `package.json` no `build.target` do Vite |

### `src/lib/`

- `api.js`: `apiFetch(path, {method, query, body, signal})` chama `/api/ethos<path>` na mesma origem, com `credentials: 'include'` (o cookie da sessão é o do imago, HttpOnly; o front nunca o lê). Erro sempre vira `ApiError {status, code, field}`: o código vem do corpo `{"error", "field"}` da API ou, quando o corpo não é JSON (o nginx responde 429, 502 e 504 em HTML), do status, com o mesmo mapa de `app/errors.py`. Sem resposta: status 0 e código `network_error`.
- `queryClient.js`: `createQueryClient({onUnauthorized})`. Leitura só repete (até 2 vezes) falha de rede e 5xx; 401, 403 e 429 nunca repetem; escrita nunca repete sozinha. Todo 401, de leitura ou escrita, chama `onUnauthorized`.
- `session.js`: `loginUrl(location)` dá `/imago/entrar?next=<caminho atual>` (o caminho completo, com o `/ethos`, a query e o hash; fora do basename, `/ethos/`), e `redirectToLogin(router)` vai para lá saindo do app (`page.assign`). O imago confere o `next` e volta para ele depois do login.
- `page.js`: `page.assign(url)` e `page.replace(url)`, a navegação para fora do app (`window.location`), num objeto que os testes trocam por mocks.
- `errors.js`: `errorKey(error, i18n.exists)` dá `errors.<codigo>`, ou `errors.unknown` para código sem tradução e erro que não veio da API. Na tela, use o componente `ErrorMessage` (com `onRetry` opcional).
- `time.js`: dias locais como `"AAAA-MM-DD"`. `dayBounds(dia, fuso)` dá `{start, end}` (fim exclusivo) em UTC, o que o `POST /habits/{id}/toggle` espera; `pastDayNoon(dia, fuso)` dá 12:00 local em UTC; `markedAtFor(dia, fuso, agora)` dá o `marked_at` (hoje: o instante atual; passado: 12:00 local; futuro: `RangeError`). Também `today`, `localDate`, `addDays`, `parseDate`, `zonedTimeToUtc`, `browserTimezone`, `sameTimezone`. Hora que não existe ou se repete (horário de verão) segue o backend (`fold=0`).
- `calendar.js`: meses e dias do ano no desenho do calendário, com a semana começando no domingo (`WEEK_START`, `CALENDAR_WEEKDAYS`, `weekColumn(dia)`, `calendarMonth(ano, mês)` e `yearMonths(ano)` com o `offset` do dia 1; só o desenho: a semana da meta continua de segunda a domingo, em `periodFirstDay` e no `score.py`), `yearRange(ano, fuso)` (o `from`/`to` do ano em UTC), `marksByDay`, `overviewByDay` e `splitDots` (até 4 pontos e o "+N"), `moveDay` (setas na grade), `moveColumnDay` e `shiftMonthDay` (setas nas colunas), `parseYear`/`parseDay` (URL), `MIN_YEAR`. `calendarView.js`: a visão do calendário (`CALENDAR_VIEWS`, `DEFAULT_CALENDAR_VIEW`, `VIEW_STORAGE_KEY`, `parseCalendarView`, `resolveView`). `calendarRange.js`: a faixa de meses do calendário (abaixo, em "Calendários e marcação"): `RANGE_KINDS`, `DEFAULT_RANGE_KIND`, `RANGE_STORAGE_KEY`, `calendarRange(tipo, âncora)`, `resolveCalendar` (estado a partir da URL), `rangeNeighbors`, `switchAnchor`, `clampAnchor`, `shiftAnchor`, `writeRangeParams`, `monthOf`, `monthParam`/`parseMonthParam`. `format.js` também tem `formatMonthYear`, `formatMonthShort` (o título das colunas) e `formatPeriod(faixa, idioma)`. `format.js`: dias, meses, datas e horas formatados pelo idioma (`weekdayNames` na ordem da API, 0 = segunda, com a inicial `short` e o nome `long`; `calendarWeekdayNames` na ordem das colunas do calendário; `formatDate` para a data de um instante no fuso de quem vê). `duration.js`: `parseDuration` e `MAX_DURATION_MINUTES`.
- `habitForm.js`: o formulário do hábito (abaixo, em "Configuração do hábito"): `habitForm(hábito, idioma)`, `habitPayload(form, idioma, hábito)`, `goalSummary(form)`, `visibleFields`, `turnedOff`, `minGoalCount`/`maxGoalCount`, `textLength`, `hasForbiddenControls` e as constantes (`TEXT_LIMITS`, `PERIOD_DAYS`, `MAX_MARKS_PER_DAY`, `FEATURES`, `FORM_FIELDS`).
- `alerts.js`: o formulário de alerta (abaixo, em "Alertas"): `alertForm(alerta)`, `alertErrors(form)`, `alertPayload(form)`, `hasCostAlert(hábito)`, `formatHour(hora, idioma, minuto)`, `canFallBehind(meta)`, `weeklyPaceStart(meta)`, `periodFirstDay(dia, período)`, `firstAlertDay(criado_em, período, fuso, agora)` e as constantes (`DEFAULT_HOUR`, `ALERT_HOURS`, `FREQUENCIES`, `WEEKDAYS`, `COST_WARNING_PERCENT`; o teste confere a hora padrão e os 80% com o backend).
- `money.js`: `formatMoney(centavos, idioma)` sem símbolo, com 2 casas (`1.234,50` / `1,234.50`); `parseMoney(texto, idioma)` lê o que a pessoa digitou e devolve centavos ou `null`; `MAX_MONEY_CENTS`.
- `palette.js`: `HABIT_COLORS` (os 12 nomes de `HabitColor`), `isHabitColor`, `isCustomColor` (`#rrggbb` em minúsculas), `isValidColor`, `textTone(hex)` (texto claro ou escuro sobre uma cor própria), `applyHabitColor(elemento, cor)` (o jeito único de pintar; ver Cores abaixo) e `readPaletteHex(nome)`. `customColor.js`: `THEME_COLORS` (fundo, superfície e texto dos dois temas, lidos de `tokens.css` importado como texto), `MIN_COLOR_CONTRAST` (3) e `lowContrastThemes(hex)` (o aviso do formulário). `color.js`: `contrastRatio`, `relativeLuminance` (WCAG). `css.js`: `readCustomProperties(css)`, as propriedades customizadas de um CSS por seletor.
- `help.js`: `HELP_SECTIONS` (as âncoras da ajuda, na ordem) e `loadHelp(idioma)` (abaixo, em "Ajuda").
- `theme.js` e `storage.js`: leitura e escrita da chave `theme` e do `localStorage` sem lançar exceção (modo privado). `timezoneNotice.js`: regra do aviso de fuso.
- `datetime.js`: `formatDateTime(instante, fuso, idioma)` e o valor de um `<input type="datetime-local">` no fuso de quem vê (`toDateTimeLocal`, `fromDateTimeLocal`).
- `banner.js`: texto do banner no idioma da tela (`bannerText`), o "fechar" lembrado por id em `ethos:banners-dismissed` (`dismissBanner`, `isBannerDismissed`; guarda os últimos 20), o contador de 280 caracteres como a API conta (`bannerTextLength`: sem os espaços das pontas, um por caractere Unicode) e o formulário do admin (`bannerForm`, `bannerPayload`, `bannerStatus`).
- `markDetails.js`: `markHasDetails(hábito, marcação)` e `dayHasDetails(hábito, marcações)`: se desmarcar perderia observação, duração ou custo (abaixo, em "Calendários e marcação").
- `sharing.js`: `guestSlots(membros, convites, limite)`, as vagas de convidados (membros sem o dono + convites pendentes) do contador da tela.
- `history.js`: o histórico. Filtros na URL (`parseHistoryFilters`, `historySearch`, com os nomes da API) e a query do `GET /history` (`historyQuery`); `EVENT_GROUPS`/`HISTORY_EVENTS` (iguais ao `HistoryEvent` do backend, conferido no teste) e o seletor de eventos (`eventSelection`, `selectionEvents`); `pageEvents` (páginas juntas sem repetir id); `authorOptions` (pessoas do filtro de autor) e `describeEvent`/`describeChange` (o texto de cada evento e de cada mudança, a partir do `details` público).
- `admin.js`: filtros da listagem de usuários (`USER_DATE_FILTERS`, `EMPTY_USER_FILTERS`, `userQuery`) e o id da pessoa na URL (`parseUserId`, até `Number.MAX_SAFE_INTEGER`, o maior id do imago).
- `export/`: o relatório e os exports, sem React (abaixo, em "Relatório e export"). `time.js` ganhou `localTime` ("HH:MM") e `format.js`, `formatShortDay`.

### Calendários e marcação

- **Rotas:** `/` é a aba principal (todos os hábitos ativos e pausados; os arquivados ficam numa seção à parte) e `/habits/:habitId` a aba do hábito (`HabitLayout`: cabeçalho, pontuação e o submenu `HabitNav`), com o calendário como rota índice. Faixa, dia e visão escolhidos ficam na URL (`?range=year&year=2025&day=2025-03-04`, `?range=3months&month=2026-01&view=columns`). Seção nova do hábito (configuração, compartilhamento, alertas): rota filha do `HabitLayout` em `src/routes.jsx` com o caminho de `HABIT_SECTION`, um item no `HABIT_NAV` de `components/HabitNav` e `useHabitContext()` para receber `{habit, timeZone}`. O caminho dos alertas é fixo (`/habits/:habitId/alerts`, o link do email; `src/paths.test.js` confere com o backend).
- **Cache:** `habitKeys.list({archived})` e `habitKeys.detail(id)` para os hábitos; `markKeys.year(id, ano, fuso)` guarda todas as marcações do ano local de um hábito, compartilhada pelas duas abas. Uma request por hábito e ano (páginas de 1000, seguindo o `next_cursor`); a faixa lê só os anos que toca (dois quando a janela de 3 meses cruza o ano), e cada escrita otimista mexe e desfaz só no ano do dia dela. Mudou a configuração de um hábito: invalide `habitKeys.all` (as marcações não mudam).
- **Escolher e marcar (ETH-54):** clicar num dia, ou Enter/Espaço nele, só escolhe o dia (`onSelect` do `DayCell`, que vai para `?day=`) e mostra os detalhes no painel, nas duas abas e nas duas visões; nada é criado nem apagado. Marcar e desmarcar ficam nos botões do painel: na aba do hábito, "Marcar este dia"/"Desmarcar este dia" (toggle) ou "Adicionar marcação" (várias por dia, cada uma se apaga no `MarkItem`); na aba principal, "Marcar"/"Desmarcar"/"Adicionar" por hábito (`OverviewRow`, com o nome do hábito no nome acessível). Viewer e arquivado só escolhem, sem botões de escrita. Desmarcar um dia com detalhes que não voltam ao marcar de novo (`dayHasDetails`: observação, duração diferente da padrão do hábito ou custo por marcação diferente do padrão; só os recursos ligados) pede confirmação (`ConfirmUnmark`): o foco vai para "Cancelar", Esc cancela, e depois o foco volta ao botão de desmarcar. O foco não sai do calendário ao escolher um dia (as setas continuam andando); o painel vem antes do calendário no HTML, então Shift+Tab chega aos botões dele. O `aria-label` do dia escolhido ganha "Escolhido" depois da data (`calendar.day_selected`).
- **Duplo clique (ETH-55):** na aba do hábito, o duplo clique num dia (`onActivate` do `DayCell`, nas duas visões) faz a ação principal do painel pelo mesmo caminho do botão (`primaryAction` em `pages/HabitCalendar`): marca ou desmarca (toggle, com a confirmação do `ConfirmUnmark` quando `dayHasDetails`) ou adiciona uma marcação (várias por dia). Os dois cliques antes dele só escolhem o dia, então sai uma escrita só por duplo clique, otimista e desfeita se a API falhar. A ação recebe o dia clicado, e não o da URL: a navegação do router é uma transição e pode chegar depois do `dblclick`; por isso a confirmação pedida para um dia ainda não escolhido espera ele ser escolhido (e some se outro dia for escolhido). `onActivate` é estável (o `DayCell` é memorizado) e só vai para quem pode marcar, com as marcações carregadas; o `DayCell` ignora o dia futuro. Na aba principal (vários hábitos no dia), viewer e arquivado, o duplo clique só escolhe. É um atalho de mouse: o teclado continua com os botões do painel. O dia tem `user-select: none` (o duplo clique não seleciona o número) e `touch-action: manipulation` (sem o zoom do toque duplo no celular).
- **Escritas:** `useToggleMark`, `useCreateMark` e `useDeleteMark` mudam a tela na hora e desfazem a mudança se a API falhar; quando dois cliques no mesmo hábito se cruzam ou a resposta não bate com o que a tela supôs, o ano é buscado de novo ao fim da última escrita. Toda escrita termina em `afterMarksChanged`, que atualiza a pontuação (só se ligada); telas com dados derivados das marcações (relatório) invalidam ali o que guardam.
- **Faixa:** o calendário mostra só o mês, 3 meses (o escolhido e os dois anteriores) ou o ano inteiro, escolhido no `CalendarNav` das duas abas. O tipo fica na URL (`range`) e lembrado no navegador (`ethos:calendar-range`, uma escolha para as duas abas); quem nunca escolheu vê o ano inteiro (o calendário anual do plano). Anterior e próximo andam um mês, 3 meses ou um ano, entre janeiro de `MIN_YEAR` e o mês de hoje; a janela de 3 meses termina no mês escolhido, então nunca mostra mês depois do de hoje. Trocar de tipo mantém o dia escolhido visível (a nova faixa fica em volta do mês dele); sem dia, a nova faixa começa no primeiro mês que estava na tela. A faixa é separada do desenho: `calendarRange` dá `{kind, anchor, first, last, months, years}` e o `Calendar` só percorre `months`, então outro desenho recebe a mesma faixa.
- **Visão:** grade (cada mês em semanas, o padrão) ou colunas (cada mês uma coluna da largura de um dia, com o nome do mês abreviado e os dias de cima para baixo: o número e a marcação, sem o dia da semana, que fica no `aria-label`; uma linha separa as semanas e o mesmo dia fica na mesma altura em todas as colunas). O dia tem o mesmo tamanho nas duas visões: uma regra só, `--day-size` em `components/Calendar/styles.module.css`, tirada da largura do calendário (container query), e `styles.test.js` falha se uma visão redefinir o tamanho do dia, escolhida no `CalendarNav` das duas abas e combinada com qualquer faixa. Fica na URL (`view`) e lembrada no navegador (`ethos:calendar-view`, separada da faixa); trocar de visão mantém a faixa e o dia. Quando as colunas não cabem (o ano no celular ou numa tela estreita), o calendário rola na horizontal por dentro (o grupo com o rótulo "Calendário de ..."), sem rolar a página; ao abrir, a coluna do dia escolhido (ou de hoje) aparece, e as setas levam a rolagem junto.
- **Teclado:** a faixa é uma parada de Tab só; as setas andam entre os dias e Enter/Espaço escolhem o dia (não marcam; o duplo clique é só do mouse, e no teclado marcar fica nos botões do painel). Na grade, ←/→ andam um dia e ↑/↓ uma semana; nas colunas, ↑/↓ andam um dia (do fim de um mês para o começo do próximo) e ←/→ vão para o mesmo dia na coluna vizinha (o último dia, se o mês for mais curto). Home/End: começo e fim do mês nas duas; nas pontas da faixa, o foco fica no primeiro ou no último dia. Dia futuro fica `aria-disabled` (continua focável e lido).

### Configuração do hábito

- **Rotas:** `/habits/new` cria (link "Novo hábito" na aba principal) e `/habits/:habitId/settings` edita, como seção da aba do hábito. As duas usam o `HabitForm`. A seção só aparece no submenu para o dono (`visible: (habit) => habit.role === 'owner'` no `HABIT_NAV`), e quem não é dono e abre o endereço volta para o calendário; quem garante é a API (403).
- **Formulário (`src/lib/habitForm.js`):** valida como a API (tamanhos de `app/models.py`, sigla `A-Z0-9` com até 4, caracteres de controle e de direção do texto, N de 0 só no tipo máximo até os dias do período, ou `MAX_MARKS_PER_DAY` x dias com várias por dia, duração de 1 a 1440, limite de 1 a 100, dinheiro por `parseMoney` no idioma do formulário). Os erros aparecem no campo depois de mexer nele ou de enviar, e o foco vai para o primeiro inválido. Um 422 da API com `field` aparece embaixo do campo (`habit_form.invalid.<campo>`) e o foco vai para ele; outros erros (ex.: `habit_limit_reached`) aparecem embaixo do formulário. `src/lib/habitForm.test.js` confere os limites e os campos com o backend.
- **Cor (ETH-49):** as 12 cores da paleta primeiro e, por último, a opção "Personalizada", com um seletor de cor (`<input type="color">`, que começa na cor atual da paleta). A cor própria é um hex só, o mesmo nos dois temas: a prévia a mostra sobre o fundo de cada tema (cores dos tokens, `THEME_COLORS`), com o número do dia marcado no texto que o calendário usa, e um aviso aparece quando ela tem menos de 3:1 contra o fundo ou a superfície de algum tema (a cor é aceita mesmo assim). Voltar para a paleta manda o nome; a última cor própria fica no formulário (`custom_color`, que não vai para a API) e volta ao marcar "Personalizada".
- **Recursos:** várias marcações por dia, duração, observação, pontuação (limite 70 por padrão; recompensa e punição só com ela ligada) e custo (nível hábito com valor obrigatório, ou marcação com valor padrão opcional; limite com período, ou "sem limite"). Campo de recurso desligado fica escondido e não é validado nem enviado, então o valor guardado volta ao religar. Desligar um recurso que está ligado no hábito salvo mostra o aviso de que os dados ficam guardados.
- **Envio:** criar manda a configuração (campos escondidos ficam com o padrão da API) e abre a aba do hábito; editar manda no `PATCH` só os campos visíveis que mudaram (nada mudou: avisa e não chama). Toda escrita guarda o hábito devolvido em `habitKeys.detail(id)` e invalida `habitKeys.all`.
- **Status e exclusão:** pausar, retomar, arquivar e desarquivar conforme o status (arquivado deixa o formulário só leitura). Apagar pede um segundo passo, com o aviso de que as marcações dos convidados também somem; depois volta para a aba principal e tira o hábito do cache.
- **Testes:** `mockHabitWritesApi(habits, {fail})` em `src/test/habits.js` simula as escritas do dono sobre o mesmo array do `mockHabitsApi` e guarda cada chamada em `requests`.

### Compartilhamento

- **Rotas:** a seção `/habits/:habitId/sharing` (`HABIT_SECTION.sharing`, visível para todo papel) e a caixa de convites recebidos `/convites` (`PATHS.invites`), com o link "Convites" no menu.
- **Dono:** convida por email com o papel (editor ou viewer), vê o contador de vagas, troca o papel (um clique), remove membros (com confirmação) e cancela convites pendentes (sem confirmação). A mensagem do convite é sempre "convite enviado", com ou sem conta, a quem já é membro ou já tem convite: a API responde igual nesses casos. Sem vagas, o envio fica desligado. Em hábito arquivado só o formulário some (a API recusa só o convite).
- **Editor e viewer:** veem quem tem acesso e podem sair do hábito (com confirmação). Depois de sair, a tela volta para a inicial e só então o hábito sai do cache (antes, a aba ainda montada buscaria o hábito e levaria um 404).
- **Vagas:** o `MAX_GUESTS_PER_HABIT` vem da config do backend; o `GET /habits/{id}/members` o devolve em `guest_limit`. O contador é `guestSlots` (membros sem o dono + pendentes), e a API confere de novo (409 `guest_limit_reached`).
- **Convites recebidos e cache:** sem polling. `useReceivedInvites` vale por `RECEIVED_STALE_TIME` (5 min) e é buscado de novo ao voltar para a aba do navegador (só depois desse tempo), ao abrir `/convites` (`fresh`: sempre) e depois de aceitar ou recusar. O menu usa a mesma consulta, só com sessão e termos aceitos, e mostra o número de pendentes (o leitor de tela ouve "N convites pendentes"). Aceitar invalida `habitKeys.all`, para o hábito aparecer na lista e nas abas.
- **Testes:** o `server` do MSW responde `GET /invites` sem convites por padrão (`receivedInvites(invites)` em `src/test/server.js`), porque o menu busca em toda tela com sessão. Um handler genérico (`http.all(api('/*'))`) precisa registrar `receivedInvites()` antes, como `activeBanner()`.

### Histórico

- **Rota:** `/historico`, no menu principal e no submenu da aba do hábito (atalho `historyPath(id)`, `?habit_id=<id>`). Cobre todos os hábitos que a pessoa acessa, arquivados inclusive.
- **Filtros na URL:** `habit_id`, `user_id`, `event` (repetido) e `from`/`to` (datas locais no fuso da conta, inclusivas), com os mesmos nomes da API. O formulário edita um rascunho e só muda a URL no "Filtrar" (cada aplicação empilha uma entrada: o voltar do navegador volta aos filtros anteriores, e o link compartilhado abre com os mesmos). Valor inválido na URL é ignorado; período invertido mostra o erro e não chama a API.
- **Eventos:** um seletor com todos, os três grupos (hábito, marcações, compartilhamento) e cada evento; uma combinação que veio pelo link e não é grupo aparece como "N eventos escolhidos no link".
- **Pessoas do filtro de autor:** a API não lista "quem já agiu no hábito", então a lista junta você, o dono e os membros do hábito escolhido no filtro (`useMembers`, `GET /habits/{id}/members`) e os autores que já apareceram em qualquer histórico carregado na visita (`seenHistoryAuthors`, do cache). Quem saiu do hábito e não aparece na lista carregada fica de fora; uma pessoa que veio pelo link e a tela não conhece aparece como "pessoa nº <id>".
- **Lista:** "carregar mais" segue o `next_cursor` com os mesmos filtros, junta as páginas sem repetir id (`pageEvents`) e leva o foco ao primeiro evento novo. Horário no fuso da conta (`formatDateTime`), hábito com link para a aba dele, autor ou "usuário removido". O texto de cada evento sai do `details` público (`PUBLIC_DETAILS` no backend): data da marcação, duração, custo, "com observação", o que mudou na configuração (`campo: antes → depois`), papel do convite e do membro. Campo ou evento que a tela não conhece aparece com o nome cru.
- **Cache:** `afterMarksChanged` invalida `historyKeys.all` além do relatório (a lista ganha eventos a cada marcação).

### Alertas

- **Rota:** `/habits/:habitId/alerts`, seção da aba do hábito e destino do link do email de alerta. Sem login, o 401 leva ao login do imago com a tela no `next`, e o imago volta para ela. O item "Alertas" do submenu aparece para o dono e o editor (`visible: (habit) => habit.role !== 'viewer'`); o viewer que abre o endereço vê "sem permissão", e a tela nem chama a API (que daria 403).
- **Formulário:** chave de meta, chave de custo (só quando o hábito tem custo com limite: `hasCostAlert`), hora cheia no fuso da conta (`me.timezone`, mostrado embaixo da hora com o link da conta do imago), diário ou semanal, e o dia da semana só no semanal (obrigatório: o semanal sem dia mostra o erro e põe o foco no campo, sem chamar a API). Salvar manda a configuração inteira no `PUT` (no diário, `weekday: null`); uma chave escondida vai com o valor salvo, como os campos escondidos do hábito. Arquivado: só leitura. Pausado: salva, com o aviso de que nada dispara.
- **Textos de quando dispara:** a meta atual (`goalSummary`) com a regra do `score.py`: mínimo atrasado no ritmo (com o exemplo da semana: 3x por semana fica atrasado a partir de quarta às 08:00; no mês e no ano, a regra da metade), máximo ao atingir ou passar (N = 0: na primeira marcação), exato ao passar ou atrasar; com meta 1 no período o ritmo nunca atrasa (`canFallBehind`), e a tela diz isso. Custo: aviso em 80% do limite e ao passar. Também: no máximo 1 email por dia, nada no período da criação (com a data de quando começa a valer, se ainda é esse período: `firstAlertDay`) e que salvar depois da hora de hoje só vale a partir da próxima ocorrência.
- **Testes:** `mockAlertsApi` em `src/test/alerts.js` guarda cada chamada em `requests`; o `PUT` troca tudo e mantém o `last_sent_at`, como a API.

### Regras para as próximas telas

- **Textos:** todo texto visível entra nos dois `translation.json`. Código de erro novo em `app/errors.py` também: o teste `src/i18n.test.js` lê o `ErrorCode` do backend e falha se faltar a tradução em pt ou en.
- **Dados:** sempre por TanStack Query sobre `apiFetch`, nunca `fetch` direto. Não trate o 401 na tela (o QueryClient já leva ao login do imago); mostre os outros erros com `ErrorMessage`.
- **Login, termos e conta (ETH-64):** são do imago. Qualquer 401 leva a `/imago/entrar?next=<caminho atual>` (`redirectToLogin`); termos pendentes também dão 401 no ethos, e o imago os pede no login. Link para o imago (conta, termos, privacidade, admin) é `<a href>` comum com `IMAGO_PATHS`, nunca `<Link>` do router (fica fora do `/ethos`). Email, idioma e fuso da conta mudam na conta do imago, e o aviso de fuso (`TimezoneNotice`) leva para lá; nada muda o fuso sozinho. Sair também é na conta do imago. O "exportar tudo" (`ExportAll`) fica no relatório.
- **Datas:** a API guarda e devolve UTC; mostre no fuso de quem vê (`me.timezone`), com `src/lib/time.js`. Nunca use os métodos locais de `Date` (`getDate`, `setHours`...), que seguem o fuso do sistema.
- **Cores:** só tokens (`var(--fg)`, `var(--surface)`...) e a paleta. A cor de um hábito é um nome da paleta ou uma cor própria `#rrggbb` (ETH-49). Para pintar algo com ela: `<HabitSwatch color={habit.color} className={styles.swatch} />` para a bolinha, ou `ref={useHabitColor(habit.color)}` em outro elemento, e `var(--habit-color, var(--muted))` no CSS (texto sobre a cor: `var(--habit-color-text, var(--bg))`). Por baixo, `applyHabitColor` põe `data-habit-color` (o nome, ou `custom`) e, na cor própria, `--habit-color` pelo CSSOM (`element.style.setProperty`) e `data-habit-text` (`light`/`dark`). A CSP (`style-src 'self'`) bloqueia `<style>` e o atributo `style` vindo no HTML, mas não o CSSOM, que é JavaScript do próprio app (`script-src 'self'`). Nada de `style` no JSX nem de `data-habit-color` escrito à mão. O teste `src/styles/colors.test.js` falha com hex, `rgb()` e afins fora de `palette.css`.
- **Tela nova:** `PageTitle` com o título, um `<h1>`, CSS Module ao lado, ícones do `react-icons` em pixels inteiros (`size={20}`), layout a partir de 320 px. Teste com `renderApp(path)` e MSW (`server.use(http.get(api('/...'), ...))`), e `axe` sem violações.

### Ajuda

- **Rota:** `/ajuda` (`PATHS.help`), fora do `RequireSession`: explica as regras e não mostra nem busca dado de ninguém, então serve também a quem ainda não tem conta. No menu, é um ícone ao lado do idioma e do tema (os links em texto já enchem a linha). As telas que precisam de explicação têm um ícone de ajuda ao lado do título (`<WithHelp section="alerts" topic={título}>`), que abre a seção certa em outra aba, para não perder o que a pessoa está preenchendo: configuração (`goal` e `pause-archive`), novo hábito (`goal`), alertas, compartilhamento e relatório.
- **Texto:** `src/help/{pt,en}.json`, texto puro (`{title, sections: [{id, title, paragraphs}]}`, sem marcação nem marcador), mostrado pelo `TextDocument`. As seções da conta e do contato levam à conta do manasomali.com (`/imago/`), onde ficam o login, o fuso, a exclusão e o suporte. A ajuda também aceita um bloco de link externo (`{href, label}`, num parágrafo próprio) para endereços da lista `HELP_LINKS` de `src/lib/help.js`; hoje, só o da seção "Inspiração" (o Every Day Goal Calendar, de Simone Giertz). `loadHelp(idioma)` ignora a região (`pt-BR` vira `pt`), cai no inglês quando o idioma não tem texto (e diz qual veio, para o `lang`) e baixa cada idioma num chunk à parte.
- **Regra:** a ajuda descreve o que o app faz hoje, conferido no código (`app/score.py`, `app/alerts/service.py`, `app/marks/service.py`, `app/sharing/service.py`, `app/habits/service.py`, `app/internal/service.py`). Mudou uma regra, mude o texto nos dois idiomas. `src/lib/help.test.js` falha se pt e en não tiverem exatamente as seções de `HELP_SECTIONS` (mesma ordem e forma), se houver marcação no texto, ou se os números citados não baterem com o código: limite padrão da pontuação, arredondamento, "Sem dados ainda" da tela, o rótulo "Períodos com a meta cumprida" do relatório, os horários do exemplo de ritmo ("3 vezes por semana": quarta às 08:00 e sexta às 16:00, a partir do `weeklyPaceStart`) e dos minutos (14 min às 20:00 de segunda), os 80% do custo, o teto de N por período, os limites de `infra/apps/ethos/app.env`, o prazo das cópias de segurança na exclusão (`infra/scripts/snapshot.sh` e `infra/lib/backups.sh`) e se a conta e o contato não apontam para a conta do imago.

### Relatório e export

- **Rota:** `/relatorio?from=AAAA-MM-DD&to=AAAA-MM-DD&habit_id=3&habit_id=5` (`reportPath`). Período (datas locais, inclusivas, até 5 anos, com períodos prontos) e hábitos (sem `habit_id`: todos, inclusive os arquivados) ficam na URL e só mudam no "Mostrar relatório"; período ausente ou inválido vira o ano atual até hoje. As informações (pontuação e sucesso/falha, recompensa, punição, gasto e limite, duração, observação e autor) são escolhidas na tela, sem buscar de novo; cada uma só aparece num hábito com o recurso ligado, e a observação começa desligada. A aba do hábito tem o atalho `reportPath({habitIds: [id]})`, e o menu, o link "Relatório".
- **Dados (`src/api/report.js`):** `GET /habits/progress` (em pedaços de até 5 anos e grupos de 100 ids) e as marcações pelo cache do ano dos calendários (`yearMarksQuery`: até 367 dias por chamada, seguindo o `next_cursor`), no máximo 4 chamadas ao mesmo tempo e só nos anos entre a primeira e a última marcação do hábito (`marks_range`). A consulta fica em `reportKeys.data(...)`, embaixo de `habitKeys.all`: mudar a configuração de um hábito (invalidar `habitKeys.all`) e mudar marcações (`afterMarksChanged`) refazem o relatório.
- **Modelo (`src/lib/export/report.js`):** `buildReport(dados, opções, {today})` junta tudo para a tela, o CSV, o JSON e a imagem: marcações só do período (pelo dia local), dias marcados, minutos, gasto, períodos com a meta cumprida do período da criação até o atual (ou o do arquivamento), inclusive, o atual com o valor de agora, como na pontuação (antes da criação e os que ainda não começaram ficam fora; pausa não sai da conta, porque a API não manda as pausas) e o período do limite de custo do fim do relatório.
- **CSV (`csv.js`):** uma linha por marcação (hábito, data, horário, autor, duração, custo, observação); coluna não escolhida, ou de recurso desligado em todos os hábitos, sai. RFC 4180 com BOM e CRLF, cabeçalho no idioma da tela, custo com ponto e 2 casas. Célula que começa com `=`, `+`, `-`, `@`, TAB ou CR ganha um `'` na frente (injeção de fórmula).
- **JSON (`json.js`):** `{version, generated_at, timezone, period, options, habits: [{configuração, marks, periods, cost_periods}]}`. O formato está em [`src/lib/export/schema.md`](frontend/src/lib/export/schema.md), com um JSON Schema que `json.test.js` usa para validar a saída (validador mínimo em `src/test/jsonSchema.js`, sem dependência nova): mudou o formato, mude o schema.
- **Imagem (`image.js`):** PNG 1080×1350 desenhado num `<canvas>`, sem lib: título e período, mapa de calor do período (fração dos hábitos marcados em cada dia; um hábito só usa a cor dele), um bloco por hábito com marcações, metas cumpridas e as informações escolhidas, e o rodapé com a data. Nunca traz emails nem observações. Cores e fonte vêm dos tokens e da paleta lidos em runtime (`readImageTheme`, `getComputedStyle` no `<html>`), então a imagem sai no tema da tela, com o contraste dos tokens; a cor própria de um hábito (`#rrggbb`) entra como está. Todo texto é cortado com "…" na largura (`fitText`, `wrapSegments`); com muitos hábitos a letra diminui até um mínimo, depois somem as linhas de recompensa/punição e, por fim, o resto vira "+N hábitos" (10 hábitos sempre cabem).
- **Compartilhar ou baixar (`share.js`):** `navigator.canShare({files})` decide: com suporte, `navigator.share` (folha de compartilhamento do sistema); sem, download por um link temporário (`downloadBlob`). A tela gera a imagem antes ("Gerar imagem", com prévia) e compartilha num segundo clique, porque o `share` exige um gesto recente. Mudar o relatório, as informações, o idioma ou o tema descarta a imagem pronta. CSV e JSON só baixam.
- **"Exportar tudo" (ETH-38):** o componente `ExportAll` (`src/components/ExportAll`, dentro de `RequireSession`) tem os botões de JSON e CSV, com o estado e o erro. Por baixo, `exportAllFile(queryClient, {timeZone, format: 'json' | 'csv', t})` devolve o File de todos os hábitos (inclusive arquivados), de todas as informações e de todo o período: uma chamada de hoje descobre os hábitos e o `marks_range` de cada um, e o período vai da primeira marcação (ou da criação mais antiga) até hoje. Entregue o File com `downloadBlob(file, file.name)`.
- **Testes:** o jsdom não tem canvas. `drawReport(ctx, ...)` recebe o contexto 2D, e os testes passam um contexto falso (`fakeContext()` em `src/test/report.js`), que mede o texto como fonte monoespaçada e grava as chamadas: conferem o tamanho do canvas (1080×1350, com `getContext` e `toBlob` trocados), que todo texto fica dentro da imagem nos dois idiomas, que desligar uma informação a tira da imagem e que 10 hábitos com um ano de marcações saem inteiros e rápido. `src/test/report.js` também tem `progressItem`, `reportData`, `fullHabit`, `fullMark`, `mockProgressApi`, `imageTheme`, `translator` e `readFileText`.

### Painel de admin e banners

- **Acesso:** o link "Admin" do menu só aparece com `me.is_admin`, e as rotas `/admin/...` ficam dentro de `RequireAdmin`, que manda quem não é admin para a tela inicial. É conveniência: quem garante é o backend (`AdminUser`, 403), e a tela mostra o 403 se ele recusar.
- **Usuários (`/admin`):** quem já abriu o ethos: email, primeiro acesso, fuso, hábitos e marcações, com busca por trecho do email e por datas de primeiro acesso (no fuso do admin, como a API espera) e "carregar mais" pelo cursor. Bloquear, trocar o email, apagar e tornar admin ficam no painel do imago (`/imago/admin`, link no topo da tela).
- **Conteúdo dos hábitos (`/admin/contas/:userId`):** a tela avisa que cada acesso fica registrado na auditoria e só busca depois do clique em "Mostrar o conteúdo" (de novo a cada conta). Cada chamada da API grava `admin_viewed_habits`, então a consulta não busca de novo sozinha (foco, reconexão) e não é cancelada ao desmontar (o StrictMode do dev faria duas chamadas).
- **Banners (`/admin/banners`):** criar, editar (só os campos que mudaram vão no `PATCH`) e encerrar. Contador de 280 por idioma; quebra de linha vira espaço (a API só aceita uma linha). Início e fim em `datetime-local` no fuso do admin, enviados em UTC.
- **Banner ativo:** o `Layout` mostra o `GET /banners/active` em toda tela, inclusive nas públicas, logo abaixo do menu, no idioma da tela e sempre como texto (nunca `dangerouslySetInnerHTML`). Fechar vale para aquele id neste navegador.
- **Testes:** o `server` do MSW já responde `GET /banners/active` sem banner (`activeBanner()` em `src/test/server.js`). Um teste que registra um handler genérico (`http.all(api('/*'))`) passa na frente desse padrão: registre `activeBanner()` antes dele, como em `src/App.test.jsx`.

### Tema, idioma e navegadores

- Tema e idioma usam as chaves do site (`theme` e `i18nextLng`, contrato em [packages/tokens/README.md](../../packages/tokens/README.md)): o que a pessoa escolhe no site vale no ethos e vice-versa. A diferença é que o tema é aplicado por `public/theme-init.js`, e não por script inline como no site.
- Navegadores: o `browserslist` do `package.json` (duas últimas versões de Chrome, Edge, Firefox e Safari, e iOS 16+). O Vite não lê esse campo sozinho, então o `vite.config.js` o converte em `build.target` (`build-targets.js`); o padrão do Vite começaria no iOS 16.4.

### Testes

Os testes rodam no vitest em dois projetos: `app` (jsdom, `src/**/*.test.*`, com MSW, i18n e o setup de `src/test/setup.js`) e `build` (Node, `tests/*.test.js`). `npm test` liga a cobertura e falha abaixo de 80% em `src/lib/`. Toda request sem handler do MSW falha o teste. Todo teste de tela também confere acessibilidade com `vitest-axe`, usando o `axe` de `src/test/axe.js`:

```jsx
expect(await axe(container)).toHaveNoViolations();
```

O `axe` no jsdom não mede contraste. Por isso `src/styles/palette.test.js` calcula o contraste das 12 cores (mínimo 3:1 contra `--bg` e `--surface` dos dois temas, lidos de `packages/tokens/tokens.css`) e confere que os nomes são os do `HabitColor` de `app/models.py`. Também confere que, sobre qualquer cor própria, o texto que `textTone` escolhe (branco ou preto) tem pelo menos 4,5:1, e que `THEME_COLORS` bate com os tokens.

`tests/build.test.js` roda o `vite build` de verdade em pastas temporárias e confere que os tokens de `packages/tokens` entram no CSS do ethos (e que trocar um token, por uma cópia apontada pelo alias `@tokens`, muda o CSS gerado), que o `index.html` carrega o `theme-init.js` no `<head>` sem `defer` e que não há script nem estilo inline.

### E2E

> **PENDENTE (ETH-64).** O E2E abaixo ainda é o do login próprio de antes do imago e está desligado no CI (`E2E_PENDING` no `ethos.yaml`: o job passa com um aviso, sem rodar) até ser refeito contra o imago. Falta: o stack subir também o backend do imago (com o fake SMTP dele) e o nginx de dev em `http://localhost:8080` com os snippets de produção, já que o `vite preview` não põe os `X-User-*`; o `e2e_stack.py` deixar de subir o SMTP falso do ethos (o app não envia mais email) e passar `IMAGO_INTERNAL_URL` e o token de dev; o `login` de `e2e/support.js` entrar por `/imago/entrar` com o código do email do imago, usando contas criadas no imago (o 401 sai do app); `account.spec.js` (exclusão) e os testes de termos e de cookie irem para o E2E do imago; o convite de `sharing.spec.js` exigir que a convidada tenha conta no imago antes; e `playwright.config.js`, `e2e/env.js` e `e2e/vite.config.js` (sem o proxy que tira o `/api/ethos`) seguirem o novo stack.

Testes de ponta a ponta com o [Playwright](https://playwright.dev/) (só Chromium) em `e2e/`, contra o app de verdade: backend, banco, SMTP e o build de produção do front. Ficam fora do `npm test` (o vitest só lê `src/` e `tests/`, e a cobertura só `src/lib/`).

```bash
cd apps/ethos/frontend
npm ci
npx playwright install chromium            # uma vez (no Linux, --with-deps instala as bibliotecas)
(cd ../backend && uv sync)                 # o stack usa as dependências de dev do backend
npm run e2e                                # sobe o stack, roda tudo e derruba
npx playwright test e2e/habits.spec.js --project desktop-light   # um arquivo, um projeto
npx playwright show-report                 # relatório HTML (no CI, o artifact playwright-report)
```

O `playwright.config.js` sobe o stack sozinho (`webServer`) e o derruba no fim, sem reaproveitar servidores que já estejam rodando:

- **Backend** (`backend/tests/e2e_stack.py`, com `uv run --frozen` na pasta do backend): um banco SQLite novo em `e2e/.stack/` (fora do git, apagado e recriado a cada execução), migrado pelo `alembic upgrade head`; o servidor SMTP falso dos testes do backend (`tests/fake_smtp.py`, com STARTTLS e login obrigatórios, como o provedor); e a API pelo uvicorn, com `--root-path /api/ethos`, `APP_ENV=dev`, `EMAIL_BACKEND=smtp` e `APP_URL` igual à origem do front (a checagem de `Origin` vale como em produção). O certificado do SMTP falso vem de uma CA de teste (`trustme`) gravada em `e2e/.stack/`, e o processo confia nela por `SSL_CERT_FILE` (a variável do OpenSSL, lida pelo `ssl.create_default_context()` do `SmtpBackend`): o app manda o email pelo caminho de produção inteiro (STARTTLS com o certificado verificado, login, envio), sem nenhum ajuste no código do app. O teto global de códigos sobe para 10 mil; os limites por email continuam os de produção.
- **Caixa de entrada**: o mesmo processo expõe os emails recebidos pelo SMTP falso em `http://127.0.0.1:47832/emails?to=<endereço>` (`[{to, subject, text}]`, na ordem de chegada; só em 127.0.0.1). É por ela que os testes leem o código de login e o de exclusão, como a pessoa leria o email: nenhum atalho no backend.
- **Front**: `vite build` (o `vite.config.js` de sempre, o mesmo build do deploy) e `vite preview` com `e2e/vite.config.js`, que serve o `dist/` em `/ethos/`, repassa `/api/ethos/*` para o backend tirando o prefixo (como o nginx) e põe nas páginas os headers de segurança do `location /ethos/` de `infra/apps/ethos/nginx.conf`, lidos do próprio arquivo. A fixture `page` dos testes falha com qualquer violação dessa CSP ou erro de JavaScript na página.
- **Portas**: 47830 (front), 47831 (API) e 47832 (caixa de entrada), sempre em `127.0.0.1`; o SMTP pega uma porta livre. Para rodar duas cópias ao mesmo tempo, troque por `E2E_FRONT_PORT`, `E2E_API_PORT` e `E2E_MAIL_PORT` (`e2e/env.js`).
- **Cookie em http**: o cookie `__Host-ethos_session` é `Secure`, e o Chromium trata `http://127.0.0.1` (e `localhost`) como origem segura: guarda e manda o cookie sem https. O teste de login confere o nome, `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/` e a falta de `Domain`. Por isso o stack usa `127.0.0.1`, e não um nome `*.localhost`, sem certificado local e sem mudar o backend.

Projetos: `desktop-light`, `desktop-dark`, `mobile-light` e `mobile-dark` (Desktop Chrome e Pixel 7, com `prefers-color-scheme` claro e escuro), todos em pt-BR, no fuso `America/Sao_Paulo` e com `reducedMotion: 'reduce'` (o CSS desliga as transições, e o axe mede o contraste das cores finais, não de uma no meio da animação). Cada teste roda nos quatro, com contas próprias (`uniqueEmail`), em paralelo.

| Arquivo | O quê |
|---|---|
| `habits.spec.js` | Login pelo código do email (e o aceite dos termos, se o modal aparecer: conta nova já nasce com eles aceitos), o cookie da sessão, criar um hábito, marcar e desmarcar hoje pelos botões do painel do dia, com o dia no calendário (conferindo depois de recarregar). Outro teste marca e desmarca hoje com o duplo clique de verdade no dia (ETH-55): uma escrita por duplo clique, sem texto selecionado e gravada depois de recarregar |
| `sharing.spec.js` | Dois contextos do navegador (`otherPage`): a convidada entra, o dono convida com "Pode marcar", o email do convite chega, ela aceita em Convites, marca hoje, e o dono vê a marcação e o membro |
| `report.spec.js` | Relatório do ano e o "Baixar CSV": nome do arquivo, BOM, cabeçalho em pt, CRLF e a linha da marcação (com aspas no nome com vírgula) |
| `account.spec.js` | Exclusão da conta: o que some, o "Exportar tudo (CSV)", o código de exclusão do email e a confirmação; termina no login com o aviso, o email de conta excluída e a sessão encerrada. O backend aceita 1 código por minuto por email (login e exclusão contados juntos), então o teste pede o código de novo a cada 5 s até o minuto passar (`toPass`, com o 429 na tela enquanto isso): cerca de 1 min por projeto |
| `theme.spec.js` | Sem escolha salva, o tema segue o sistema. O site não sobe no E2E: uma página fora de `/ethos/` no mesmo servidor (mesma origem, como o site em produção) grava `localStorage.theme`, e o ethos abre com esse tema (`data-theme` e a cor de fundo de `packages/tokens/tokens.css`); a troca no menu do ethos grava a mesma chave, que o site lê. Também confere que a página sai com a CSP |

O axe (`@axe-core/playwright`, WCAG 2.1 A e AA, `expectAccessible`) roda nas telas principais (inicial, aba do hábito, compartilhamento, convites, relatório, exclusão e login) em cada projeto, então mede o contraste nos dois temas, o que o `vitest-axe` no jsdom não faz.

Regras: seletores por papel e nome acessível (`getByRole`, `getByLabel`), com os textos em pt; nada de `waitForTimeout` (espere pelo estado da tela ou da API com `expect`, `expect.poll` ou `toPass`); cada teste cria as próprias contas com `uniqueEmail` e não depende de outro. Os passos comuns ficam em `e2e/support.js` (`login`, `createHabit`, `todayCell`/`selectToday`/`toggleToday`, `goByMenu`/`openMenu`, que abre o menu no celular, `inbox`/`codeFromEmail` e `expectAccessible`).

## CI

O workflow [ethos.yaml](../../.github/workflows/ethos.yaml) roda em PRs e em push na `main` que tocam `apps/ethos/**`, `packages/**`, o próprio workflow ou os arquivos de infra que os testes leem (`infra/apps/ethos/app.conf`, `infra/apps/ethos/app.env`, `infra/apps/ethos/nginx.conf`, `infra/scripts/snapshot.sh`, `infra/scripts/restore-test.sh`, `infra/lib/backups.sh`, `infra/config.env`, `infra/lib/common.sh`, `infra/lib/packages.sh` e `.github/scripts/check-python-version.sh`). Em PRs, só as checagens:

- backend: `uv lock --check`, `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest --cov` e 100% de cobertura nos módulos de `FULL_COVERAGE`;
- frontend: `npm ci`, `npm run lint`, `npm run build` e `npm test`;
- E2E: `uv sync --frozen` no backend, `npm ci`, o Chromium do Playwright (em cache por versão; as bibliotecas do sistema saem do apt a cada execução) e `npm run e2e` (ver "E2E", acima). Em falha, o relatório HTML e os traces ficam no artifact `playwright-report` por 7 dias (`npx playwright show-report <pasta>` ou `npx playwright show-trace <trace.zip>`). Num rollback para um commit anterior ao E2E, o job passa sem rodar nada. **Hoje desligado** (`E2E_PENDING`, ver "E2E"): passa com um aviso;
- scripts do deploy ([packages/deploy/](../../packages/deploy/README.md)): `shellcheck` (com o `backend/tests/vm-restore.sh`), `test-deploy-scripts.sh` (limpeza de assets, migrações do rollback e recusa de nome de aplicação inválido) e `test-vm.sh` (com o nome `ethos` e o ensaio `backend/tests/vm-restore.sh`), que roda o `vm.sh` num Ubuntu 24.04 com o uv e o Python instalados pelas funções do provision: `.venv`, migração e `/health` como `app-ethos`, backup e restart. Depois, o `vm-restore.sh` ensaia o [infra/RESTORE.md](../../infra/RESTORE.md) com o banco populado pelo `seed`: backup, uma exclusão de verdade (`delete_user_data`) com a linha no journald, o ensaio numa cópia, o restore do `pre-deploy-<sha>.db` e o `reapply-deletions` pelo `systemd-run` com linhas do login antigo, duas vezes. No fim, o `restore-test.sh` do `backup-verify.yaml` com esse banco e um Litestream falso.

Em push na `main` e no `workflow_dispatch`, o workflow também faz o deploy.

## Deploy

O job `deploy` só começa depois que as checagens (backend, frontend, E2E e scripts) passam: um teste quebrado para o workflow antes de qualquer passo na VM. Ele roda em push na `main` que muda o que vai para a VM (`apps/ethos/backend/`, `apps/ethos/frontend/`, `packages/`, com os scripts do deploy, ou o próprio workflow). Um push que só muda arquivos lidos pelos testes (os de `infra/`, este README) roda as checagens sem deploy. Em PRs, nunca há deploy.

### Antes do primeiro deploy

- **Variável `ETHOS_URL`** no GitHub: Settings → Secrets and variables → Actions → Variables → New repository variable, com o endereço do site, só `https://<domínio>`, sem caminho e sem barra no fim (hoje, `https://manasomali.com`). O health check chama `$ETHOS_URL/api/ethos/health`. Nenhum domínio fica fixo no workflow: trocar de domínio é trocar a variável. Sem ela, o workflow falha logo no começo (job "Preparar o deploy"), sem tocar na VM.
- **Secrets**: os mesmos do site e do Infra, já cadastrados no repositório: `REMOTE_HOST`, `REMOTE_USER`, `SERVER_SSH_KEY` e `SSH_KNOWN_HOSTS`. O job usa o environment `production`, como o Infra.
- **Infra provisionado**: o workflow Infra precisa ter rodado com `infra/apps/ethos/` e a linha `ethos` do `databases.txt` (unit `app-ethos`, pastas, banco, uv e Python). O primeiro passo do deploy confere e, se faltar algo, falha pedindo para rodar o Infra.

### Os passos

| # | Passo | Onde |
|---|---|---|
| 1 | Checagens (needs) | runner |
| 2 | `vm.sh check`: unit `app-ethos.service`, `/opt/apps/ethos` e `/var/www/ethos` graváveis, uv, o Python de `.python-version`, `sqlite3`, banco e pasta de backup | VM |
| 3 | rsync de `backend/` para `/opt/apps/ethos/` com `--delete`, pelas regras de `packages/deploy/backend.rsync-filter`: a `.venv` fica intocada; `tests/`, caches, `.env` e bancos locais não sobem | runner → VM |
| 4 | `vm.sh install`: `uv sync --frozen --no-dev --no-build --compile-bytecode` com o Python de `/opt/uv/python` (nunca baixa um), e `compileall` de `app/` e `migrations/` | VM |
| 5 | `vm.sh backup <sha>`: `sqlite3 .backup` como `app-ethos` em `/var/backups/sqlite/ethos/pre-deploy-<sha>.db` | VM |
| 6 | `vm.sh restart`: `systemctl restart app-ethos`; o `ExecStartPre` roda `alembic upgrade head` | VM |
| 7 | Health check: `$ETHOS_URL/api/ethos/health`, 10 tentativas, 3 s entre elas | runner |
| 8 | rsync do `dist/` (o mesmo build que passou nos testes) para `/var/www/ethos/`, **sem** `--delete`, com o `index.html` por último | runner → VM |
| 9 | `clean-assets.sh`: apaga de `/var/www/ethos/assets/` os arquivos com mais de 7 dias que não estão no build atual | VM |

- Os scripts são os de [packages/deploy/](../../packages/deploy/README.md), comuns às aplicações, com o nome `ethos` como parâmetro. Os passos na VM vão pelo SSH como `bash -s -- ethos <comando> < packages/deploy/vm.sh`: nada fica instalado lá. O usuário de deploy (com sudo sem senha) roda como `app-ethos` só o que lê o banco e grava o backup, e como root só o `systemctl`.
- **Bytecode**: o projeto não é instalado na `.venv` (não tem `build-system`), então o `--compile-bytecode` do uv só cobre os pacotes. O `compileall` gera o de `app/` e `migrations/`, porque o `app-ethos` não grava na pasta do código (e a unit roda com `PYTHONDONTWRITEBYTECODE`).
- **Backup**: o mesmo método do `snapshot.sh` (consistente com o WAL e com o Litestream), gravado primeiro como `.partial`, conferido com `integrity_check` e só então renomeado. Se o commit já tem um `pre-deploy-<sha>.db` (re-run, rollback para um commit já publicado), o primeiro fica, porque é o de antes da migração dele, e o novo ganha a hora no nome (`pre-deploy-<sha>-<AAAAMMDDTHHMMSSZ>.db`). Retenção: o `snapshot.sh` diário apaga os `*.db` com mais de 7 dias dessa pasta, estes inclusive. Cada deploy guarda uma cópia inteira do banco por 7 dias.
- **Migração quebrada**: cada `upgrade` roda numa transação só, então o banco fica na revisão anterior. O serviço não sobe (`StartLimitBurst` da unit: 5 tentativas em 5 min), o `restart` falha, o job para no passo 6, e o front anterior continua no ar, falando com uma API fora do ar. Corrija com um commit novo ou faça o rollback. O log do Actions não mostra o journal (o repositório é público): na VM, `journalctl -u app-ethos -n 50 --no-pager`.
- **Front sem `--delete`**: o nginx (`infra/apps/ethos/nginx.conf`) serve o `index.html` com `no-cache` e os arquivos de `assets/` (nome com hash) com cache de um ano e `immutable`. Uma aba aberta com a versão anterior continua carregando as telas dela, porque os assets antigos ficam por 7 dias; o `index.html` novo só entra depois de todos os assets que ele carrega. A idade conta a partir do último deploy que usou o arquivo: o rsync atualiza a data dos que continuam no build. Arquivos fora de `assets/` (`locales/`, `theme-init.js`) não têm hash e são sobrescritos no deploy.
- **Ordem**: o backend novo entra antes do front novo, então o front nunca fica no ar com um backend mais velho que ele. Por isso a API precisa continuar atendendo o front anterior (mudanças compatíveis).
- **Concorrência**: o job usa o grupo `ethos-deploy`, nunca dois deploys ao mesmo tempo. Os runs da `main` também andam um de cada vez e na ordem (grupo `ethos-checks-refs/heads/main`): um push que chega durante um deploy espera, e se chegarem vários, o GitHub cancela os pendentes do meio e publica só o mais novo. O grupo `infra` fica de fora (o GitHub mantém só um run pendente por grupo e cancelaria um deploy na fila atrás de um provision).

### Rollback

Actions → Ethos → Run workflow, a partir da `main`, com o SHA completo do commit a publicar (o anterior ao problema). O workflow só aceita um commit que esteja na `main`, roda as checagens desse commit (os módulos de `FULL_COVERAGE` que ainda não existiam nele são pulados) e faz os mesmos 9 passos com o código e o build dele. Os scripts do deploy são sempre os da `main`.

- **Migrações não voltam**: o rollback não roda `downgrade`. Como as migrações são só aditivas, o código anterior funciona com o banco novo. Se o banco já está numa revisão que o commit antigo não conhece (rollback para antes de uma migração aplicada), o `alembic upgrade head` dele pararia com "Can't locate revision". Por isso o passo `keep-migrations.sh` lê a revisão do banco e leva junto, da `main`, os arquivos de migração que faltam até ela: o head do commit vira a revisão do banco e o upgrade não faz nada. Uma migração que falhou não fica aplicada e não é levada.
- **Cor própria (migração 0004, ETH-49)**: o código de antes dela só conhece os nomes da paleta e responde 500 ao ler um hábito com cor própria. Antes de um rollback para antes dela, troque essas cores na VM (`UPDATE habits SET color = 'teal' WHERE color GLOB '#*';`, a mesma sugestão do `downgrade`, que é recusado enquanto houver cor própria).
- **Login pelo imago (migração 0005, ETH-64)**: não é aditiva, e o código de antes dela não roda com o banco migrado (não há mais `users`). Um rollback para antes dela é: rollback do código e restore do `pre-deploy-<sha>.db` do deploy que aplicou a 0005, nessa ordem, como em "Dados estragados" abaixo, e o login volta a ser o do ethos (o imago precisa voltar junto ao estado de antes). O que mudou no ethos depois desse deploy se perde.
- **Dados estragados por uma migração**: faça o rollback do código e depois restaure o `pre-deploy-<sha>.db` do deploy que a aplicou, nessa ordem, seguindo o [infra/RESTORE.md](../../infra/RESTORE.md#restaurar-o-banco-de-uma-app-ethos) (o rollback roda duas vezes, e o `alembic upgrade head` manual fica de fora, para a migração quebrada não rodar de novo).
- Um push novo na `main` depois do rollback publica a `main` de novo.

### Regras

- **Migrações só aditivas**: criar tabela ou coluna (anulável ou com default). Remover ou renomear só num deploy seguinte, quando nenhum código no ar (nem o de um rollback) usa mais aquilo. É o que permite o rollback sem `downgrade` e o código anterior rodando com o banco novo durante o deploy. A única exceção é a 0005 (a passagem do login para o imago, ver "Migrações"), cujo rollback exige o `pre-deploy-<sha>.db`.
- **Nunca apague nem renomeie um arquivo de migração já publicado**: o rollback busca na `main` as migrações que o banco já tem.
- **Mudança de infra entra num PR anterior ao do app**: unit nova, variável nova no `app.env`, porta, versão do Python. O Infra e o ethos rodam em paralelo, sem ordem garantida entre eles; o deploy confere a unit, as pastas e o Python e falha com mensagem clara se o provision ainda não rodou.

## Go-live

Checklist manual de produção, antes de divulgar o ethos. Os comandos com `ssh` rodam a partir de uma máquina com acesso à VM (`<REMOTE_USER>@<REMOTE_HOST>`, os mesmos dos secrets do deploy); `voce@example.com` é o seu email. Nunca cole um código, token ou cookie de produção em issue, PR ou chat. Copie a lista para o PR de go-live e marque cada item com o resultado.

- [ ] **Login, email, admin, cookie e rate limit do login**: desde a ETH-64 são do imago (o checklist dele está no [README do imago](../imago/README.md)). No ethos, confira que `https://manasomali.com/ethos/` sem login leva a `/imago/entrar?next=/ethos/`, que o antigo `https://manasomali.com/ethos/entrar` leva a `/imago/entrar`, e que um admin do imago vê o link "Admin" no menu do ethos.
- [ ] **Memória do `app-ethos` abaixo de 150M** (a unit tem `MemoryMax=150M`: acima disso o kernel mata o processo). Depois de um uso normal (alguns hábitos, marcações, relatório e export), na VM:

  ```bash
  systemctl status app-ethos --no-pager          # linha "Memory: ... (max: 150.0M ...)"
  systemctl show app-ethos -p MemoryCurrent -p MemoryPeak -p MemoryMax -p NRestarts
  journalctl -u app-ethos --since today --no-pager | grep -iE 'oom|killed' || echo "sem OOM"
  ```

  `MemoryCurrent` e `MemoryPeak` em bytes, abaixo de 157286400 (150M), com folga; `NRestarts=0`.
- [ ] **Monitor externo gratuito do health check, com aviso por email.** Por exemplo, no [UptimeRobot](https://uptimerobot.com/) (plano Free): Add New Monitor → tipo HTTP(s) (ou Keyword, com `"status":"ok"`), URL `https://manasomali.com/api/ethos/health`, intervalo de 5 minutos, alerta para o seu email. Confira o aviso com "Test notification" (ou parando o serviço por um minuto: `sudo systemctl stop app-ethos`, esperar o email, `sudo systemctl start app-ethos`). O endpoint devolve `{"status":"ok"}` com 200 depois de um `SELECT 1` no banco (503 `database_unavailable` sem ele; 502 do nginx com o serviço parado).
- [ ] **Requests do Object Storage, uma semana depois do go-live.** O Always Free inclui 50 mil requisições de API do Object Storage por mês, e o Litestream com `LITESTREAM_SYNC_INTERVAL=1m` (em `infra/config.env`) gasta perto de 45 mil com escrita contínua. No console da OCI: Observability & Management → Monitoring → Service Metrics, compartimento do bucket, namespace `oci_objectstorage`, métrica `AllRequests`, estatística Sum, intervalo de 1 dia, filtro `resourceDisplayName` = o bucket (`S3_BUCKET`), nos últimos 7 dias. Projeção do mês = soma dos 7 dias × 30 / 7. Se passar de 40 mil (80% da cota), suba o intervalo num PR do Infra (`LITESTREAM_SYNC_INTERVAL=5m` em `infra/config.env`; o provision reinicia o Litestream; o intervalo é a perda máxima de dados num desastre) e meça de novo uma semana depois. Anote no PR de go-live o total da semana e a projeção.
- [ ] **Lighthouse com acessibilidade ≥ 90.** No Chrome, numa janela anônima: DevTools → Lighthouse → Mode "Navigation", categoria Accessibility, Device "Mobile" e depois "Desktop", em `https://manasomali.com/ethos/ajuda`. Para as telas com login (`/ethos/`, a aba de um hábito, `/ethos/relatorio`), entre antes pelo `/imago/entrar` na mesma janela e desmarque "Clear storage" nas opções do Lighthouse, senão ele mede o login do imago. Pela linha de comando, só as telas públicas:

  ```bash
  npx lighthouse https://manasomali.com/ethos/ajuda --only-categories=accessibility --view                    # celular (padrão)
  npx lighthouse https://manasomali.com/ethos/ajuda --only-categories=accessibility --preset=desktop --view
  ```

  Anote a nota de cada tela, nos dois temas (o ícone de tema do menu). O E2E já roda o axe nas telas principais nos dois temas e nos dois tamanhos (ver "E2E"); o Lighthouse confere o site publicado.

## Migração

O ethos foi feito para mudar de hospedagem, de domínio ou de banco sem mexer no código do app: toda a config vem do ambiente (`app/config.py`), o banco é um arquivo SQLite e o que é da VM fica fora de `apps/ethos/`, em `infra/apps/ethos/`. Esta seção diz o que muda em cada tipo de migração. O restore de um backup (inclusive numa VM nova) está no [infra/RESTORE.md](../../infra/RESTORE.md).

### Variáveis de ambiente

As do app são as de `Settings` em `app/config.py`, as mesmas do `.env.example` (que é o `infra/apps/ethos/app.env` mais o `INTERNAL_API_TOKEN`; um teste confere). Em produção, a unit lê `/etc/infra/apps/ethos.env` (do `app.env`, versionado) e `/etc/infra/internal/ethos.env` (o token, gerado pelo provision na VM).

| Variável | Produção hoje | Hospedagem nova | Domínio ou caminho novo | Banco movido |
|---|---|---|---|---|
| `APP_ENV` | `prod` | — | — | — |
| `APP_URL` | `https://manasomali.com/ethos` | — | troca (ver abaixo) | — |
| `DATABASE_PATH` | `/var/lib/sqlite/ethos/app.db` | o caminho na máquina nova | — | o caminho novo |
| `IMAGO_INTERNAL_URL` | `http://127.0.0.1:3003` | a origem da API interna do imago vista da máquina nova | — | — |
| `INTERNAL_API_TOKEN` | gerado na VM (`/etc/infra/internal/ethos.env`) | o mesmo valor no ethos e no `IMAGO_APP_TOKENS` do imago | — | — |
| `MAX_HABITS_PER_USER`, `MAX_MARKS_PER_DAY`, `MAX_NOTE_LENGTH`, `MAX_GUESTS_PER_HABIT`, `MAX_SHARED_HABITS_PER_USER`, `MAX_INVITES_PER_DAY` | os do plano | — | — | — |

Fora do app, mas também mudam numa migração:

- `PORT` (`3001`) e `PYTHON_VERSION` em `infra/apps/ethos/app.conf`: a porta do uvicorn (o provision troca o `__PORTA__` da unit e do nginx) e o Python que o provision instala, igual ao `backend/.python-version`.
- `PYTHONUNBUFFERED=1` e `PYTHONDONTWRITEBYTECODE=1` na unit: os logs saem na hora, e o `app-ethos` não tenta gravar bytecode na pasta do código.
- Variável `ETHOS_URL` do GitHub (`https://manasomali.com`): o health check do deploy. Troca com o domínio.
- Secrets do deploy (`REMOTE_HOST`, `REMOTE_USER`, `SERVER_SSH_KEY`, `SSH_KNOWN_HOSTS`): trocam com a hospedagem. Os do Litestream (`LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY`) e as variáveis `S3_ENDPOINT`, `S3_BUCKET` e `OCI_REGION` trocam com o lugar dos backups.

### Hospedagem

- **Outra VM, com o `infra/`**: o caminho de "VM perdida" do [infra/RESTORE.md](../../infra/RESTORE.md#vm-perdida): DNS, secrets, certificado, workflow Infra, restore do banco e deploy do ethos. Antes de desligar a VM antiga, pare nela o `app-ethos` e o `ethos-alerts.timer` e espere o Litestream enviar o último estado (`LITESTREAM_SYNC_INTERVAL`, 1 min), ou leve um `.backup` (ver "Banco"). Guarde o journal dela (`sudo journalctl -u app-ethos -o cat > exclusoes.log`) até o ethos estar no ar no destino: é a entrada do `reapply-deletions` se for preciso restaurar um backup de antes da passagem para o imago (as exclusões de depois estão no journal do imago).
- **Outra hospedagem, sem o `infra/`**: o que a VM faz hoje e precisa existir lá:
  - o Python de `backend/.python-version` e `uv sync --frozen --no-dev` (o `uv.lock` fixa tudo);
  - `alembic upgrade head` antes de subir (a unit roda no `ExecStartPre`: migração que falha não deixa o app subir);
  - `uvicorn app.main:app --workers 1 --root-path /api/ethos`, escutando só em 127.0.0.1. Um worker só (SQLite, um processo escrevendo). Os headers `X-User-*` só são confiáveis porque só o proxy chega nele;
  - o imago na mesma origem (o login, a conta e o envio dos emails) e a API interna entre os dois, com o token;
  - um proxy na frente, na mesma origem do front: pergunta ao imago quem é o usuário em cada request de `/api/ethos/` (`auth_request`) e repassa a resposta nos `X-User-*`, sempre definidos por ele (os do navegador somem); tira o prefixo `/api/ethos`; responde 404 para `/api/ethos/internal/`; serve o `frontend/dist/` em `/ethos/`, com o `index.html` de fallback e sem cache e os `assets/` com cache longo; põe os headers de segurança (CSP sem `'unsafe-inline'`, `nosniff`, `Referrer-Policy`, HSTS). O modelo é `infra/apps/ethos/nginx.conf` com o `nginx-http.conf`;
  - um job de hora em hora que rode `python -m app.cli run-alerts` (`infra/apps/ethos/ethos-alerts.service` e `.timer`);
  - uma pasta gravável para o banco (o WAL cria `app.db-wal` e `app.db-shm` ao lado), backup contínuo (Litestream) e snapshot diário;
  - o stdout e o stderr do app guardados de forma persistente (journald ou equivalente), e o journal antigo do `app-ethos`: as linhas `conta <id> excluída` do login de antes do imago são o que o `reapply-deletions` lê depois de restaurar um backup daquela época.

### Domínio ou caminho

- `APP_URL` é a origem aceita contra CSRF (`app/identity.py`: todo POST, PUT, PATCH e DELETE precisa de um `Origin` igual a esquema + host + porta do `APP_URL`) e a base dos links dos emails (a tela de alertas é `APP_URL` + `/habits/{id}/alerts`). Com o domínio errado, nenhuma escrita passa (403) e os links apontam para o lugar errado. Mude junto com o `ETHOS_URL` do GitHub e o certificado do domínio novo.
- O ethos não tem cookie: a sessão é o cookie do imago, preso ao host, e o `auth_request` do nginx precisa do imago na mesma origem. Trocar de domínio desloga todo mundo no imago. Um 301 do domínio antigo para o novo mantém os links dos emails já enviados.
- A CSP do nginx só usa `'self'`: não cita o domínio e não muda, desde que front, API e imago fiquem na mesma origem. A API não tem CORS: separar front e API em origens diferentes exigiria CORS, `connect-src` e outro desenho do login. Não separe.
- O tema e o idioma vêm das chaves `theme` e `i18nextLng` do `localStorage`, compartilhadas com o site porque estão na mesma origem ([packages/tokens/README.md](../../packages/tokens/README.md)). Num domínio separado do site, a escolha deixa de valer entre os dois, e só.
- O caminho (`/ethos/` e `/api/ethos/`) está fixo em vários lugares, que mudam juntos: o `base` do `frontend/vite.config.js`, `BASENAME` em `frontend/src/paths.js`, `API_BASE` em `frontend/src/lib/api.js`, o `--root-path /api/ethos` da unit, as `location` de `infra/apps/ethos/nginx.conf` e o caminho do `APP_URL`. O backend só conhece o prefixo pelo `--root-path`: as rotas ficam na raiz (`/health`, `/me`...). O `next` do login (`/imago/entrar?next=/ethos/...`) sai do caminho da página, e os links do imago (`IMAGO_PATHS`) supõem o imago em `/imago/` na mesma origem.

### Banco

- **SQLite, um arquivo só** (`DATABASE_PATH`), em WAL. Exportar com o app no ar é seguro pelo `.backup` (consistente com o WAL; `cp` do arquivo não é), como o deploy faz:

  ```bash
  sudo -u app-ethos sqlite3 /var/lib/sqlite/ethos/app.db ".backup '/var/backups/sqlite/ethos/export.db'"
  sudo -u app-ethos sqlite3 /var/backups/sqlite/ethos/export.db 'PRAGMA journal_mode=DELETE; PRAGMA integrity_check;'
  ```

  Para não perder escritas, pare antes o `app-ethos` e o `ethos-alerts.timer`. Importar: com o app parado no destino, ponha o arquivo em `DATABASE_PATH`, com dono o usuário do serviço, e rode `PRAGMA integrity_check; PRAGMA journal_mode=WAL;` e `alembic upgrade head`. Se o arquivo for mais velho que a última exclusão de conta, rode o `reapply-deletions` com o journal da origem antes de abrir.
- **Litestream**: replica cada banco para `<S3_BUCKET>/<nome>/` (`infra/lib/backups.sh`, retenção de 168 h). Uma máquina nova recupera dali com `litestream restore` (RESTORE.md). Outro bucket ou outro provedor S3 é config do Infra (`S3_ENDPOINT`, `S3_BUCKET`, `OCI_REGION` e os secrets `LITESTREAM_*`), sem mudança no app. A replicação para quando o banco sai do `databases.txt`.
- **Outro banco (Postgres, por exemplo)**: não é só trocar a variável. O app usa recursos do SQLite: `BEGIN IMMEDIATE` e os PRAGMAs de `app/db.py`, `json_extract`, `json_set` e `instr` na exclusão de conta, a coluna gerada `audit_log.mark_id` e o modo batch do Alembic. Os dados saem com `sqlite3 app.db .dump` (SQL), mas esses pontos e as migrações precisam ser reescritos antes.

### Tirar o ethos do monorepo

O ethos não importa código do site. O que ele usa fora de `apps/ethos/` (conferido com `grep -rln ethos` fora de `apps/ethos/` e `grep -rn '\.\./\.\./' apps/ethos`):

| Fora de `apps/ethos/` | Quem usa | Ao tirar |
|---|---|---|
| `packages/tokens/tokens.css` (e o contrato do `localStorage` em `packages/tokens/README.md`) | `frontend/vite.config.js` (alias `@tokens` e `server.fs.allow`), `src/index.css`, `src/lib/customColor.js` (`?raw`), `src/styles/palette.test.js`, `tests/build.test.js` e `e2e/theme.spec.js` | copiar para o repo novo e apontar o alias e os dois testes para a cópia |
| `infra/apps/ethos/` (`app-ethos.service`, `ethos-alerts.service`, `ethos-alerts.timer`, `nginx.conf`, `nginx-http.conf`, `app.conf`, `app.env`) | o provision (units, nginx e `/etc/infra/apps/ethos.env`); `backend/tests/test_env_files.py` e `frontend/src/lib/help.test.js` leem o `app.env`; `frontend/e2e/vite.config.js` lê os headers do `nginx.conf`; o `check-python-version.sh` lê o `app.conf` | levar como a config de deploy do repo novo e apontar os testes para a cópia |
| `infra/databases.txt` (linha `ethos`) e a tabela de portas do `infra/README.md` | usuário `app-ethos`, pasta do banco, Litestream e snapshots; `check-ports.sh` | no monorepo, sair só depois de o banco estar no destino (tirar a linha mantém os dados, mas sem backup) |
| `infra/scripts/snapshot.sh`, `infra/scripts/restore-test.sh`, `infra/lib/backups.sh`, `infra/lib/common.sh`, `infra/lib/packages.sh`, `infra/config.env` | lidos pelos testes: `help.test.js` (prazos dos backups) e `packages/deploy/test-vm.sh` (uv, Python, snapshot e restore-test) | trocar por constantes ou cópias no repo novo |
| `packages/deploy/` (`vm.sh`, `keep-migrations.sh`, `clean-assets.sh`, `backend.rsync-filter` e os testes) | o deploy e o job de scripts do `ethos.yaml`; o `test-vm.sh` lê o `backend/tests/vm-restore.sh` | copiar para o repo novo (o nome da aplicação continua como parâmetro) |
| `apps/imago/` (o login, a conta, os termos e o envio dos emails) | todo request com login (o `auth_request` do nginx), `backend/app/imago_client.py` e a API interna (`/internal/*`, com o token de `/etc/infra/internal/ethos.env`) | o ethos não funciona sozinho: levar um imago na mesma origem, ou trocar a identidade (`app/identity.py`) por outra |
| `.github/workflows/ethos.yaml` | CI e deploy (os `paths` citam os arquivos de `infra/` acima) | copiar, trocando `apps/ethos/` pela raiz |
| `.github/scripts/check-python-version.sh` | `ethos.yaml` e `infra.yaml` | levar, ou comparar direto com a config de deploy |
| `.github/scripts/test-provision-apps.sh`, `test-provision-nginx.sh` e `check-ports.sh` | `infra.yaml`: testam as units, as rotas e a porta do ethos | no monorepo, tirar a parte do ethos quando `infra/apps/ethos/` sair |
| `site/` | nenhum código; mesma origem (as chaves `theme` e `i18nextLng`), e o `server` de `infra/nginx/site.conf` inclui o `apps.d` | nada a levar; num domínio próprio, o ethos precisa de um `server` seu no nginx |
| `.claude/launch.json` e `CLAUDE.md` | dev server e instruções | atualizar |

Passos:

1. `git subtree split -P apps/ethos -b ethos-sozinho` e um repo novo a partir desse branch (o histórico vem junto).
2. No repo novo: `packages/tokens`, `packages/deploy`, a config de `infra/apps/ethos/`, o workflow e o script do Python, com os caminhos ajustados; os testes que leem `infra/` passam a ler as cópias.
3. Migrar o banco ("Banco", acima) e o deploy, com o app antigo parado.
4. No monorepo, com o ethos no ar no destino: tirar `apps/ethos/`, `infra/apps/ethos/` (o provision desliga as units e tira os snippets do nginx, com cópia em `/var/backups/infra`, sem apagar código nem dados), a linha do `databases.txt`, a da porta no `infra/README.md`, o `ethos.yaml` e a parte do ethos de `test-provision-apps.sh`, `test-provision-nginx.sh` e `.claude/launch.json`. Os dados em `/var/lib/sqlite/ethos/` ficam na VM até serem apagados à mão.
