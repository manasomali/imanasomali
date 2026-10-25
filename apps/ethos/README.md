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
uv run coverage report --fail-under=100 --include=app/admin/accounts.py,app/admin/banners.py,app/alerts/service.py,app/audit.py,app/auth/deletion.py,app/auth/deps.py,app/auth/origin.py,app/auth/security.py,app/auth/service.py,app/habits/access.py,app/habits/scoring.py,app/habits/service.py,app/history/service.py,app/marks/schemas.py,app/marks/service.py,app/pagination.py,app/progress/service.py,app/retention.py,app/score.py,app/sharing/quota.py,app/sharing/service.py   # depois do pytest
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
- `alerts.last_evaluated_at` (migração 0003) guarda a última avaliação de cada alerta pelo `run-alerts` (ou o último salvar da configuração), para cada ocorrência da hora escolhida ser avaliada uma vez só, com ou sem email (veja "Alertas").
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
- Resposta: `{"from", "to", "timezone", "habits": [...]}`, por id. Cada item tem `habit` (o mesmo objeto do `GET /habits/{id}`, com `score: {value, success}` só com a pontuação ligada), `goal_target` (N, ou N × `duration_minutes` com a duração ligada), `periods` (`[{first_day, last_day, value, met, spend_cents}]`), `marks_range` (`{first_day, last_day}`: os dias locais da primeira e da última marcação do hábito em todo o tempo, não só no intervalo; `null` sem marcação; o "exportar tudo" do front parte dele) e, só com o custo ligado e um limite, `cost_periods` (`[{first_day, last_day, spend_cents, limit_percent}]`).
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

- Hora: a hora cheia escolhida, no fuso do usuário (`users.timezone`), todo dia (diário) ou só no dia da semana escolhido (semanal). Cada ocorrência é avaliada uma vez, na primeira execução do `run-alerts` a partir dela no mesmo dia local: uma execução atrasada (o timer das 09:00 rodou às 10:05, ou a VM ficou fora umas horas) ainda avalia o alerta das 09:00; o dia que passa inteiro sem execução perde a ocorrência. Avaliação sem nada a avisar não se repete mais tarde no mesmo dia (`alerts.last_evaluated_at`). Salvar a configuração depois da hora de hoje deixa o alerta para a próxima ocorrência.
- Horário de verão: a hora que não existe (02:00 quando o relógio pula para 03:00) dispara às 03:00; a hora que se repete (01:00 duas vezes) dispara só na primeira.
- Regras, no período atual e só com a chave ligada: meta pelo `score.evaluate` (`min` atrasado no ritmo, `floor(N × fração do período)` com inteiros; `max` atingiu ou passou de N; `exact` passou ou atrasado); custo pelo `score.check_cost` (aviso a partir de 80% do limite, alerta ao passar). Nada dispara no período em que o hábito foi criado, nem num período com pausa. Hábito pausado ou arquivado e conta bloqueada não são avaliados.
- No máximo um email por membro e hábito por dia local (`last_sent_at`), juntando meta e custo num email só (`Alert`), no idioma do usuário, com o link para `APP_URL/habits/{id}/alerts`.
- Sem email duplicado: o alerta é relido e reavaliado dentro de um `BEGIN IMMEDIATE`, que grava `last_evaluated_at` e `last_sent_at` antes do envio; o envio sai depois do commit, fora da trava. Execuções repetidas ou ao mesmo tempo mandam um email só. Se o envio falha, outra transação desfaz a marcação e a próxima execução tenta de novo; se o processo morre entre o commit e o envio, aquele email se perde (um alerta a menos, nunca um repetido).
- Falha num alerta (SMTP, fuso inválido, erro inesperado) vira uma linha de log com os ids do hábito e do usuário e o tipo do erro (nunca email, nome do hábito ou a mensagem da exceção) e não impede os outros.

### Admin e banners

O pacote `app/admin/` (`accounts.py` e `banners.py` com 100% de cobertura, `schemas.py` e `routes.py`) tem o painel de admin. Todo `/admin/...` exige `AdminUser` (a dependência está também no router, então rota nova nunca fica aberta): sem sessão, 401 `unauthorized`; usuário comum, 403 `forbidden`. Cada escrita confere de novo, dentro do `BEGIN IMMEDIATE`, que quem age continua admin ativo (dois admins que se bloqueiam ao mesmo tempo não ficam os dois bloqueados). Conta ou banner que não existe: 404 `not_found`. Listas paginadas por cursor, `limit` de 1 a 200 (padrão 50).

| Endpoint | O quê |
|---|---|
| `GET /admin/users` | `{"users": [{id, email, is_active, is_admin, timezone, locale, created_at, last_login_at, habit_count, mark_count}], "next_cursor"}`, das contas mais novas às mais antigas. Filtros: `email` (trecho, sem curingas; espaços e maiúsculas não importam), `status` (`active` ou `blocked`), `created_from`/`created_to` e `last_login_from`/`last_login_to` (datas locais inclusivas no fuso do admin; fim antes do início, 422 no campo do fim). |
| `GET /admin/users/{id}/habits` | `{"user", "habits", "marks", "next_cursor"}`: a conta, os hábitos de que ela é dona em qualquer status (como no `GET /habits/{id}`, `role` owner, sem `score`) e uma página das marcações deles, de todos os autores, com as observações, das mais recentes às mais antigas. `habit_id` filtra um hábito dela (de outra conta: 404). Cada chamada grava `admin_viewed_habits`, na mesma transação da leitura. |
| `POST /admin/users/{id}/block` | Desliga o `is_active` e apaga as sessões: a pessoa não recebe código nem entra; os dados ficam. A própria conta: 409 `cannot_block_self`. Devolve a conta. |
| `POST /admin/users/{id}/unblock` | Liga o `is_active`. Devolve a conta. |
| `PATCH /admin/users/{id}/email` | Corpo `{new_email}` (normalizado como no login). Email que já tem conta, inclusive o atual: 409 `email_in_use` (field `new_email`), sem mudar nada. Apaga as sessões, vence os códigos pendentes do email antigo e da conta e avisa o email antigo e o novo depois da resposta. Os convites pendentes recebidos continuam (são da conta). Devolve a conta. |
| `DELETE /admin/users/{id}` | 204: a exclusão de `app/auth/deletion.py` (último admin ativo: 409 `last_admin`), com os avisos depois da resposta. |
| `GET /admin/banners` | `{"banners": [{id, text_pt, text_en, starts_at, ends_at, created_by, created_at, updated_at}], "next_cursor"}`, todos, dos criados por último aos primeiros. |
| `POST /admin/banners` | 201. Corpo `{text_pt, text_en, starts_at, ends_at}`. |
| `PATCH /admin/banners/{id}` | Qualquer parte dos mesmos campos (`null` e campo desconhecido: 422). |
| `POST /admin/banners/{id}/end` | Fecha a janela agora. Agendado que ainda não começou: nunca aparece (`starts_at` vira 1 µs antes do fim). Já encerrado: nada muda. |
| `GET /banners/active` | Público, sem sessão nem termos: `{"banner": {id, text_pt, text_en, starts_at, ends_at} \| null}`. |

- Contagens: `habit_count` são os hábitos de que a conta é dona (todos os status) e `mark_count` as marcações que ela fez em qualquer hábito; saem de subconsultas na consulta da página (uma consulta, sem N+1).
- Último login: a coluna `users.last_login_at`, gravada a cada login por código (nula em quem nunca entrou). Não vem das sessões (somem no logout) nem do evento `login` (apagado depois de 90 dias).
- Bloquear não tira o último admin ativo: o admin não bloqueia a si mesmo, e quem bloqueia continua admin. Bloquear outro admin é permitido.
- Banner: texto de 1 a 280 caracteres por idioma, sem espaços nas pontas, uma linha só (controles e quebra de linha: 422), guardado como veio (HTML não é interpretado; o front mostra como texto). Janela `[starts_at, ends_at)` em UTC, com o fim depois do início (senão 422 `ends_at`). Com mais de um na janela, aparece o que começou por último (empate: o criado depois).
- Auditoria, com `user_id` = o admin e a conta alvo em `details.target_user_id` (é por ele que a exclusão da conta acha a linha e tira os emails): `admin_viewed_habits` `{target_user_id, habit_id?}`; `user_blocked` `{target_user_id, sessions}`; `user_unblocked` `{target_user_id}`; `email_changed` `{target_user_id, old_email, new_email, sessions}`; `account_deleted` (ver "Exclusão de conta"). Banners: `banner_created` `{banner_id, text_pt, text_en, starts_at, ends_at}`, `banner_updated` e `banner_ended` `{banner_id, changes: [{field, old, new}]}`. Ação que não muda nada (bloquear quem já está bloqueado, editar com os mesmos valores) não grava.

### Comandos de operação (CLI)

```bash
uv run --env-file .env python -m app.cli --help      # lista os comandos
uv run --env-file .env python -m app.cli run-alerts  # avalia os alertas na hora e manda os emails
uv run --env-file .env python -m app.cli cleanup     # aplica a retenção de dados
uv run --env-file .env python -m app.cli create-admin voce@example.com   # torna a conta admin
uv run --env-file .env python -m app.cli seed        # dados de exemplo (só em dev)
```

O CLI lê a mesma config do servidor (variáveis de ambiente) e abre o banco de `DATABASE_PATH`, que precisa existir e estar migrado. Em produção roda como `app-ethos`. Código de saída 0 em sucesso, 1 em erro (a mensagem sai no stderr com `erro:`, sem stack trace nem valores) e 2 em uso errado.

| Comando | O quê |
|---|---|
| `run-alerts` | Avalia os alertas cuja hora chegou e manda os emails (ver "Alertas"). Imprime quantos alertas avaliou, quantos emails mandou e quantas falhas teve. Sai com 0 mesmo com falha num alerta (SMTP, por exemplo): a falha é logada, não para os outros e é tentada de novo na próxima execução. Só erro geral (config inválida, banco inacessível na leitura inicial) sai com 1, e aí o `OnFailure=` do timer grava a linha de erro no journald. Pode rodar quantas vezes quiser: a segunda seguida não manda nada. Roda de hora em hora pelo `ethos-alerts.timer`, antes do `cleanup`, na mesma unit: se ele sair com 1, o `cleanup` daquela hora não roda. |
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
| `src/bootstrap.js` | `createApp()`: router com `basename="/ethos"` e QueryClient ligados (401 em qualquer chamada leva para o login) |
| `src/routes.jsx` | Todas as rotas. Tela que exige sessão é filha de `RequireSession`; tela pública (login, termos, privacidade) fica fora. O painel de admin é filho de `RequireAdmin`; a aba do hábito (`/habits/:habitId`) tem as seções como rotas filhas do `HabitLayout` |
| `src/paths.js` | `BASENAME` e `PATHS` (`/`, `/entrar`, `/conta`, `/termos`, `/privacidade`, `/habits/new`, `/habits/:habitId`, `/relatorio`, `/admin`, `/admin/contas/:userId`, `/admin/banners`), `adminUserPath(id)`, `HABIT_SECTION` (seções da aba do hábito), `habitPath(id, seção, query)`, `parseHabitId` e `reportPath({from, to, habitIds})`. Use as constantes, nunca o caminho escrito à mão |
| `src/i18n.js` | `createI18n()`, `LANGUAGES` e a detecção do idioma (mesma chave do site, `i18nextLng`; `pt-BR` vira `pt`) |
| `src/index.css` | Estilos globais. Importa as fontes, `@tokens/tokens.css` (alias para `packages/tokens`) e a paleta |
| `src/styles/palette.css` | As 12 cores dos hábitos (`--habit-<nome>`) nos dois temas |
| `src/api/auth.js` | `useMe()`/`fetchMe()` (`GET /auth/me`, chave `meQueryKey`), `useCachedMe()` (o usuário já carregado, sem buscar: para o que aparece também nas telas públicas, como o menu), `requestCode()`, `verifyCode()`, `acceptTerms()` (manda o `TERMS_VERSION`), `logout()`, `useLogout()` (sai, vai para o login e limpa o cache), `apiLocale()` |
| `src/api/banners.js` | `useActiveBanner()` (`GET /banners/active`, sem login, chave `activeBannerQueryKey`) |
| `src/api/admin.js` | Endpoints de `/admin` (chaves em `adminKeys`): `useAccounts`, `useAccountHabits`, `blockAccount`, `unblockAccount`, `changeAccountEmail`, `deleteAccount`, `useBanners`, `createBanner`, `updateBanner`, `endBanner` |
| `src/api/habits.js` | `useHabits({archived})`, `useHabit(id)`, `fetchHabits`, `fetchHabit`, `canMark(habit)` e as chaves `habitKeys`; escritas do dono: `useCreateHabit`, `useUpdateHabit(id)`, `useHabitStatus(id)` (`mutate('pause' \| 'resume' \| 'archive' \| 'unarchive')`), `useDeleteHabit(id)` + `forgetHabit` (depois de sair da aba), `habitSaved` |
| `src/api/marks.js` | Marcações por ano (`useYearMarks`, `useYearMarksOfHabits`, `fetchYearMarks`, `yearMarksQuery`), escritas otimistas (`useToggleMark`, `useCreateMark`, `useDeleteMark`) e `useUpdateMark`, `afterMarksChanged`, chaves `markKeys` |
| `src/api/progress.js` | `fetchProgress({from, to, habitIds})` (`GET /habits/progress`, em grupos de 100 ids) e as chaves `reportKeys` do relatório |
| `src/api/report.js` | Dados do relatório e do export (abaixo, em "Relatório e export"): `useReportData`, `fetchReportData`, `fetchAllReportData`, `exportAllFile` |
| `src/components/` | `Layout` (pular para o conteúdo, menu, banner, `<main>`, rodapé com os links dos termos e da privacidade), `Menu` (links, link do admin só para `is_admin`, volta ao site, idioma, tema), `Banner`, `RequireSession` (com termos por aceitar, só mostra o `TermsModal`), `RequireAdmin`, `TermsModal`, `TimezoneNotice`, `ErrorMessage`, `PageTitle`; do calendário: `YearCalendar` (+ `DayCell`), `YearNav`, `DayPanel`, `MarkItem`, `HabitTabs`, `HabitNav`, `HabitScore`; `HabitForm` (configuração do hábito, para criar e editar); do relatório: `ExportAll` |
| `src/pages/` | Telas: `Home` (calendário de todos os hábitos), `Habit` (`HabitLayout`, a aba do hábito), `HabitCalendar`, `HabitSettings` (configuração), `NewHabit` (criar), `Report` (relatório e export, num chunk à parte por `LazyReport`), `Login` (email → código, destino do 401), `Legal` (termos e privacidade, sem login), `Admin/` (contas, conteúdo dos hábitos de uma conta e banners), `NotFound`; provisória: `Account` (destino do aviso de fuso) |
| `src/hooks/` | `useTheme` (tema atual e a troca), `useCalendarParams` (ano e dia na URL), `useHabitContext` (o hábito dentro das seções da aba) |
| `src/legal/{pt,en}/{terms,privacy}.json` | Textos dos termos de uso e da política de privacidade (abaixo, em "Termos e privacidade") |
| `src/lib/` | Utilitários sem React, com cobertura mínima de 80% (abaixo) |
| `src/test/` | Setup dos testes: MSW (`server`, `api(path)`, `activeBanner(banner)`), `renderApp(path)`, `meFixture()`, `createTestI18n()`, `axe`, `readFrontendFile()`; do painel de admin, `src/test/admin.js` (`ADMIN`, `signedIn`, `accountFixture`, `bannerFixture`, `trackRequests`) |
| `tests/` | Testes do build de produção, no Node |
| `build-targets.js` | Converte o `browserslist` do `package.json` no `build.target` do Vite |

### `src/lib/`

- `api.js`: `apiFetch(path, {method, query, body, signal})` chama `/api/ethos<path>` na mesma origem, com `credentials: 'include'` (o cookie `__Host-ethos_session` é HttpOnly; o front nunca o lê). Erro sempre vira `ApiError {status, code, field}`: o código vem do corpo `{"error", "field"}` da API ou, quando o corpo não é JSON (o nginx responde 429, 502 e 504 em HTML), do status, com o mesmo mapa de `app/errors.py`. Sem resposta: status 0 e código `network_error`.
- `queryClient.js`: `createQueryClient({onUnauthorized})`. Leitura só repete (até 2 vezes) falha de rede e 5xx; 401, 403 e 429 nunca repetem; escrita nunca repete sozinha. Todo 401, de leitura ou escrita, chama `onUnauthorized`.
- `session.js`: `redirectToLogin(router)` vai para `/entrar` guardando o caminho atual em `state.from` (no histórico, nunca na URL); `returnPath(location)` devolve esse caminho depois do login, só se for interno.
- `errors.js`: `errorKey(error, i18n.exists)` dá `errors.<codigo>`, ou `errors.unknown` para código sem tradução e erro que não veio da API. Na tela, use o componente `ErrorMessage` (com `onRetry` opcional).
- `time.js`: dias locais como `"AAAA-MM-DD"`. `dayBounds(dia, fuso)` dá `{start, end}` (fim exclusivo) em UTC, o que o `POST /habits/{id}/toggle` espera; `pastDayNoon(dia, fuso)` dá 12:00 local em UTC; `markedAtFor(dia, fuso, agora)` dá o `marked_at` (hoje: o instante atual; passado: 12:00 local; futuro: `RangeError`). Também `today`, `localDate`, `addDays`, `parseDate`, `zonedTimeToUtc`, `browserTimezone`, `isValidTimezone`, `sameTimezone`. Hora que não existe ou se repete (horário de verão) segue o backend (`fold=0`).
- `calendar.js`: meses e dias do ano (semana na segunda), `yearRange(ano, fuso)` (o `from`/`to` do ano em UTC), `marksByDay`, `overviewByDay` e `splitDots` (até 4 pontos e o "+N"), `moveDay` (setas), `parseYear`/`parseDay` (URL), `MIN_YEAR`. `format.js`: dias, meses e horas formatados pelo idioma. `duration.js`: `parseDuration` e `MAX_DURATION_MINUTES`.
- `habitForm.js`: o formulário do hábito (abaixo, em "Configuração do hábito"): `habitForm(hábito, idioma)`, `habitPayload(form, idioma, hábito)`, `goalSummary(form)`, `visibleFields`, `turnedOff`, `minGoalCount`/`maxGoalCount`, `textLength`, `hasForbiddenControls` e as constantes (`TEXT_LIMITS`, `PERIOD_DAYS`, `MAX_MARKS_PER_DAY`, `FEATURES`, `FORM_FIELDS`).
- `money.js`: `formatMoney(centavos, idioma)` sem símbolo, com 2 casas (`1.234,50` / `1,234.50`); `parseMoney(texto, idioma)` lê o que a pessoa digitou e devolve centavos ou `null`; `MAX_MONEY_CENTS`.
- `palette.js`: `HABIT_COLORS` (os 12 nomes de `HabitColor`) e `isHabitColor`. `color.js`: `contrastRatio`, `relativeLuminance` (WCAG), para escolher a cor de um texto sobre a cor de um hábito.
- `legal.js`: `TERMS_VERSION`, `SUPPORT_EMAIL` e `loadLegalDocument(nome, idioma)` (abaixo, em "Termos e privacidade").
- `theme.js` e `storage.js`: leitura e escrita da chave `theme` e do `localStorage` sem lançar exceção (modo privado). `timezoneNotice.js`: regra do aviso de fuso.
- `datetime.js`: `formatDateTime(instante, fuso, idioma)` e o valor de um `<input type="datetime-local">` no fuso de quem vê (`toDateTimeLocal`, `fromDateTimeLocal`).
- `banner.js`: texto do banner no idioma da tela (`bannerText`), o "fechar" lembrado por id em `ethos:banners-dismissed` (`dismissBanner`, `isBannerDismissed`; guarda os últimos 20), o contador de 280 caracteres como a API conta (`bannerTextLength`: sem os espaços das pontas, um por caractere Unicode) e o formulário do admin (`bannerForm`, `bannerPayload`, `bannerStatus`).
- `admin.js`: filtros da listagem de contas (`accountQuery`), a confirmação digitando o email (`confirmsEmail`) e o id da conta na URL (`parseUserId`).
- `export/`: o relatório e os exports, sem React (abaixo, em "Relatório e export"). `time.js` ganhou `localTime` ("HH:MM") e `format.js`, `formatShortDay`.

### Calendários e marcação

- **Rotas:** `/` é a aba principal (todos os hábitos ativos e pausados; os arquivados ficam numa seção à parte) e `/habits/:habitId` a aba do hábito (`HabitLayout`: cabeçalho, pontuação e o submenu `HabitNav`), com o calendário como rota índice. Ano e dia escolhidos ficam na URL (`?year=2025&day=2025-03-04`). Seção nova do hábito (configuração, compartilhamento, alertas): rota filha do `HabitLayout` em `src/routes.jsx` com o caminho de `HABIT_SECTION`, um item no `HABIT_NAV` de `components/HabitNav` e `useHabitContext()` para receber `{habit, timeZone}`. O caminho dos alertas é fixo (`/habits/:habitId/alerts`, o link do email; `src/paths.test.js` confere com o backend).
- **Cache:** `habitKeys.list({archived})` e `habitKeys.detail(id)` para os hábitos; `markKeys.year(id, ano, fuso)` guarda todas as marcações do ano local de um hábito, compartilhada pelas duas abas. Uma request por hábito e ano (páginas de 1000, seguindo o `next_cursor`). Mudou a configuração de um hábito: invalide `habitKeys.all` (as marcações não mudam).
- **Escritas:** `useToggleMark`, `useCreateMark` e `useDeleteMark` mudam a tela na hora e desfazem a mudança se a API falhar; quando dois cliques no mesmo hábito se cruzam ou a resposta não bate com o que a tela supôs, o ano é buscado de novo ao fim da última escrita. Toda escrita termina em `afterMarksChanged`, que atualiza a pontuação (só se ligada); telas com dados derivados das marcações (relatório) invalidam ali o que guardam.
- **Teclado:** o ano é uma parada de Tab só; as setas andam entre os dias (Home/End: começo e fim do mês) e Enter/Espaço acionam. Dia futuro fica `aria-disabled` (continua focável e lido).

### Configuração do hábito

- **Rotas:** `/habits/new` cria (link "Novo hábito" na aba principal) e `/habits/:habitId/settings` edita, como seção da aba do hábito. As duas usam o `HabitForm`. A seção só aparece no submenu para o dono (`visible: (habit) => habit.role === 'owner'` no `HABIT_NAV`), e quem não é dono e abre o endereço volta para o calendário; quem garante é a API (403).
- **Formulário (`src/lib/habitForm.js`):** valida como a API (tamanhos de `app/models.py`, sigla `A-Z0-9` com até 4, caracteres de controle e de direção do texto, N de 0 só no tipo máximo até os dias do período, ou `MAX_MARKS_PER_DAY` x dias com várias por dia, duração de 1 a 1440, limite de 1 a 100, dinheiro por `parseMoney` no idioma do formulário). Os erros aparecem no campo depois de mexer nele ou de enviar, e o foco vai para o primeiro inválido. Um 422 da API com `field` aparece embaixo do campo (`habit_form.invalid.<campo>`) e o foco vai para ele; outros erros (ex.: `habit_limit_reached`) aparecem embaixo do formulário. `src/lib/habitForm.test.js` confere os limites e os campos com o backend.
- **Recursos:** várias marcações por dia, duração, observação, pontuação (limite 70 por padrão; recompensa e punição só com ela ligada) e custo (nível hábito com valor obrigatório, ou marcação com valor padrão opcional; limite com período, ou "sem limite"). Campo de recurso desligado fica escondido e não é validado nem enviado, então o valor guardado volta ao religar. Desligar um recurso que está ligado no hábito salvo mostra o aviso de que os dados ficam guardados.
- **Envio:** criar manda a configuração (campos escondidos ficam com o padrão da API) e abre a aba do hábito; editar manda no `PATCH` só os campos visíveis que mudaram (nada mudou: avisa e não chama). Toda escrita guarda o hábito devolvido em `habitKeys.detail(id)` e invalida `habitKeys.all`.
- **Status e exclusão:** pausar, retomar, arquivar e desarquivar conforme o status (arquivado deixa o formulário só leitura). Apagar pede um segundo passo, com o aviso de que as marcações dos convidados também somem; depois volta para a aba principal e tira o hábito do cache.
- **Testes:** `mockHabitWritesApi(habits, {fail})` em `src/test/habits.js` simula as escritas do dono sobre o mesmo array do `mockHabitsApi` e guarda cada chamada em `requests`.

### Regras para as próximas telas

- **Textos:** todo texto visível entra nos dois `translation.json`. Código de erro novo em `app/errors.py` também: o teste `src/i18n.test.js` lê o `ErrorCode` do backend e falha se faltar a tradução em pt ou en.
- **Dados:** sempre por TanStack Query sobre `apiFetch`, nunca `fetch` direto. Não trate o 401 na tela (o QueryClient já leva para o login); mostre os outros erros com `ErrorMessage`.
- **Login e termos (ETH-31):**
  - `/entrar` é uma tela só: email (`POST /auth/code/request`) e depois o código (`verifyCode`, que é o único lugar que manda o fuso e o idioma do navegador). As mensagens são as mesmas para qualquer email, então a tela não revela se a conta existe. Reenviar o código só depois de 60 s (a API aceita 1 por minuto). No 429 do pedido, "já tenho um código" passa para o código sem pedir outro. Depois de entrar: `queryClient.clear()` e `returnPath(location)`.
  - `/termos` e `/privacidade` ficam fora do `RequireSession` e não chamam a API. Mostram `loadLegalDocument` como texto, com o `lang` do idioma que veio, um sumário e uma âncora por seção (`/termos#account`); o link direto rola até a seção quando o texto chega.
  - Com `terms_pending` no `/me`, o `RequireSession` não monta a tela e mostra só o `TermsModal` (`role="dialog"`, `aria-modal`, foco preso, o resto da página `inert`, sem fechar com Escape). Ele tem os links dos textos (em outra aba), o idioma e "Sair" (`useLogout`). Aceitar manda o `TERMS_VERSION` da aba. No 409, recarrega o `/me`; se a versão do backend for outra, a aba tem textos velhos e o modal pede para recarregar a página.
  - Sair: use `useLogout()` (navega para o login antes de limpar o cache).
- **Conta (ETH-38):** é o único lugar que chama `PATCH /auth/me`. O aviso de fuso leva para `/conta` com o fuso do navegador em `location.state.suggestedTimezone`, para já vir selecionado. Nada muda o fuso da conta sozinho.
- **Datas:** a API guarda e devolve UTC; mostre no fuso de quem vê (`me.timezone`), com `src/lib/time.js`. Nunca use os métodos locais de `Date` (`getDate`, `setHours`...), que seguem o fuso do sistema.
- **Cores:** só tokens (`var(--fg)`, `var(--surface)`...) e a paleta. Para pintar algo com a cor de um hábito: `data-habit-color={habit.color}` no elemento e `var(--habit-color, var(--muted))` no CSS. Sem `style` inline (a CSP só aceita `style-src 'self'`). O teste `src/styles/colors.test.js` falha com hex, `rgb()` e afins fora de `palette.css`.
- **Tela nova:** `PageTitle` com o título, um `<h1>`, CSS Module ao lado, ícones do `react-icons` em pixels inteiros (`size={20}`), layout a partir de 320 px. Teste com `renderApp(path)` e MSW (`server.use(http.get(api('/...'), ...))`), e `axe` sem violações.

### Termos e privacidade

Os textos dos termos de uso e da política de privacidade ficam em `src/legal/<idioma>/<documento>.json` (`terms` e `privacy`, em `pt` e `en`). São texto puro, sem HTML nem Markdown, que a tela mostra como texto (o React escapa tudo):

```json
{ "title": "Termos de uso", "sections": [{ "id": "account", "title": "Conta e acesso", "paragraphs": ["...", ["item", "item"]] }] }
```

Cada item de `paragraphs` é um parágrafo (texto) ou uma lista (array de textos). O `id` da seção é igual nos dois idiomas e serve de âncora (`/termos#account`). O único marcador é `{{supportEmail}}`.

`src/lib/legal.js`:

- `loadLegalDocument(nome, idioma)` devolve `{name, language, version, title, sections}` com o marcador já trocado pelo email. A região do idioma é ignorada (`pt-BR` vira `pt`); idioma sem texto cai no inglês, e `language` diz qual veio (use no `lang` do conteúdo). Documento desconhecido: `RangeError`. Os JSON não vão no bundle principal: cada um vira um chunk com hash, baixado só quando a tela pede, e uma aba aberta antes de um deploy continua com os textos da versão dela.
- `TERMS_VERSION`: a versão dos textos, uma data (`AAAA-MM-DD`), igual à de `backend/app/terms.py`.
- `SUPPORT_EMAIL`: o email de suporte de produção, fixo no build (o backend não o expõe, e as páginas legais abrem sem login). Use a constante em toda tela que mostra o email, como a de conta.

`src/lib/legal.test.js` falha se a versão for diferente da do backend, se o email for diferente do `SUPPORT_EMAIL` de `infra/apps/ethos/app.env`, se pt e en não tiverem as mesmas seções (mesmos ids, na mesma ordem e com a mesma forma), se um texto tiver marcação ou outro marcador, e se os prazos da seção `retention` da política não baterem com os do código (sessão e código em `app/auth/service.py`, auditoria e IP em `app/audit.py`, cópias de segurança em `infra/scripts/snapshot.sh` e `infra/lib/backups.sh`).

Para publicar uma versão nova: mude os textos nos dois idiomas, `TERMS_VERSION` aqui e em `backend/app/terms.py`, no mesmo PR. Quem aceitou a versão anterior aceita a nova no próximo acesso. Os textos são um rascunho técnico, conferido contra o código, e não substituem uma revisão jurídica.

### Relatório e export

- **Rota:** `/relatorio?from=AAAA-MM-DD&to=AAAA-MM-DD&habit_id=3&habit_id=5` (`reportPath`). Período (datas locais, inclusivas, até 5 anos, com períodos prontos) e hábitos (sem `habit_id`: todos, inclusive os arquivados) ficam na URL e só mudam no "Mostrar relatório"; período ausente ou inválido vira o ano atual até hoje. As informações (pontuação e sucesso/falha, recompensa, punição, gasto e limite, duração, observação e autor) são escolhidas na tela, sem buscar de novo; cada uma só aparece num hábito com o recurso ligado, e a observação começa desligada. A aba do hábito tem o atalho `reportPath({habitIds: [id]})`, e o menu, o link "Relatório".
- **Dados (`src/api/report.js`):** `GET /habits/progress` (em pedaços de até 5 anos e grupos de 100 ids) e as marcações pelo cache do ano dos calendários (`yearMarksQuery`: até 367 dias por chamada, seguindo o `next_cursor`), no máximo 4 chamadas ao mesmo tempo e só nos anos entre a primeira e a última marcação do hábito (`marks_range`). A consulta fica em `reportKeys.data(...)`, embaixo de `habitKeys.all`: mudar a configuração de um hábito (invalidar `habitKeys.all`) e mudar marcações (`afterMarksChanged`) refazem o relatório.
- **Modelo (`src/lib/export/report.js`):** `buildReport(dados, opções, {today})` junta tudo para a tela, o CSV, o JSON e a imagem: marcações só do período (pelo dia local), dias marcados, minutos, gasto, períodos encerrados com a meta cumprida (o atual não conta) e o período do limite de custo do fim do relatório.
- **CSV (`csv.js`):** uma linha por marcação (hábito, data, horário, autor, duração, custo, observação); coluna não escolhida, ou de recurso desligado em todos os hábitos, sai. RFC 4180 com BOM e CRLF, cabeçalho no idioma da tela, custo com ponto e 2 casas. Célula que começa com `=`, `+`, `-`, `@`, TAB ou CR ganha um `'` na frente (injeção de fórmula).
- **JSON (`json.js`):** `{version, generated_at, timezone, period, options, habits: [{configuração, marks, periods, cost_periods}]}`. O formato está em [`src/lib/export/schema.md`](frontend/src/lib/export/schema.md), com um JSON Schema que `json.test.js` usa para validar a saída (validador mínimo em `src/test/jsonSchema.js`, sem dependência nova): mudou o formato, mude o schema.
- **Imagem (`image.js`):** PNG 1080×1350 desenhado num `<canvas>`, sem lib: título e período, mapa de calor do período (fração dos hábitos marcados em cada dia; um hábito só usa a cor dele), um bloco por hábito com marcações, metas cumpridas e as informações escolhidas, e o rodapé com a data. Nunca traz emails nem observações. Cores e fonte vêm dos tokens e da paleta lidos em runtime (`readImageTheme`, `getComputedStyle` no `<html>`), então a imagem sai no tema da tela, com o contraste dos tokens. Todo texto é cortado com "…" na largura (`fitText`, `wrapSegments`); com muitos hábitos a letra diminui até um mínimo, depois somem as linhas de recompensa/punição e, por fim, o resto vira "+N hábitos" (10 hábitos sempre cabem).
- **Compartilhar ou baixar (`share.js`):** `navigator.canShare({files})` decide: com suporte, `navigator.share` (folha de compartilhamento do sistema); sem, download por um link temporário (`downloadBlob`). A tela gera a imagem antes ("Gerar imagem", com prévia) e compartilha num segundo clique, porque o `share` exige um gesto recente. Mudar o relatório, as informações, o idioma ou o tema descarta a imagem pronta. CSV e JSON só baixam.
- **"Exportar tudo" (ETH-38):** o componente `ExportAll` (`src/components/ExportAll`, dentro de `RequireSession`) tem os botões de JSON e CSV, com o estado e o erro. Por baixo, `exportAllFile(queryClient, {timeZone, format: 'json' | 'csv', t})` devolve o File de todos os hábitos (inclusive arquivados), de todas as informações e de todo o período: uma chamada de hoje descobre os hábitos e o `marks_range` de cada um, e o período vai da primeira marcação (ou da criação mais antiga) até hoje. Entregue o File com `downloadBlob(file, file.name)`.
- **Testes:** o jsdom não tem canvas. `drawReport(ctx, ...)` recebe o contexto 2D, e os testes passam um contexto falso (`fakeContext()` em `src/test/report.js`), que mede o texto como fonte monoespaçada e grava as chamadas: conferem o tamanho do canvas (1080×1350, com `getContext` e `toBlob` trocados), que todo texto fica dentro da imagem nos dois idiomas, que desligar uma informação a tira da imagem e que 10 hábitos com um ano de marcações saem inteiros e rápido. `src/test/report.js` também tem `progressItem`, `reportData`, `fullHabit`, `fullMark`, `mockProgressApi`, `imageTheme`, `translator` e `readFileText`.

### Painel de admin e banners

- **Acesso:** o link "Admin" do menu só aparece com `me.is_admin`, e as rotas `/admin/...` ficam dentro de `RequireAdmin`, que manda quem não é admin para a tela inicial. É conveniência: quem garante é o backend (`AdminUser`, 403), e a tela mostra o 403 se ele recusar.
- **Contas (`/admin`):** busca por trecho do email, status e datas de cadastro e de último login (datas no fuso do admin, como a API espera), com "carregar mais" pelo cursor. Bloquear, trocar o email e apagar abrem um painel que só libera o botão quando o admin digita o email da conta; desbloquear não pede confirmação. Uma ação por vez em cada conta.
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

O `axe` no jsdom não mede contraste. Por isso `src/styles/palette.test.js` calcula o contraste das 12 cores (mínimo 3:1 contra `--bg` e `--surface` dos dois temas, lidos de `packages/tokens/tokens.css`) e confere que os nomes são os do `HabitColor` de `app/models.py`.

`tests/build.test.js` roda o `vite build` de verdade em pastas temporárias e confere que os tokens de `packages/tokens` entram no CSS do ethos (e que trocar um token, por uma cópia apontada pelo alias `@tokens`, muda o CSS gerado), que o `index.html` carrega o `theme-init.js` no `<head>` sem `defer` e que não há script nem estilo inline.

## CI

O workflow [ethos.yaml](../../.github/workflows/ethos.yaml) roda em PRs e em push na `main` que tocam `apps/ethos/**`, `packages/**`, o próprio workflow ou os arquivos de infra que os testes conferem (`infra/apps/ethos/app.conf`, `infra/apps/ethos/app.env`, `infra/provision.sh`, `infra/scripts/snapshot.sh` e `infra/lib/backups.sh`). Por enquanto só faz checagens, sem deploy:

- backend: `uv lock --check`, `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest --cov` e 100% de cobertura nos módulos de `FULL_COVERAGE`;
- frontend: `npm ci`, `npm run lint`, `npm run build` e `npm test`.
