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
uv run coverage report --fail-under=100 --include=app/audit.py,app/auth/deletion.py,app/auth/deps.py,app/auth/origin.py,app/auth/security.py,app/auth/service.py,app/habits/access.py,app/habits/scoring.py,app/habits/service.py,app/history/service.py,app/marks/schemas.py,app/marks/service.py,app/pagination.py,app/progress/service.py,app/retention.py,app/score.py,app/sharing/quota.py,app/sharing/service.py   # depois do pytest
```

Alguns módulos precisam de 100% de cobertura (linhas e ramos). A lista fica na variável `FULL_COVERAGE` do passo "Cobertura de 100% nos módulos críticos" do CI, que confere cada um com o `coverage report` acima.

Os testes não precisam de `.env`: as fixtures de `tests/conftest.py` montam a config com um SQLite em arquivo temporário (`settings`, `make_settings`, `engine`, `db_session`, `app`, `client`, `make_client`, `smtp_server`, `make_smtp_server`, `outbox`, `make_account`). O banco de teste já vem com o schema completo: as migrações rodam uma vez por execução do pytest (`migrated_template`) e cada teste recebe uma cópia (`database`). Para testar migrações, `make_alembic_config(caminho)` devolve a config do Alembic apontando para outro banco. `tests/factories.py` tem `new_user`, `new_habit`, `new_member`, `new_invite`, `new_mark`, `new_pause`, `new_alert`, `save` e `count` para montar dados.

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
- `audit_log.mark_id` é uma coluna gerada (VIRTUAL, migração 0002) com o `details.mark_id` dos eventos de marcação, indexada para o histórico de uma marcação. O app nunca a grava: o SQLite a calcula do `details`.
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

### Sessão, CSRF e conta

- `app/auth/deps.py` (100% de cobertura): quem é o usuário do request. Todo endpoint do app usa `CurrentUser` (sessão válida e a versão atual dos termos aceita; sem o aceite, 403 `terms_not_accepted`); rota de admin usa `AdminUser` (`is_admin`, lido do banco a cada request; usuário comum leva 403 `forbidden`). `CurrentUserAnyTerms` (sem conferir os termos) é só para `/auth/me`, `/auth/me/terms` e `/auth/me/delete/request`, e `CurrentSession` (sem renovar) só para o logout e o `DELETE /auth/me`. Sem cookie, token desconhecido, sessão vencida ou conta inativa: 401 `unauthorized`.
- Renovação: a sessão vale 60 dias desde o último uso. `last_seen_at` e `expires_at` são gravados no máximo uma vez por dia por sessão (`RENEWAL_INTERVAL`), num `write_transaction` que só abre quando precisa e repete a conferência dentro dele; nessa hora o cookie sai de novo com o `Max-Age` cheio. O cookie renovado só vai na resposta quando o endpoint devolve dados (não um `Response` pronto).
- `app/auth/origin.py` (100% de cobertura): proteção contra CSRF. Um middleware recusa com 403 `forbidden` toda request que não seja GET, HEAD ou OPTIONS sem exatamente um header `Origin` igual à origem do `APP_URL` (`settings.app_origin`: esquema + host + porta se não for a padrão). Vale para todas as rotas, inclusive as do login, e roda antes de ler o corpo. Nos testes, o `make_client` manda esse `Origin` em todo request; `make_client(app, origin=False)` não manda.
- Endpoints: `POST /auth/logout` (apaga a sessão atual e o cookie, evento `logout`), `POST /auth/logout-all` (apaga todas as sessões do usuário, evento `logout_all` com `{"sessions": n}`), `GET /auth/me` (id, email, fuso, idioma, `is_admin`, versão dos termos aceita, versão atual e `terms_pending`), `PATCH /auth/me` com `{timezone?, locale?}` (fuso IANA desconhecido: 422 `invalid_timezone`; `null` ou campo desconhecido: 422; evento `profile_updated` com o que mudou) e `POST /auth/me/terms` com `{terms_version}` (a versão que a pessoa leu; diferente da atual: 409 `conflict`; evento `terms_accepted`). O fuso só muda pelo `PATCH /auth/me`.

### Hábitos

O pacote `app/habits/` tem a configuração dos hábitos e o acesso a eles:

- `access.py` (100% de cobertura): `get_habit_access(session, habit_id, user_id)` devolve o hábito e o papel de quem pede (`owner`, `editor` ou `viewer`) ou 404 `not_found`, igual para id que não existe e para hábito de outra pessoa (a API nunca revela que ele existe). `require_owner(access)` dá 403 `forbidden` para editor e viewer. `require_writable(access)` dá 409 `habit_archived` em hábito arquivado, que é só leitura (confira o papel antes: quem não pode escrever recebe 403). `HabitId` é o id no caminho (1 até o maior inteiro do SQLite; fora disso, 422).
- `scoring.py` (100% de cobertura): converte os modelos para as dataclasses do `score.py` e lê marcações e pausas em lote. `evaluate_habits(session, hábitos, fuso, now=...)` calcula a pontuação de vários hábitos com duas consultas.
- `schemas.py`: os tamanhos e formatos do plano. Nome de 1 a 60 caracteres, descrição até 500, recompensa e punição até 140, sigla de 1 a 4 letras (A-Z) ou números salva em maiúsculas, cor da paleta de 12 nomes. Espaços nas pontas saem, texto opcional vazio vira `null`, caracteres de controle e de direção do texto são recusados, booleanos e inteiros são estritos e campo desconhecido é recusado.
- `service.py` (100% de cobertura): as regras. `check_config` confere a configuração inteira depois de cada mudança: N ≥ 1 em `min` e `exact` e N ≥ 0 em `max`, teto de N (dias do período no toggle: 7, 28 ou 365; `MAX_MARKS_PER_DAY` × dias com várias por dia), minutos com a duração ligada, valor do custo no nível hábito, limite de custo e período juntos, e recompensa e punição só com a pontuação ligada. Desligar um recurso não apaga o valor dele, que volta ao religar. `MAX_HABITS_PER_USER` conta os ativos e pausados do dono dentro da transação da criação e do desarquivamento (409 `habit_limit_reached`).
- Pausar e arquivar (só o dono; pedir o estado atual não muda nada nem grava evento): pausar abre um intervalo em `habit_pauses` e retomar o fecha; fora do arquivo, `paused` tem exatamente uma pausa aberta (o índice único `uq_habit_pauses_open` impede duas). Pausado continua marcável, e a pontuação ignora os períodos com pausa. Arquivar grava `archived_at` (a pontuação congela nessa data) e deixa o hábito só leitura: editar, pausar e retomar dão 409 `habit_archived`; apagar continua. A pausa aberta de um hábito pausado fica aberta no arquivo. Desarquivar volta ao status de antes: `paused` se há pausa aberta; senão `active`, e o tempo arquivado vira a pausa fechada `[archived_at, agora)`, para não contar como meta não cumprida.
- `routes.py`: `GET /habits` (os do usuário e os compartilhados com ele, com o `role`; ativos e pausados, ou só os arquivados com `?archived=true`), `POST /habits` (201), `GET /habits/{id}`, `PATCH /habits/{id}` (mudança parcial; `null` só nos campos opcionais) `DELETE /habits/{id}` (204) e `POST /habits/{id}/pause`, `/resume`, `/archive` e `/unarchive` (sem corpo, devolvem o hábito). Editar, apagar, pausar e arquivar são só do dono. A pontuação (`score: {value, success}`, `null` em "sem dados") vem só com `score_enabled`, no fuso de quem pede; desligada, a chave nem aparece.
- Auditoria: `habit_created`, `habit_updated` com `{"changes": [{"field", "old", "new"}]}` (a descrição só com o `field`), `habit_deleted` com `habit_id=None` e `{"habit_id": n}` (mais `recent_invites`, os convites do hábito nas últimas 24 h, que continuam contando no limite de convites do dono), e `habit_paused`, `habit_resumed`, `habit_archived` e `habit_unarchived`. Apagar o hábito apaga em cascata as marcações, pausas, membros, convites, alertas e a auditoria dele, e os membros recebem o email `HabitDeleted` depois do commit.

Nos testes, `tests/auth_helpers.py` tem `open_session(session, user)` (sessão direto no banco, sem email) e `cookie(token)`; a fixture `make_account(email, **campos)` cria um usuário com os termos aceitos e uma sessão (`Account(user, headers)`); `tests/habit_helpers.py` tem os atalhos da API de hábitos (`VALID`, `create`, `created`, `stored`, `events`, `share`, `NOT_FOUND`, `FORBIDDEN`, `invalid`); e `tests/factories.py` tem `new_member`, `new_invite`, `new_mark`, `new_pause` e `new_alert` para montar compartilhamento, marcações, pausas e alertas direto no banco.

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
- Várias por dia: `MAX_MARKS_PER_DAY` conta as marcações do hábito, de todos os membros, no dia de `marked_at` no fuso salvo de quem marca (`users.timezone`), na mesma transação da inserção (409 `mark_limit_reached`).
- Endpoint do modo errado (toggle num hábito com várias por dia, ou `POST /marks` num toggle): 409 `mark_mode_mismatch`.
- Observação só com `notes_enabled`, até `MAX_NOTE_LENGTH` caracteres, mesmas regras de texto da descrição do hábito. Duração só com `duration_enabled`, de 1 a 1440 minutos; sem ela, a padrão do hábito. Custo só com `cost_enabled`: no nível hábito é sempre o valor fixo do hábito (mandar outro, na criação ou no PATCH, dá 422); no nível marcação, o valor mandado ou, sem ele, o padrão do hábito. O custo fica gravado na marcação: mudar o do hábito não muda as antigas. Campo de recurso desligado: 422 com o campo.
- Escrita: dono e editor, em marcações de qualquer pessoa; viewer, 403 `forbidden`; sem acesso, 404 `not_found`; arquivado, 409 `habit_archived` (pausado aceita). A ordem é 404, 403, 409 (arquivado, modo), 422 e 409 (limite).
- Auditoria: `mark_created`, `mark_updated` e `mark_deleted` com `habit_id`, quem fez (`user_id`), o IP e, no `details`, `{mark_id, author_id, marked_at, duration_minutes, cost_cents, has_note}` (criar e apagar; o toggle que desmarca grava um `mark_deleted` por marcação) ou `{mark_id, changes: [{field, old, new}]}` (editar). O texto da observação nunca vai para a auditoria: só `{"field": "note"}` ou `has_note`.

Nos testes, `tests/test_marks.py` tem os testes de concorrência com threads de verdade contra o banco em arquivo (`run_parallel(engine, chamadas, ação)`, que chama o `service` em sessões separadas, juntas por um `threading.Barrier`).

### Progresso (relatório e export)

O pacote `app/progress/` (`schemas.py`, `service.py` com 100% de cobertura, e `routes.py`) entrega os dados do relatório: `GET /habits/progress?from=YYYY-MM-DD&to=YYYY-MM-DD[&habit_ids=1&habit_ids=2]`. Exige `CurrentUser`; todo papel lê. O router é registrado antes do de `/habits` no `create_app`, senão `/habits/progress` cairia em `/habits/{habit_id}` (422).

- `from` e `to`: datas locais (só `YYYY-MM-DD`), inclusivas, no fuso de quem pede (`users.timezone`), de 1900-01-01 a 2999-12-31. O intervalo cobre no máximo 5 anos de dias: de 2021-01-01 vai até 2025-12-31; 2026-01-01 já é "5 anos e 1 dia" (422 `validation_error` em `to`, como `to` antes de `from`). De 29/2, o aniversário num ano não bissexto é 1/3.
- `habit_ids`: repetido na query, até 100 (ids repetidos contam uma vez). Sem ele, todos os hábitos que o usuário acessa, inclusive os arquivados (eles guardam histórico e entram no "exportar tudo"). Hábito sem acesso, ou que não existe, some da resposta, sem erro: a API não revela que ele existe.
- Resposta: `{"from", "to", "timezone", "habits": [...]}`, por id. Cada item tem `habit` (o mesmo objeto do `GET /habits/{id}`, com `score: {value, success}` só com a pontuação ligada), `goal_target` (N, ou N × `duration_minutes` com a duração ligada), `periods` (`[{first_day, last_day, value, met, spend_cents}]`) e, só com o custo ligado e um limite, `cost_periods` (`[{first_day, last_day, spend_cents, limit_percent}]`).
- Cálculos só pelo `score.py`, no fuso de quem pede. `periods` vem do `summarize_periods`: os períodos da meta que tocam o intervalo, inteiros (com o valor e o gasto do período todo), sem filtro de criação ou pausa. A pontuação vem do `evaluate`: é a pontuação atual do hábito, a mesma do `GET /habits`, não recortada pelo intervalo.
- Gasto (só com `cost_enabled`; desligado, `spend_cents` e `cost_periods` nem aparecem): soma do `cost_cents` gravado em cada marcação, igual nos níveis hábito e marcação. `cost_periods` usa os períodos do limite (`cost_limit_period`, que pode ser diferente da meta); `limit_percent` é o gasto em porcentagem do limite, arredondado meio para cima só com inteiros (pode passar de 100; `null` com limite 0).
- Sem N+1: hábitos, marcações e pausas são lidos em lote (5 consultas com a sessão, em qualquer número de hábitos). A fixture `selects` do `conftest.py` conta os SELECT nos testes.

### Compartilhamento

O pacote `app/sharing/` tem os convites e os membros (`quota.py` e `service.py` com 100% de cobertura, `schemas.py` e `routes.py`). Papéis: o dono (`habits.owner_id`) configura, convida, troca papel e remove; `editor` marca e edita marcações de qualquer pessoa; `viewer` só vê. Todos os endpoints exigem `CurrentUser`; sem acesso ao hábito, 404 `not_found`; com acesso mas sem o papel, 403 `forbidden`.

| Endpoint | Quem | O quê |
|---|---|---|
| `POST /habits/{id}/invites` | dono | Corpo `{email, role}` (`editor` ou `viewer`). Sempre 202 `{"status": "sent"}`: com ou sem conta, a si mesmo, a quem já é membro ou já tem convite pendente (esses três não mudam nada). Arquivado: 409 `habit_archived`. |
| `GET /habits/{id}/invites` | dono | `{"invites": [{id, email, role, created_at}]}`, os pendentes (sem dizer se o email tem conta). |
| `DELETE /habits/{id}/invites/{invite_id}` | dono | 204, cancela o pendente. |
| `GET /habits/{id}/members` | todos | `{"members": [{user: {id, email}, role, joined_at}]}`, o dono primeiro (com a data de criação do hábito). |
| `PATCH /habits/{id}/members/{user_id}` | dono | Corpo `{role}`; devolve o membro. De editor para viewer, os alertas dele no hábito saem na mesma transação. |
| `DELETE /habits/{id}/members/{user_id}` | dono | 204. As marcações do membro ficam; os alertas dele no hábito saem. |
| `POST /habits/{id}/leave` | editor e viewer | 204, como remover. O dono recebe 403 (ele apaga o hábito). |
| `GET /invites` | convidado | `{"invites": [{id, habit: {id, name, color}, owner: {id, email}, role, created_at}]}`, os pendentes recebidos. |
| `POST /invites/{invite_id}/accept` | convidado | O hábito, como no `GET /habits/{id}`, com o papel novo. |
| `POST /invites/{invite_id}/decline` | convidado | 204. |

Regras (`service.py`):

- O convite não expira e não tem status: a linha de `habit_invites` existe enquanto está pendente e sai ao ser aceito, recusado ou cancelado.
- Email sem conta: o convite fica pendente para sempre, com `invited_user_id` vazio, e nunca é entregue, nem se a conta for criada depois. Aceitar ou recusar um convite que não é do usuário (de outra conta, sem conta ou inexistente) dá o mesmo 404.
- Para não revelar quem tem conta, os ramos com e sem conta fazem as mesmas consultas e escritas, com o mesmo SQL (há teste), e o email ao convidado sai depois da resposta (`BackgroundTasks`). Conta bloqueada recebe o convite pendente, mas não o email. O `details` da auditoria não leva o email nem o `invited_user_id`.
- Limites, conferidos dentro do `BEGIN IMMEDIATE` (requests em paralelo não passam deles), todos 409: `MAX_INVITES_PER_DAY` por dono, somando todos os hábitos (`invite_limit_reached`), `MAX_GUESTS_PER_HABIT`, membros + pendentes (`guest_limit_reached`), e `MAX_SHARED_HABITS_PER_USER` ao aceitar (`shared_habit_limit_reached`; o convite continua pendente). O hábito compartilhado conta só no `MAX_HABITS_PER_USER` do dono.
- `MAX_INVITES_PER_DAY` conta os eventos `invite_created` do dono nas últimas 24 h (janela móvel), porque as linhas de convite somem (`quota.py`). A retenção não apaga esses eventos. Como a auditoria do hábito sai com ele, o `habit_deleted` leva `recent_invites` e a conta soma esse número por 24 h depois da exclusão: apagar o hábito não devolve convites.
- Em hábito arquivado, só convidar é recusado; cancelar, aceitar, recusar, sair, remover e trocar papel continuam.
- Auditoria (todos com `habit_id`): `invite_created`, `invite_canceled`, `invite_accepted` e `invite_declined` com `{invite_id, role}`; `member_left` com `{role}`; `member_removed` com `{member_id, role}`; `member_role_changed` com `{member_id, changes: [{field: "role", old, new}]}`.

`tests/test_permissions.py` tem a matriz de permissões (dono, editor, viewer, estranho e sem sessão) de todos os endpoints de hábito, e quem vê o hábito nas listas (`/habits`, `/habits/progress`, `/history`).

### Histórico

O pacote `app/history/` (`service.py` com 100% de cobertura, `schemas.py` e `routes.py`) entrega o histórico dos hábitos, lido do `audit_log`: `GET /history`, do mais recente ao mais antigo. Exige `CurrentUser`; todo papel lê. O cursor das listagens (`"<microssegundos>.<id>"`, opaco para o cliente) fica em `app/pagination.py`, usado também pelas marcações.

- Eventos: só os de hábito (`habit_created`, `habit_updated`, `habit_paused`, `habit_resumed`, `habit_archived`, `habit_unarchived`), de marcação (`mark_*`) e de compartilhamento (`invite_*`, `member_*`), a lista `HistoryEvent`. Nunca os de auth, de conta, de admin nem `alert_updated` (a configuração de alerta é de cada membro). `habit_deleted` (com `habit_id` nulo) não aparece: a auditoria do hábito sai com ele.
- Acesso: os eventos dos hábitos que o usuário acessa agora (dono, editor ou viewer), inclusive arquivados e inclusive o que aconteceu antes de ele entrar. Quem sai ou é removido deixa de ver na hora. `invite_created`, `invite_canceled` e `invite_declined` só aparecem para o dono, como a lista de convites; `invite_accepted` aparece para todos.
- Filtros, opcionais e combináveis: `habit_id` (sem acesso ou inexistente: lista vazia, sem revelar nada), `user_id` (quem fez), `event` (repetido: `&event=mark_created&event=mark_deleted`; fora da lista, 422), `mark_id` (os eventos de uma marcação: quem criou, editou e apagou, e quando; usa o índice de `audit_log.mark_id`) e `from`/`to` (datas locais `YYYY-MM-DD`, inclusivas, no fuso de quem pede, como no progresso; `to` antes de `from`, 422).
- Paginação: `limit` de 1 a 200 (padrão 50), ordem `created_at` desc e `id` desc; com `next_cursor` não nulo, repita com `&cursor=<next_cursor>` e os mesmos filtros. A página seguinte continua depois da última linha vista: eventos novos entre uma página e outra não repetem nem pulam itens.
- Resposta: `{"events": [{id, event, created_at, habit: {id, label}, author: {id, email} | null, details}], "next_cursor"}`. `author: null` é "usuário removido". `details` sai filtrado por uma lista de chaves por evento (`PUBLIC_DETAILS`): o JSON gravado nunca é repassado inteiro, e o IP nunca sai.
- Uma consulta por página (hábito e autor em JOIN), sem N+1.

### Exclusão de conta

`app/auth/deletion.py` (100% de cobertura) apaga uma conta numa transação só (`BEGIN IMMEDIATE`): ou apaga tudo ou nada.

- Pelo usuário: `POST /auth/me/delete/request` manda um código `delete_account` para o email da conta (202; os mesmos limites do código de login, contados junto com ele: 429 `rate_limited`). `DELETE /auth/me` com `{code}` confere o código (10 minutos, uma vez só, 5 tentativas, só o mais recente vale; o de login é recusado) e apaga: 204 e o cookie apagado; código recusado, 400 `invalid_code` (field `code`). Funcionam sem os termos atuais aceitos.
- Pelo admin (ETH-28): `delete_account(session, account_id=..., actor_id=..., ip=...)`, a mesma exclusão sem código; devolve `AccountDeletion(account_id, emails)`, com os emails a agendar depois do commit.
- O último admin ativo não é apagado: 409 `last_admin` (no pedido do código, no `DELETE /auth/me` e pelo admin). Admin bloqueado não conta.
- Apaga: a conta, as sessões, os `login_codes` dela e do email, os hábitos dela (com as marcações dos convidados, pausas, membros, convites enviados, alertas e a auditoria deles), os convites recebidos (pela conta e pelo email), as participações em hábitos de outras pessoas, os alertas e a auditoria da própria conta (auth, `terms_accepted`, `profile_updated`, `admin_created` e os `habit_deleted` dos hábitos dela).
- Anonimiza: as marcações dela em hábitos de outras pessoas (`user_id` nulo, "usuário removido"); as linhas do `audit_log` que ficam com o `user_id` dela (`user_id` e `ip` nulos); os ids dela em `author_id` e `member_id` dos eventos de hábito (viram `null`, porque o histórico os mostra); e todo texto com "@" no `details` das linhas que citam a conta (pelo `user_id`, pelo email ou por `target_user_id`, a conta alvo dos eventos de admin). `banners.created_by` vira nulo.
- Grava `account_deleted` com `user_id` = quem apagou (nulo quando foi a própria conta) e `{"account_id": n, "by_admin": bool}`, sem email nem IP da pessoa. Depois do commit, o log tem só `conta <id> excluída`: depois de restaurar um backup, essas linhas dizem quais exclusões reaplicar.
- Emails: "conta excluída" para a conta e "você perdeu acesso" para cada membro dos hábitos dela (um por membro, com todos os hábitos), lidos antes de apagar e enviados depois do commit.

### Comandos de operação (CLI)

```bash
uv run --env-file .env python -m app.cli --help      # lista os comandos
uv run --env-file .env python -m app.cli cleanup     # aplica a retenção de dados
uv run --env-file .env python -m app.cli create-admin voce@example.com   # torna a conta admin
uv run --env-file .env python -m app.cli seed        # dados de exemplo (só em dev)
```

O CLI lê a mesma config do servidor (variáveis de ambiente) e abre o banco de `DATABASE_PATH`, que precisa existir e estar migrado. Em produção roda como `app-ethos`. Código de saída 0 em sucesso, 1 em erro (a mensagem sai no stderr com `erro:`, sem stack trace nem valores) e 2 em uso errado.

| Comando | O quê |
|---|---|
| `cleanup` | Retenção de dados (ver acima), numa transação só. Imprime quantas linhas mudou em cada passo. Pode rodar quantas vezes quiser: a segunda seguida não muda nada. No plano, roda de hora em hora pelo `ethos-alerts.timer`, depois dos alertas. |
| `create-admin <email>` | Liga o `is_admin` de uma conta que já existe e grava `admin_created` no `audit_log` (`user_id` = a conta promovida, `details` = `{"via": "cli"}`), numa transação só. É o único jeito de criar admin: não existe endpoint para isso. O email é normalizado e validado como no login (`normalize_email`: espaços e maiúsculas não importam; endereço inválido é erro). A saída mostra o id da conta, nunca o email. Email sem conta: erro e nada muda (a pessoa precisa entrar no app uma vez antes, o que cria a conta). Conta bloqueada (`is_active=false`): erro e nada muda; desbloqueie antes. Conta que já é admin: avisa, sai com 0 e não grava nada. |
| `seed` | Só com `APP_ENV=dev` (fora dele: erro, sai com 1 e não grava nada). Cria, numa transação só, as contas `ana@example.com`, `bia@example.com` e `caio@example.com` (com os termos aceitos; entre pelo login com o email, e o código sai no terminal com `EMAIL_BACKEND=console`), 8 hábitos que variam os tipos (toggle e várias por dia; meta mínima, máxima e exata; duração, observação, pontuação, custo nos dois níveis; ativo, pausado e arquivado; compartilhado com editor e viewer) e as marcações dos últimos 60 dias, pelas mesmas regras e com a mesma auditoria da API. Não duplica: se alguma das contas de exemplo já existe, avisa, sai com 0 e não grava nada. Para recriar, apague o banco de dev e rode `alembic upgrade head` de novo. |

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
