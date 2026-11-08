# imago

A conta única do `manasomali.com`: login, sessão, termos, exclusão de conta e o envio de todos os emails, para o site e todas as aplicações. Servido em `manasomali.com/imago/`, com API em `manasomali.com/api/imago/`. Segue a convenção de [apps/README.md](../README.md); o plano é o [imago-plan.md](../../imago-plan.md).

| Pasta | O quê |
|---|---|
| `backend/` | API em Python + FastAPI, gerenciada pelo [uv](https://docs.astral.sh/uv/), porta 3003 |
| `frontend/` | React + Vite, servido em `/imago/` |

Back e front são independentes: cada um tem as suas dependências e o seu lockfile. O imago não importa código do ethos nem de outra aplicação, e elas não importam o dele: falam só por HTTP local (ver [API interna](#api-interna)).

## Requisitos

- [uv](https://docs.astral.sh/uv/getting-started/installation/). Ele instala sozinho a versão do Python fixada em `backend/.python-version` (a mesma do ethos).
- Node 22 e npm.

## Backend

```bash
cd apps/imago/backend
uv sync                                       # cria a .venv com as dependências de dev
cp .env.example .env                          # config local; o .env fica fora do git
uv run --env-file .env alembic upgrade head   # cria ou atualiza o banco (DATABASE_PATH)
uv run --env-file .env python -m app.cli seed # contas de exemplo 101, 102 e 103 (opcional)
uv run --env-file .env uvicorn app.main:app --reload --port 3003 --root-path /api/imago
```

A API sobe em `http://127.0.0.1:3003`, na porta de produção, porque as aplicações em dev chamam o imago nela (`IMAGO_INTERNAL_URL`). Como em produção, as rotas ficam na raiz (`http://127.0.0.1:3003/health`) e o prefixo público entra pelo `--root-path`: em produção o nginx tira o `/api/imago` antes de repassar a request. No Git Bash (Windows), o MSYS converte `/api/imago` num caminho do Windows: rode o comando no PowerShell ou prefixe com `MSYS_NO_PATHCONV=1`. A documentação interativa (`/docs`, `/redoc` e o schema em `/openapi.json`) só existe com `APP_ENV=dev`; abra pelo proxy do Vite, com o front rodando, em `http://localhost:5175/api/imago/docs`. Fora de dev os três respondem 404: o schema listaria as rotas internas e as de admin para qualquer um.

Testes e lint:

```bash
uv run pytest                              # com cobertura; falha abaixo de 85%
uv run ruff check                          # lint (--fix corrige o que der)
uv run ruff format                         # formata; --check só confere, como no CI
uv run coverage report --fail-under=100 --include=app/admin/accounts.py,app/admin/router.py,app/audit.py,app/auth/deps.py,app/auth/origin.py,app/auth/router.py,app/auth/security.py,app/auth/service.py,app/body_limit.py,app/config.py,app/deletion.py,app/import_users.py,app/internal/deps.py,app/internal/router.py,app/internal/tasks.py,app/mail/quota.py,app/mail/sender.py,app/reapply.py,app/retention.py,app/seed.py   # depois do pytest
```

Os módulos da lista acima precisam de 100% de cobertura (linhas e ramos); ela fica na variável `FULL_COVERAGE` do workflow. Os testes não precisam de `.env`: as fixtures de `tests/conftest.py` montam a config com um SQLite em arquivo temporário (`settings`, `make_settings`, `engine`, `db_session`, `outbox`, `apps`, `task_context`, `app`, `client`, `make_client`, `smtp_server`, `make_smtp_server`, `make_account`). O banco de teste já vem com o schema completo: as migrações rodam uma vez por execução do pytest e cada teste recebe uma cópia. `tests/factories.py` tem `new_user`, `save` e `count`; `tests/auth_helpers.py`, o login completo (`login`), `cookie`, `open_session` e o `Outbox` (email em memória); `tests/internal_helpers.py`, os tokens de teste do ethos e do engrafi e `bearer(token)`; `tests/apps_helpers.py`, as aplicações falsas (`FakeApps`, num `httpx2.MockTransport`) que recebem as tarefas do imago: o `app` dos testes já vem ligado a elas (fixture `apps`), e nenhum teste chama a rede (uma chamada que escape delas falha o teste).

Dependências entram com `uv add <pacote>` (ou `uv add --dev <pacote>`), que atualiza o `pyproject.toml` e o `uv.lock`. Os dois vão juntos no commit.

### Configuração

Toda a config vem de variáveis de ambiente, lidas e validadas por `app/config.py` na subida. Variável obrigatória faltando ou valor inválido derruba o servidor com a lista do que está errado, sem mostrar os valores (passam por aqui a senha do SMTP e os tokens). Variável vazia conta como não definida.

| Variável | O quê |
|---|---|
| `APP_ENV` | `prod` ou `dev`. Com `prod`, o email de console é recusado e o `APP_URL` precisa ser https |
| `APP_URL` | URL pública do front (`https://manasomali.com/imago`). A origem dela é a única aceita no header `Origin` |
| `DATABASE_PATH` | arquivo SQLite (`/var/lib/sqlite/imago/app.db` em produção) |
| `SUPPORT_EMAIL` | contato da tela de conta (troca de email) e destino do aviso de teto de envio |
| `MAIL_FROM_ADDRESS` | remetente de todos os emails (`no-reply@manasomali.com`); o nome é "manasomali.com" ou o da aplicação |
| `EMAIL_BACKEND` | `smtp` ou `console` (só com `APP_ENV=dev`: o email, com o código, sai no terminal) |
| `IMAGO_APPS` | aplicações que usam o imago, na ordem da tela de conta: `ethos=http://127.0.0.1:3001[,engrafi=http://127.0.0.1:3002]`. Pode ficar vazia |
| `MAX_EMAILS_PER_DAY`, `MAX_EMAILS_PER_HOUR` | teto de envio em janelas móveis de 24 h e 1 h (padrão 275 e 60) |
| `MAIL_RESERVED_FOR_CODES_PER_DAY`, `MAIL_RESERVED_FOR_CODES_PER_HOUR` | fim de cada janela reservado a códigos e emails de conta (padrão 60 e 15) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | credenciais SMTP (`/etc/infra/smtp.env`), obrigatórias com `EMAIL_BACKEND=smtp` |
| `IMAGO_APP_TOKENS` | token da API interna de cada aplicação: `ethos:<token>[,engrafi:<token>]` (`/etc/infra/internal/imago.env`) |

Validação do `IMAGO_APPS` e do `IMAGO_APP_TOKENS` na subida: nome de aplicação com a regra do `infra/databases.txt` (`^[a-z][a-z0-9-]{1,26}$`, nunca `imago`), URL só `http://127.0.0.1:<porta>` (sem caminho), nada repetido, token base64url de 32 a 512 caracteres, um token para cada aplicação do `IMAGO_APPS` e nenhum token igual em duas aplicações (é o token que diz quem chamou). Um token de uma aplicação fora do `IMAGO_APPS` é aceito na subida, mas não autentica nada.

O `.env.example` já serve para desenvolver: `APP_ENV=dev`, `EMAIL_BACKEND=console`, o banco em `imago-dev.db`, `APP_URL` no nginx de desenvolvimento (`http://localhost:8080/imago`) e o ethos no `IMAGO_APPS` com um token só de dev, que vai também no `INTERNAL_API_TOKEN` do `.env` do ethos. Os nomes do `.env.example` são exatamente os da config e os do `infra/apps/imago/app.env` + `smtp.env` + `IMAGO_APP_TOKENS` (`tests/test_env_files.py` confere). Variável nova entra no `app/config.py`, no `.env.example` e no `infra/apps/imago/app.env` (ou no `smtp.env`, se for credencial), com a mudança no `app.env` num PR anterior ao do código que a exige.

### Banco, erros e logs

- `app/db.py`: o mesmo do ethos. Engine síncrona com `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON` e `secure_delete=ON` em toda conexão nova. Endpoints que usam o banco são `def` (nunca `async def`) e recebem a sessão por `SessionDep`. Toda escrita vai dentro de `with write_transaction(session):` (`BEGIN IMMEDIATE`); escrita do ORM fora dele é recusada.
- `app/models.py`: `users`, `sessions`, `login_codes`, `audit_log`, `mail_log` e `app_tasks`. Datas sempre em UTC; enums e tamanhos com `CHECK` no banco. `users.id` é um inteiro aleatório de 1 a 2^53 - 1 (`generate_account_id`), sorteado ao criar a conta, nunca sequencial: a coluna é `BIGINT` (não vira o rowid do SQLite), então uma conta sem id é recusada em vez de ganhar o maior id + 1. `users.email` é único, só ASCII, salvo com strip + lower. `users.status` é `active` ou `deleting`; `terms_version` e `terms_accepted_at` vazios só numa conta que ainda não aceitou nenhuma versão (as importadas do ethos). Apagar um usuário apaga em cascata as sessões, os códigos e as tarefas, e deixa `NULL` o `audit_log.user_id`. `app_tasks` tem no máximo uma tarefa pendente por (`user_id`, `app`, `action`) (índice único parcial `uq_app_tasks_pending`).
- `app/errors.py`: catálogo de códigos (`ErrorCode`), com `mail_quota` além dos do ethos. Toda resposta de erro sai como `{"error": "<codigo>", "field": "<campo>" | null}`.
- `app/logs.py`: uma linha por request (método, rota declarada, status e duração). Nunca IP, query string, corpo, headers (nem os `X-User-*`), cookies, email, código ou token.
- `app/body_limit.py`: corpo de qualquer request até 100 KB, conferido pelo `Content-Length` antes de ler o corpo; acima disso, ou sem `Content-Length` (chunked), 422 `validation_error`.
- `GET /health`: 200 `{"status": "ok"}` se o banco responde a `SELECT 1`; senão 503 `database_unavailable`.

### Migrações

O schema é criado e alterado só pelo Alembic, com `alembic.ini` e `migrations/` na pasta do backend, como no ethos. **Desvio do plano**: a árvore do `imago-plan.md` mostra `alembic/versions/`, mas a pasta é `migrations/`, porque os scripts de deploy compartilhados (`packages/deploy/`, vindos de `apps/ethos/deploy/`) dependem desse layout. O banco vem de `DATABASE_PATH`.

```bash
uv run --env-file .env alembic upgrade head      # aplica as migrações que faltam
uv run --env-file .env alembic current           # revisão em que o banco está
uv run --env-file .env alembic downgrade -1      # desfaz a última
```

As regras são as do ethos (seção "Migrações" do [apps/ethos/README.md](../ethos/README.md)): uma transação só por execução, chaves estrangeiras desligadas durante a migração e conferidas antes do commit, só modo online, migração escrita à mão (`uv run alembic revision --rev-id 0002 -m "descricao"`) e `app/models.py` no mesmo PR. `tests/test_migrations.py` sobe, desce e sobe de novo e compara o banco migrado com os modelos (drift).

### Auditoria e retenção

- `app/audit.py`: `audit.record(session, AuditEvent.X, user_id=..., ip=..., details={...})` dentro do `write_transaction` da mudança. Lista fechada: eventos de auth (`code_requested`, `login`, `login_failed`, `logout`, `logout_all`, `delete_code_requested`, `send_cap_reached`), da conta (`terms_accepted`, `profile_updated`, `account_deletion_started`, `account_deleted`) e do admin (`admin_created`, `user_blocked`, `user_unblocked`, `email_changed`). Ação sobre outra conta leva o id dela em `details.target_user_id`. Nenhuma chave com `code`, `token`, `cookie`, `password` etc. no `details`.
- `app/retention.py` (pelo `cleanup`, de hora em hora): eventos de auth com mais de 90 dias saem; IPs do `audit_log` e de `sessions` com mais de 90 dias viram `NULL`; sessões vencidas saem; `login_codes` criados há mais de 1 dia saem (o limite por email conta essas linhas, então um código vencido continua no banco até lá); `mail_log` com mais de 48 h sai; tarefas concluídas há mais de 7 dias saem (as pendentes ficam).

### Login por código

Cadastro e login são o mesmo fluxo, sem senha: `POST /auth/code/request` com `{email}` manda um código de 6 dígitos, e `POST /auth/code/verify` com `{email, code, timezone, locale}` confere o código, cria a conta no primeiro acesso e abre a sessão.

- `app/auth/security.py` (ETH-16): código com `secrets.randbelow(10**6)` (sempre 6 dígitos), token com `secrets.token_urlsafe(32)`, id de conta aleatório, sha256 e comparação com `hmac.compare_digest`. No banco ficam só os hashes.
- `app/auth/service.py` (ETH-17): o código vale 10 minutos, uma vez só, por no máximo 5 tentativas (contadas antes de comparar, num `BEGIN IMMEDIATE`, e gravadas mesmo quando a resposta é erro); pedir outro invalida o anterior do mesmo propósito. Limite por email de 1 código por minuto e 5 por hora, somando login e exclusão de conta, contado pelas linhas de `login_codes`. Depois, o teto de envio compartilhado (tipo `code`). Conta bloqueada ou em exclusão ganha a linha do código (conta nos limites), mas nenhum email. Conta nova nasce com o id aleatório, `TERMS_VERSION` aceita e o fuso e o idioma do navegador; conta existente ignora os dois. O email de uma conta em exclusão não cria conta nova. `request_delete_code` e `use_delete_code` já existem para a exclusão de conta (ETH-61).
- `app/auth/router.py`: `request` responde sempre 202 com o mesmo corpo e headers (com conta, sem conta, bloqueada, em exclusão) e 429 `rate_limited` igual para qualquer email; `verify` responde 400 `invalid_code` (field `code`) para qualquer código recusado e 422 `invalid_timezone` para fuso desconhecido no primeiro acesso. Email só ASCII (até 254 caracteres): ele vai no header `X-User-Email` das aplicações.
- `app/terms.py`: `TERMS_VERSION = "2026-11-08"`, a mesma constante do front (`frontend/src/lib/legal.js`, conferida pelo `src/lib/legal.test.js`). Fica no código e muda no mesmo PR dos textos.

### Sessão, CSRF e conta

- Cookie `__Host-imago_session` (`app/auth/cookies.py`): `HttpOnly; Secure; SameSite=Lax; Path=/`, sem `Domain`, `Max-Age` de 400 dias. Quem decide a validade é o `expires_at` da sessão (60 dias sem uso): a renovação feita pelo `auth_request` não chega ao navegador.
- `app/auth/deps.py`: `CurrentUser` (sessão válida e termos atuais aceitos; senão 403 `terms_not_accepted`), `AdminUser` (`is_admin` lido do banco a cada request; senão 403 `forbidden`), `CurrentUserAnyTerms` (só `GET /me` e `POST /me/terms`, e a exclusão da conta na ETH-61) e `CurrentSession` (logout). Sem cookie, token desconhecido, sessão vencida, conta bloqueada ou em exclusão: 401 `unauthorized`. A sessão renova com o uso, no máximo uma escrita por dia (`RENEWAL_INTERVAL`), também pelo `/internal/session`.
- `app/auth/origin.py`: toda request que não seja GET, HEAD ou OPTIONS sem exatamente um `Origin` igual à origem do `APP_URL` leva 403 `forbidden`, antes de ler o corpo. `/internal/*` fica de fora (confere o token).
- Endpoints: `POST /auth/logout` (apaga a sessão atual e o cookie), `POST /auth/logout-all` (todas as sessões do usuário), `GET /me` (`{id, email, timezone, locale, is_admin, terms_version, current_terms_version, terms_pending, apps, support_email}`; `apps` são os nomes do `IMAGO_APPS`, e o link de cada um é `/<nome>/`), `PATCH /me` com `{timezone?, locale?}` (exige os termos atuais; fuso desconhecido: 422 `invalid_timezone`; `null` ou campo desconhecido: 422) e `POST /me/terms` com `{terms_version}` (diferente da atual: 409 `conflict`). Atenção: no ethos era `/auth/me`; no imago é `/me`.
- Quando o idioma ou o fuso mudam, o `PATCH /me` cria uma tarefa `refresh` para cada aplicação (ver [Tarefas para as aplicações](#tarefas-para-as-aplicações)).

### API interna

Só entre os serviços, direto em `127.0.0.1:3003`, nunca pelo nginx (que responde 404 para `/api/imago/internal/`).

- `GET /internal/session`, sem token, chamado pelo `auth_request` do nginx em cada request de `/api/<app>/`: sempre 200 e corpo vazio. Com cookie válido, conta ativa e termos atuais aceitos, devolve `X-User-Id` (decimal), `X-User-Email`, `X-User-Locale`, `X-User-Timezone` e `X-User-Admin: 1` (só para admin); em qualquer outro caso, nenhum deles. Renova a sessão com a regra de uma escrita por dia. Responde igual a qualquer método, caso o nginx repasse o do request original.
- Todo o resto de `/internal/*` exige `Authorization: Bearer <token da aplicação>` (`app/internal/deps.py`, `CallerApp`), comparado em tempo constante com os do `IMAGO_APP_TOKENS`; sem token ou com token errado, 401. O token diz qual aplicação chamou: é esse nome que vai no `mail_log` e no remetente, nunca um que venha no corpo. O `router` de `app/internal/router.py` põe a dependência em todas as rotas dele, e um teste confere, pelo OpenAPI, que toda rota de `/internal/` (menos `/internal/session`) responde 401 sem token.
- `POST /internal/mail` `{kind: "notification", user_id, subject, text, html}`: 202 `{"status": "accepted"}` com a linha do `mail_log` gravada (o SMTP roda depois, em BackgroundTasks; a falha vira uma linha de log); 204 para conta bloqueada ou em exclusão (sem envio e sem contar); 404 `not_found` para id inexistente; 429 `mail_quota` com o teto de notificações atingido; 422 na validação (assunto até 200 caracteres numa linha só, campos desconhecidos recusados). O destinatário é sempre um usuário do imago, por id.
- `POST /internal/users/lookup` `{email}` (convites; o email vai no corpo, nunca na URL): 200 `{id, locale}` da conta com esse email (normalizado como no login); 404 `not_found` se ela não existe, está bloqueada ou em exclusão (a mesma resposta nos três casos); 422 com email inválido ou campo desconhecido.
- `GET /internal/users/{id}`: 200 `{id, email, locale, timezone, active}` (`active`: não bloqueada e fora de exclusão); 404 `not_found`; 422 com id fora de 1 a 2^53 - 1.

### Tarefas para as aplicações

O imago chama a API interna de cada aplicação do `IMAGO_APPS` (`app/internal/tasks.py`), com o token dela e timeout de 10 s, guardando cada pedido em `app_tasks`:

- `delete` (`POST /internal/users/{id}/delete`, sem corpo): a exclusão de conta;
- `refresh` (`POST /internal/users/{id}/refresh` com `{email, locale, timezone}`): o `PATCH /me` quando o idioma ou o fuso mudam e a troca de email pelo admin.

Regras:

- `request_tasks`, na mesma transação da mudança, cria uma tarefa por aplicação, no máximo uma pendente por (conta, aplicação, ação): pedir de novo com uma pendente não cria linha nova.
- Depois do commit, `schedule` tenta as tarefas em `BackgroundTasks`; o que falhar fica para o `run-tasks` do `imago-cleanup.timer`, de hora em hora. Só a resposta 200 conta como sucesso (outro status, erro de conexão e timeout são falha), e cada aplicação é chamada à parte: uma fora do ar não impede as outras.
- Sucesso grava `done_at`; falha soma 1 em `attempts` e grava `last_attempt_at`, com uma linha de aviso no log. A partir da 5ª falha seguida, cada tentativa grava uma linha de erro (`journalctl -u app-imago -p err`, ou o do `imago-cleanup`), com o id da conta, a aplicação e o motivo (status HTTP ou tipo do erro), nunca o email.
- O `refresh` manda os valores da conta na hora da chamada. Se a conta muda durante a chamada (a mudança achou a tarefa pendente e não criou outra), a chamada se repete com os valores novos antes de a tarefa ser concluída.
- Uma tarefa de uma aplicação que saiu do `IMAGO_APPS` não é chamada: conta como falha a cada execução, até a aplicação voltar ou alguém apagar a tarefa à mão.
- Dentro do processo, a mesma tarefa nunca roda em duas threads ao mesmo tempo. Entre o servidor e o `run-tasks`, no pior caso a mesma tarefa é chamada duas vezes, o que as aplicações aceitam (as duas rotas são idempotentes).

### Exclusão de conta

Pela própria pessoa: `POST /me/delete/request` manda um código de exclusão ao email atual (202, com os mesmos limites, validade e tentativas do código de login; 409 `last_admin` para o último admin ativo) e `DELETE /me` com `{code}` começa a exclusão (204 e o cookie apagado; código recusado: 400 `invalid_code`, field `code`; último admin: 409). Os dois funcionam com os termos pendentes. Pelo admin, sem código: `DELETE /admin/users/{id}`. Os dois usam `app/deletion.py`, em três passos:

1. **Na request**, numa transação `BEGIN IMMEDIATE`: confere que a conta não é o último admin ativo, muda o status para `deleting`, apaga as sessões, os códigos e as tarefas `refresh` pendentes, cria uma tarefa `delete` para cada aplicação do `IMAGO_APPS` e grava `account_deletion_started` (quem pediu: a própria pessoa ou o admin). Depois do commit, uma linha no log com só o id: `INFO app.deletion: conta <id> excluída`. A partir daí a pessoa não entra, não recebe código e o email dela não cria conta nova.
2. **Depois da resposta** (`BackgroundTasks`): o `POST /internal/users/{id}/delete` de cada aplicação, pelas tarefas. O que falhar fica para o `run-tasks`, de hora em hora.
3. **Quando não sobra tarefa `delete` pendente** (logo depois do passo 2 ou no `run-tasks`), numa transação `BEGIN IMMEDIATE` que confere se a linha ainda existe, então roda uma vez só mesmo com a request e o `run-tasks` terminando ao mesmo tempo: apaga a auditoria da própria conta (auth, termos, perfil, `admin_created` e o `account_deletion_started`), tira o IP e os emails das linhas que citam a conta (pelo `user_id`, pelo email ou pelo `details.target_user_id`, como a troca de email pelo admin), apaga os códigos de todos os emails que a conta teve (menos os de um email antigo que já é de outra conta), apaga a linha em `users` (o CASCADE leva sessões, códigos e tarefas) e grava `account_deleted` com o id e quem apagou (`user_id` do admin, ou vazio quando foi a própria pessoa), sem email nem IP. Depois do commit, o email "conta excluída" vai para o endereço lido, pelo teto de envio (tipo `account`).

Emails de conta (conta excluída, troca de email) recusados pelo teto não saem, e o `SUPPORT_EMAIL` recebe o aviso de teto, como nos códigos (no máximo um por hora). Com o `IMAGO_APPS` vazio, os três passos rodam na própria request.

#### Depois de restaurar um backup

O backup (do imago ou de qualquer aplicação) traz de volta as contas apagadas depois dele. Antes de abrir os serviços de novo, rode o `reapply-deletions` do imago com as linhas do journal do `app-imago` (roteiro completo no `infra/RESTORE.md`):

```bash
# imago_cli: ver "Comandos de operação (CLI)"
sudo journalctl -u app-imago -o cat --no-pager \
  | "${imago_cli[@]}" /opt/apps/imago/.venv/bin/python -m app.cli reapply-deletions
"${imago_cli[@]}" /opt/apps/imago/.venv/bin/python -m app.cli run-tasks   # o que ficou pendente
```

Ele lê as linhas `conta <id> excluída` (as outras são ignoradas) e, sem mandar email: refaz a exclusão inteira da conta que ainda existe no imago (com o `delete` de todas as aplicações do `IMAGO_APPS`; a que falhar fica como tarefa, e o `run-tasks` a termina) e chama o `delete` de cada aplicação para a conta que já não existe no imago (o caso de um banco de aplicação restaurado). O último admin ativo é pulado com um aviso. Pode rodar quantas vezes quiser. As exclusões dependem do journald (limite de 100M, e some junto se a VM for perdida): é um risco aceito no plano.

### Admin de contas

`app/admin/router.py` (rotas) e `app/admin/accounts.py` (regras). Tudo exige `AdminUser` (sessão, termos atuais aceitos e `is_admin` lido do banco): sem sessão 401, usuário comum 403 `forbidden`, termos pendentes 403 `terms_not_accepted`. Cada escrita confere de novo, dentro do `BEGIN IMMEDIATE`, que quem age continua admin ativo (401 se foi bloqueado ou entrou em exclusão no meio, 403 se perdeu o admin), e grava no `audit_log` com `user_id` = o admin e a conta alvo em `details.target_user_id`.

- `GET /admin/users?email&status&cursor&limit`: `{"users": [AdminUser], "next_cursor"}`, das contas mais novas para as mais antigas (`created_at`, id), paginadas por cursor (sem OFFSET). `email` é um trecho (espaços e maiúsculas não importam; `%` e `_` são letras); `status` é `active`, `blocked` (`is_active` falso) ou `deleting`; `limit` de 1 a 200, padrão 50. `AdminUser` = `{id, email, status ("active"|"deleting"), is_active, is_admin, timezone, locale, created_at, last_login_at|null}`, datas em ISO 8601 UTC.
- `PATCH /admin/users/{id}` com `{is_active}` (só `true`/`false`): bloquear apaga as sessões da conta (`user_blocked`, com quantas) e a pessoa não entra nem recebe código; desbloquear grava `user_unblocked`. Sem mudança, nada é gravado. A própria conta: 409 `cannot_block_self`. Bloquear nunca tira o último admin ativo: quem bloqueia é um admin ativo diferente da conta bloqueada, e dois admins que se bloqueiam ao mesmo tempo esperam um pelo outro (o segundo já não é admin ativo: 401).
- `PATCH /admin/users/{id}/email` com `{new_email}` (normalizado como no login): 409 `email_in_use` (field `new_email`) se o email já tem conta, inclusive o atual dela, sem mudar nada. Na troca: apaga as sessões da conta, vence os códigos pendentes do email antigo e da conta, grava `email_changed` (`old_email`, `new_email`, `sessions`), cria uma tarefa `refresh` para cada aplicação e manda depois da resposta os avisos ao email antigo e ao novo, no idioma da conta (cada um pelo teto de envio; recusado, avisa o suporte).
- `DELETE /admin/users/{id}`: 204; o passo 1 da [exclusão de conta](#exclusão-de-conta), com as aplicações chamadas depois da resposta. Último admin ativo: 409 `last_admin`. Conta bloqueada também é apagada. O admin apagando a própria conta conta como exclusão pela própria pessoa. Conta já em exclusão: 204 sem gravar nada, e as aplicações que faltam são chamadas de novo.
- `GET /admin/mail`: `{"window_hours": 24, "by_app": [{app, code, account, notification}], "day": {sent, limit, notification_limit}, "hour": {...}}`. `by_app` traz o imago e cada aplicação do `IMAGO_APPS`, nessa ordem e com zero se não mandaram nada, e depois uma aplicação que saiu do `IMAGO_APPS` e ainda tem envios na janela; `sent` é a contagem de cada janela móvel do teto, `limit` o teto de códigos e emails de conta e `notification_limit` onde as notificações param.

Conta em exclusão aparece na listagem, mas bloquear, desbloquear e trocar o email dela dão 404 `not_found`, como uma conta que já não existe: ela está saindo de todas as aplicações. Conta inexistente: 404.

### Email e teto de envio

Só o imago fala com o SMTP (a unit dele é a única que lê o `smtp.env`), pelo pacote `app/mail/`:

- `sender.py`: `Mailer`, `OutgoingEmail` (emails do próprio imago, do catálogo, com "manasomali.com" no remetente), `Notification` (emails prontos das aplicações, com o nome da aplicação no remetente) e `schedule(background_tasks, mailer, outgoing)`, chamado depois que o `write_transaction` fechou. Falha de envio vira uma linha de erro com o tipo do email e do erro, sem destinatário, código nem corpo, e não derruba o request.
- `backends.py`: SMTP só com STARTTLS e certificado verificado (sem STARTTLS, nada sai) e o backend de console, recusado fora de `APP_ENV=dev`.
- `catalog.py` e `templates.py`: os emails do imago em pt e en (código de login, código de exclusão, conta excluída, troca de email para o antigo e para o novo, teto atingido para o suporte). Assunto fixo por tipo e idioma, sem código nem email; todo dado escapado no HTML. Idioma pelo `users.locale` ou pelo `Accept-Language` (`language.py`), com `en` quando nada bate.
- `quota.py`: um teto só para o imago e todas as aplicações, contado pelas linhas de `mail_log` (aplicação, tipo e instante, sem destinatário) em janelas móveis de 24 h e de 1 h. Códigos e emails de conta param em `MAX_EMAILS_PER_DAY`/`MAX_EMAILS_PER_HOUR`; notificações param antes, quando sobram só as reservas (`MAIL_RESERVED_FOR_CODES_*`). A linha é gravada na mesma transação `BEGIN IMMEDIATE` que confere o teto, antes do SMTP. Quando um código (ou email de conta) é recusado, o `SUPPORT_EMAIL` recebe um aviso, no máximo um por hora (o último é o evento `send_cap_reached`, lido e gravado na mesma transação), fora da contagem.

Nos testes, a fixture `smtp_server` sobe um servidor SMTP falso (aiosmtpd) com STARTTLS e login obrigatórios; o `app` padrão usa o `outbox`, em memória.

### Comandos de operação (CLI)

```bash
uv run --env-file .env python -m app.cli --help      # lista os comandos
uv run --env-file .env python -m app.cli cleanup     # aplica a retenção de dados
uv run --env-file .env python -m app.cli run-tasks   # tarefas pendentes para as aplicações
uv run --env-file .env python -m app.cli create-admin voce@example.com   # torna a conta admin
uv run --env-file .env python -m app.cli seed        # contas de exemplo (só em dev)
```

O CLI lê a mesma config do servidor e abre o banco de `DATABASE_PATH`, que precisa existir e estar migrado. Código de saída 0 em sucesso, 1 em erro (a mensagem sai no stderr com `erro:`, sem stack trace nem valores) e 2 em uso errado. As contas aparecem pelo id, nunca pelo email.

| Comando | O quê |
|---|---|
| `cleanup` | Retenção de dados (ver acima), numa transação só. Imprime quantas linhas mudou em cada passo; a segunda execução seguida não muda nada. Roda de hora em hora pelo `imago-cleanup.timer` (ETH-57), depois do `run-tasks`. |
| `run-tasks` | Tenta as tarefas pendentes para as aplicações ([Tarefas para as aplicações](#tarefas-para-as-aplicações)) e termina as exclusões de conta sem tarefa `delete` pendente (passo 3, com o email "conta excluída"). Imprime quantas tarefas tentou, concluiu, quantas falharam, quantas ficaram para depois (em andamento noutra thread ou com a conta mudando a cada chamada) e quantas exclusões terminou. Sai com 0 mesmo com falhas, que ficam gravadas e voltam na próxima execução; só um erro geral (config, banco) sai com 1. Roda de hora em hora pelo `imago-cleanup.timer`, antes do `cleanup`. |
| `import-users -` | Passagem do login do ethos ([roteiro](#passagem-do-login-do-ethos-eth-64-passo-3)), uma vez só: lê do stdin uma linha JSON por conta, no formato do `export-users` do ethos (`id`, `email`, `is_active`, `is_admin`, `timezone`, `locale`, `created_at`, `last_login_at`, datas ISO 8601 em UTC), e a linha final `{"end": true, "count": <total>}`, e grava todas numa transação só, com os mesmos ids, status `active` e sem o aceite dos termos (o imago pede no primeiro acesso). Não grava nada se uma linha não é JSON, se falta ou sobra um campo, se um valor é inválido (id de 1 a 2^53 - 1, email pela normalização do login, fuso IANA, idioma `pt` ou `en`), se um id ou email se repete na entrada ou já existe no imago: o erro diz a linha e o motivo (com o id da conta do imago que já existe), nunca o email. Também não grava nada sem a linha final (o export morreu no meio e o pipe fechou com parte das contas), com o total dela diferente do número de contas lidas ou com qualquer linha, mesmo em branco, depois dela. Só o stdin (`-`; recusa um terminal e uma entrada sem nenhuma conta): as contas nunca passam por arquivo. Imprime só as contagens (importadas, ativas, bloqueadas, admins), nunca email. |
| `reapply-deletions [id ...]` | Depois de restaurar um backup ([Depois de restaurar um backup](#depois-de-restaurar-um-backup)): lê do stdin as linhas do `journalctl -u app-imago -o cat` (ou ids soltos, um por linha), ou recebe os ids (de 1 a 2^53 - 1) como argumentos, e refaz as exclusões sem email. Recusa um terminal no stdin, entrada vazia e uma linha de exclusão fora do formato (nada é apagado). Imprime quantas contas apagou de novo no imago (e quantas esperam uma aplicação: rode o `run-tasks`), quantas já não existiam no imago, quantas pulou (último admin) e quantas chamadas às aplicações falharam. Sai com 1 se o `delete` de uma conta que já não existe no imago falhou numa aplicação (essa falha não fica gravada em lugar nenhum: rode de novo). Com o `IMAGO_APPS` vazio (o ensaio numa cópia), só o banco do imago muda. |
| `create-admin <email>` | Liga o `is_admin` de uma conta que já existe e grava `admin_created` (`{"via": "cli"}`). É o único jeito de criar admin: não existe endpoint para isso. O email é normalizado como no login. Email sem conta: erro, nada muda (a pessoa entra no imago uma vez antes). Conta bloqueada ou em exclusão: erro, nada muda. Conta que já é admin: avisa, sai com 0 e não grava nada. |
| `seed` | Só com `APP_ENV=dev`. Cria as contas de exemplo com ids fixos, que os seeds das aplicações usam: 101 `ana@example.com` (admin, `America/Sao_Paulo`, pt), 102 `bia@example.com` (`America/Sao_Paulo`, pt) e 103 `caio@example.com` (`Europe/Lisbon`, en), todas com os termos atuais aceitos (`app/seed.py`, `SEED_ACCOUNTS`). Se alguma já existe, não grava nada. |

Na VM, os comandos rodam como `app-imago`, com o mesmo ambiente e as mesmas proteções da unit (`infra/apps/imago/app-imago.service`), pelo `systemd-run`: os `EnvironmentFile=` são `0600` do root, então `sudo -u app-imago` não basta. Defina uma vez no shell:

```bash
imago_cli=(sudo systemd-run --quiet --pipe --wait --collect --uid=app-imago --gid=app-imago
  --working-directory=/opt/apps/imago
  -p EnvironmentFile=/etc/infra/smtp.env -p EnvironmentFile=/etc/infra/internal/imago.env
  -p EnvironmentFile=/etc/infra/apps/imago.env
  -p NoNewPrivileges=true -p ProtectSystem=strict -p ProtectHome=true -p PrivateTmp=true
  -p ReadWritePaths=/var/lib/sqlite/imago -p MemoryMax=150M
  -E PYTHONUNBUFFERED=1 -E PYTHONDONTWRITEBYTECODE=1)
"${imago_cli[@]}" /opt/apps/imago/.venv/bin/python -m app.cli create-admin voce@example.com
```

`--pipe` liga o stdin e o stdout do comando ao terminal (ou ao pipe), `--wait` espera e devolve o código de saída, e `--collect` não deixa a unit temporária para trás quando ele falha.

Comando novo: um handler `(context: CommandContext, args) -> int` em `app/cli.py`, registrado em `build_parser`. Erro esperado é `raise CommandError("mensagem")`.

### Passagem do login do ethos (ETH-64, passo 3)

A ordem completa está no [imago-plan.md](../../imago-plan.md) ("migração do login do ethos"). Este é o passo 3, na VM, depois do PR de infra A (o `auth_request` do ethos já pergunta ao imago, e o imago está no ar sem as contas do ethos) e com o `export-users` já publicado no ethos por um deploy normal. O ethos fica fora do ar daqui até o fim do deploy do PR do ethos.

1. Defina o `imago_cli` ([Comandos de operação](#comandos-de-operação-cli)) e o do ethos, com o ambiente e as proteções das units dele nesse ponto (`infra/apps/ethos/app-ethos.service`; o ethos de hoje ainda lê o `smtp.env`):

   ```bash
   ethos_cli=(sudo systemd-run --quiet --pipe --wait --collect --uid=app-ethos --gid=app-ethos
     --working-directory=/opt/apps/ethos
     -p EnvironmentFile=/etc/infra/smtp.env -p EnvironmentFile=/etc/infra/internal/ethos.env
     -p EnvironmentFile=/etc/infra/apps/ethos.env
     -p NoNewPrivileges=true -p ProtectSystem=strict -p ProtectHome=true -p PrivateTmp=true
     -p ReadWritePaths=/var/lib/sqlite/ethos -p MemoryMax=150M
     -E PYTHONUNBUFFERED=1 -E PYTHONDONTWRITEBYTECODE=1)
   ```

   O `ReadWritePaths` do ethos vale também para o export, que só lê: o SQLite em WAL precisa criar o `-shm` ao lado do banco.

2. Pare o ethos, para nenhuma conta nascer ou sumir no meio da passagem, e anote as contagens:

   ```bash
   sudo systemctl stop ethos-alerts.timer ethos-alerts.service app-ethos
   systemctl is-active ethos-alerts.timer ethos-alerts.service app-ethos   # inactive (3x)
   sudo -u app-ethos sqlite3 /var/lib/sqlite/ethos/app.db 'SELECT count(*) FROM users;'   # N
   sudo -u app-imago sqlite3 /var/lib/sqlite/imago/app.db 'SELECT count(*) FROM users;'   # M, normalmente 0
   ```

3. Export e import ligados por um pipe, sem arquivo em disco. O export termina com uma linha `{"end": true, "count": N}`, e o import só grava se a entrada acabar nela, com o total igual às contas lidas: se o export morrer no meio (falta de memória, erro no banco), o pipe fecha sem essa linha e o import recusa tudo, em vez de gravar só parte das contas. O `pipefail` faz um export que falhou aparecer também no código de saída:

   ```bash
   ( set -o pipefail
     "${ethos_cli[@]}" /opt/apps/ethos/.venv/bin/python -m app.cli export-users \
       | "${imago_cli[@]}" /opt/apps/imago/.venv/bin/python -m app.cli import-users - )
   echo "saída: $?"   # 0
   ```

   A saída esperada é `import-users: N contas importadas (A ativas, B bloqueadas, C admins)`, com o N do passo 2. O import é tudo ou nada, inclusive com a entrada cortada: se ele recusar a entrada (o erro diz a linha e o motivo, nunca o email; `a entrada acabou sem a linha final` quer dizer que o export falhou: veja o `erro:` dele no terminal ou, se ele foi morto por falta de memória, o `journalctl -k`), nada foi gravado no imago; corrija e rode de novo.

   Um id ou email que já existe no imago também é recusado: alguém achou o `/imago/` antes e criou uma conta (inclusive o admin testando o imago com o email dele). Essa conta não tem dados em lugar nenhum (o ethos de hoje não lê o imago), então apague-a direto no banco do imago, pelo id que o erro mostra, e rode o passo 3 de novo. Não use o painel nem o `DELETE /me`: essa exclusão espera o `delete` do ethos novo, e até lá a conta continua no imago.

   ```bash
   sudo -u app-imago sqlite3 /var/lib/sqlite/imago/app.db \
     "PRAGMA foreign_keys=ON; DELETE FROM users WHERE id = <id do erro>;"
   ```

4. Confira no imago: o total é M + N, os admins e bloqueados batem com os do ethos e ninguém tem os termos aceitos:

   ```bash
   sudo -u app-imago sqlite3 /var/lib/sqlite/imago/app.db \
     'SELECT count(*), sum(is_admin), sum(NOT is_active), sum(terms_version IS NULL) FROM users;'
   sudo -u app-ethos sqlite3 /var/lib/sqlite/ethos/app.db \
     'SELECT count(*), sum(is_admin), sum(NOT is_active) FROM users;'
   ```

   Até aqui o ethos não mudou: para desistir, `sudo systemctl start app-ethos ethos-alerts.timer` volta com o login antigo (as contas importadas ficam no imago; um import novo as recusaria).

5. Faça o merge do PR do ethos que troca o login (ETH-14, 26, 27, 60 e a migração `users` → `app_users`). O deploy sobe o ethos novo; confira:

   ```bash
   systemctl is-active app-ethos                          # active
   curl -fsS https://manasomali.com/api/ethos/health      # {"status":"ok"}
   ```

6. Religue os alertas: `sudo systemctl start ethos-alerts.timer`.
7. Entre em `/imago/entrar` com o email do admin, aceite os termos, abra `/ethos/` (os hábitos de antes estão lá) e `/imago/admin`.

Não rode o import de novo depois que ele deu certo: ele recusa os ids que já estão no imago.

### Regras

- Nunca logar email, código, token, cookie, IP nem os headers `X-User-*`. Nunca pôr código, token ou cookie no `details` da auditoria.
- Toda escrita num `write_transaction`, com as leituras que decidem a escrita dentro dele. Emails só depois do commit.
- Admin só pelo `create-admin`; o último admin ativo não é bloqueado nem apagado.
- Mudança no catálogo de erros entra também nos `translation.json` do front.
- Nada importa de `site/` nem de `apps/<outra>/`.

Pontos de extensão para as próximas tasks: `service.account_emails` reserva os emails de conta no teto (com o aviso ao suporte); `deletion.start_deletion` é o passo 1 da exclusão.

## Frontend

```bash
cd apps/imago/frontend
npm ci
npm run dev                                # http://localhost:5175/imago/
```

O dev server usa a porta 5175 (o site usa a 5173 e o ethos a 5174) e falha se ela estiver ocupada. Também dá para subir pela entrada `imago` do `.claude/launch.json`. Em dev, o Vite repassa `/api/imago/*` para o backend em `http://127.0.0.1:3003` (a porta de produção), sem o prefixo, como o nginx faz em produção; suba o backend antes de usar as telas que chamam a API. Em dev o site, o imago e as aplicações rodam em portas diferentes, então não dividem o cookie nem o `localStorage`: para o fluxo entre aplicações (o `next` de volta para o ethos), use o nginx de dev em `http://localhost:8080`.

```bash
npm run lint                               # ESLint com jsx-a11y; qualquer aviso falha
npm test                                   # vitest com cobertura, roda uma vez e sai
npm run build                              # gera dist/
npm run preview                            # serve o dist/ localmente
```

### Telas

| Rota | Tela | Login |
|---|---|---|
| `/imago/` | Conta: email (só leitura, com a troca pelo `support_email` do `GET /me`), as aplicações, idioma, fuso, sair, sair de todos os aparelhos e a exclusão da conta | sim; sem sessão vai para `/imago/entrar?next=/imago/`. Com termos pendentes mostra o aviso do aceite e só o que funciona sem ele (sair e excluir) |
| `/imago/entrar?next=<caminho>` | Entrar (email → código) e o aceite de termos novos. Destino do 401 do imago e de todas as aplicações | não |
| `/imago/termos`, `/imago/privacidade` | Termos de uso e política de privacidade de todas as aplicações | não |
| `/imago/admin` | Contas (busca, bloquear, trocar email, excluir) e os envios de email das últimas 24 h | `is_admin` e termos aceitos; quem não é admin volta para a conta, e termos pendentes vão para o aceite |

O rodapé de toda tela tem os links dos termos e da privacidade.

### Estrutura

| Caminho | O quê |
|---|---|
| `index.html` | Carrega `/imago/theme-init.js` no `<head>`, sem `defer`, antes do app |
| `public/theme-init.js` | Aplica o tema salvo (`localStorage.theme`) como `data-theme` antes da primeira pintura. É arquivo, não script inline, por causa da CSP (`script-src 'self'`) |
| `public/locales/{pt,en}/translation.json` | Traduções, baixadas em runtime (não vão no bundle). `errors.<codigo>` traduz os códigos da API; `apps.<nome>` tem os textos de cada aplicação (abaixo) |
| `src/main.jsx`, `src/bootstrap.js`, `src/App.jsx` | Inicia o i18n, cria o router (`basename="/imago"`) e o QueryClient (`createApp`): um 401 em qualquer chamada leva para a tela de entrar com o caminho atual no `next` |
| `src/routes.jsx`, `src/paths.js` | Todas as rotas e `BASENAME`/`PATHS` (`/`, `/entrar`, `/termos`, `/privacidade`, `/admin`). Use as constantes, nunca o caminho escrito à mão |
| `src/i18n.js` | `createI18n()`, `LANGUAGES` e a detecção do idioma (chave compartilhada `i18nextLng`; `pt-BR` vira `pt`) |
| `src/index.css` | Estilos globais. Importa as fontes e `@tokens/tokens.css` (alias para `packages/tokens`) |
| `src/api/account.js` | `/auth` e `/me`: `useMe`, `useSignedInMe` (o `/me` já carregado, sem buscar, só se a última busca deu certo: para o topo), `requestCode`, `verifyCode` (manda o fuso do navegador e o idioma da tela), `acceptTerms` (manda o `TERMS_VERSION`), `useUpdateMe` (`PATCH /me`; idioma novo vira também o da tela), `useLogout`, `useLogoutAll`, `requestAccountDeletion`, `useDeleteAccount` (os três limpam o cache e vão para a tela de entrar) |
| `src/api/admin.js` | `/admin`: `useAccounts(query)` (páginas por cursor), `setAccountActive`, `changeAccountEmail`, `deleteAccount`, `useMailStats` |
| `src/components/` | `Layout` (pular para o conteúdo, topo, `<main>`, rodapé), `Header` (conta, admin só para `is_admin`, volta ao site, idioma da tela e tema), `RequireSession`, `RequireAdmin`, `ErrorMessage`, `PageTitle`, `TextDocument` (texto puro com sumário e âncoras) |
| `src/pages/` | `Login` (`CodeForm` e `TermsAcceptance`), `Account` (`Apps`, `LanguageForm`, `TimezoneForm`, `Sessions`, `DeleteAccount`), `Legal`, `Admin` (`AccountCard`, `MailStats`), `NotFound` |
| `src/legal/{pt,en}/{terms,privacy}.json` | Textos legais (abaixo) |
| `src/lib/` | Utilitários sem React, com cobertura mínima de 80% (abaixo) |
| `src/test/` | Setup dos testes: MSW (`server`, `api(path)`, `apiError`, `trackRequests`), `renderApp(path)`, `meFixture()`, `signedIn()`, `createTestI18n()`, `axe`, `readFrontendFile()`; do admin, `src/test/admin.js` (`ADMIN`, `accountFixture`, `mailFixture`) |
| `tests/` | Testes do build de produção, no Node |
| `build-targets.js` | Converte o `browserslist` do `package.json` no `build.target` do Vite |

### `src/lib/`

- `api.js`: `apiFetch(path, {method, query, body, signal})` chama `/api/imago<path>` na mesma origem, com `credentials: 'include'` (o cookie `__Host-imago_session` é HttpOnly; o front nunca o lê). Erro sempre vira `ApiError {status, code, field}`: o código vem do corpo `{"error", "field"}` ou, quando o corpo não é JSON (o nginx responde 429, 502 e 504 em HTML), do status. Sem resposta: status 0 e `network_error`.
- `queryClient.js`: leitura só repete falha de rede e 5xx; escrita nunca repete; todo 401 chama `onUnauthorized`.
- `next.js`: o `next` da tela de entrar. `resolveNext(valor)` monta `new URL(next, location.origin)`, exige a mesma origem e recusa caractere de controle (C0, DEL e C1), `\` e o caminho que, resolvido, começa com `//` (`/.//site.com` e `/%2e%2e//site.com` dão o pathname `//site.com`, que o navegador leria como outro host); `next` ausente, inválido ou para a própria tela de entrar (em qualquer grafia que o router aceita) vira `/imago/`. `appRoute(caminho)` diz se o destino é do próprio imago (navegação pelo router) ou de fora (navegação de página inteira, por `pageLocation.replace` de `location.js`, que tira a tela de entrar do histórico).
- `session.js`: `loginPath(next)` (`/entrar?next=/imago/admin`, barras legíveis) e `redirectToLogin(router)`, o destino do 401. `SESSION_NOT_SAVED`: código só do front para o código aceito sem sessão no `/me` seguinte (cookie não guardado).
- `apps.js`: aplicações do `GET /me` (`accountApps`, nomes com a regra do `databases.txt`), `appPath(nome)` (`/<nome>/`) e `appTexts(nome, t, exists)`, os textos de `apps.<nome>` (sem tradução, o nome cru; `export_path` só vale na mesma origem).
- `legal.js`: `TERMS_VERSION`, `SUPPORT_EMAIL` (dos textos legais, que abrem sem login), `loadLegalDocument(nome, idioma)` e `contactEmail(valor)` (o `support_email` do `/me` se for um email simples).
- `admin.js`: filtros da listagem (`accountQuery`, `ACCOUNT_STATUSES`), `accountStatus` (`active`, `blocked` ou `deleting`), `confirmsEmail` (a confirmação digitando o email) e `accountApiPath(id)`.
- `mail.js`: o `GET /admin/mail` para a tela: `mailWindow` (quanto falta para o teto e para as notificações pararem) e `mailTable` (linhas por aplicação e totais).
- `code.js` (6 dígitos, `onlyDigits`, espera de 60 s para reenviar), `locale.js` (`apiLocale`), `time.js` e `timezones.js` (fuso do navegador, lista IANA com offset e busca sem acento), `datetime.js` (`formatDateTime` no fuso de quem vê), `theme.js` e `storage.js` (chaves compartilhadas sem lançar exceção).

### Login e `next`

Cadastro e login são a mesma tela: email → código de 6 dígitos (`inputmode="numeric"`, `autocomplete="one-time-code"`, reenviar depois de 60 s, "já tenho um código" depois de um 429). As mensagens são iguais para qualquer email. A tela busca o `/me` sempre que abre (nunca confia no cache, que pode ser de uma sessão que acabou):

- sem sessão (401): o formulário, com o aviso "ao continuar, você concorda com os termos de uso e a política de privacidade";
- com sessão e termos em dia: vai direto para o `next`;
- com sessão e termos pendentes: só o aceite (`POST /me/terms` com o `TERMS_VERSION` do build). Um 409 quer dizer que o backend já tem uma versão mais nova que a desta aba: a tela pede para recarregar a página, que traz os textos novos. Dá para sair dali, e quem não concordar pode excluir a conta na tela de conta.

As aplicações mandam para `/imago/entrar?next=<caminho atual>` quando a API delas responde 401 (termos pendentes contam como sem login para elas).

### Textos de cada aplicação

Cada aplicação do `IMAGO_APPS` tem, nos dois `translation.json`, o objeto `apps.<nome>` com `name`, `description` (lista da tela de conta), `deletion` (o que some na exclusão), `export_label` e `export_path` (caminho absoluto do export, ex.: `/ethos/relatorio`, a tela do "exportar tudo"). `src/lib/apps.test.js` confere as 5 chaves em pt e en e que o export do ethos é o `PATHS.report` de `apps/ethos/frontend/src/paths.js`; o `.github/scripts/check-imago-apps.sh` confere que toda aplicação do `IMAGO_APPS` tem os dela. Aplicação nova: acrescente os textos e a seção dela nos termos e na privacidade (versão nova dos termos).

### Termos e privacidade

Os textos ficam em `src/legal/<idioma>/<documento>.json` (`terms` e `privacy`, em `pt` e `en`), texto puro, no mesmo formato do ethos: `{title, sections: [{id, title, paragraphs}]}`, cada parágrafo um texto ou uma lista de textos, e o único marcador é `{{supportEmail}}`. A parte geral vale para todas as aplicações; cada aplicação tem uma seção com o nome dela como `id` (`/imago/termos#ethos`). Os JSON não vão no bundle principal: cada um vira um chunk com hash.

`src/lib/legal.test.js` falha se a versão for diferente do `TERMS_VERSION` de `backend/app/terms.py`, se pt e en não tiverem as mesmas seções (mesmos ids, na mesma ordem e com a mesma forma), se um texto tiver marcação ou outro marcador, se faltar a seção de uma aplicação de `apps`, se a política não citar o cookie `__Host-imago_session` e se os prazos não baterem (sessão 60 dias, código 10 minutos, eventos de auth e IPs 90 dias, contagem de emails 48 horas e cópias de segurança de `infra/scripts/snapshot.sh` e `infra/lib/backups.sh`). O `SUPPORT_EMAIL` é comparado com o de `infra/apps/imago/app.env` quando esse arquivo existe.

Para publicar uma versão nova (inclusive a entrada de uma aplicação nova): mude os textos nos dois idiomas, `TERMS_VERSION` aqui e em `backend/app/terms.py`, no mesmo PR. Os textos são um rascunho técnico e precisam da revisão do dono antes de entrar no ar.

### Testes

Os testes rodam no vitest em dois projetos: `app` (jsdom, `src/**/*.test.*`, com MSW, i18n e o setup de `src/test/setup.js`) e `build` (Node, `tests/*.test.js`). `npm test` liga a cobertura e falha abaixo de 80% em `src/lib/`. Toda request sem handler do MSW falha o teste, e todo teste de tela confere acessibilidade com o `axe` de `src/test/axe.js`:

```jsx
expect(await axe(container)).toHaveNoViolations();
```

Navegação de página inteira (o `next` de outra aplicação, recarregar a página) passa por `pageLocation` (`src/lib/location.js`), que os testes trocam com `vi.spyOn`: o jsdom não navega. Checagens entre áreas: a versão dos termos (`backend/app/terms.py`), o catálogo de erros (`backend/app/errors.py`: todo código tem tradução) e o export do ethos.

`tests/build.test.js` roda o `vite build` de verdade e confere que os tokens de `packages/tokens` entram no CSS (e que trocar um token muda o CSS), que o `index.html` carrega o `theme-init.js` no `<head>` sem `defer`, que não há script nem estilo inline, que tudo é servido em `/imago/` e que os textos legais ficam fora do bundle principal.

## CI

O workflow [imago.yaml](../../.github/workflows/imago.yaml) roda em PRs e em push na `main` que tocam `apps/imago/**`, `packages/**`, o próprio workflow ou os arquivos lidos pelas checagens (`infra/apps/*/app.conf`, `infra/apps/imago/app.env`, `infra/provision.sh`, `infra/scripts/snapshot.sh`, `infra/scripts/restore-test.sh`, `infra/lib/backups.sh`, `infra/config.env`, `infra/lib/common.sh`, `infra/lib/packages.sh`, `.github/scripts/check-python-version.sh` e `.github/scripts/check-imago-apps.sh`). Em PRs, só as checagens:

- backend: `check-python-version.sh`, `uv lock --check`, `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest --cov` (85%) e 100% de cobertura nos módulos de `FULL_COVERAGE`;
- frontend: `npm ci`, `npm run lint`, `npm run build` e `npm test`;
- consistência com a infra: `.github/scripts/check-imago-apps.sh` (o `IMAGO_APPS` do `infra/apps/imago/app.env` tem toda aplicação de `infra/apps/`, com a porta do `app.conf` dela, e cada uma tem os textos da tela de conta em pt e en). O backend compara o `.env.example` com o `app.env`, o `smtp.env` e o `IMAGO_APP_TOKENS` (`tests/test_env_files.py`);
- scripts do deploy ([packages/deploy/](../../packages/deploy/README.md)): `shellcheck`, `test-deploy-scripts.sh` (limpeza de assets, migrações do rollback e recusa de nome de aplicação inválido) e `test-vm.sh imago`, que roda o `vm.sh` num Ubuntu 24.04 com o uv e o Python instalados pelas funções do provision: `.venv`, migração e `/health` como `app-imago` (com o `.env.example`, trocando só o `DATABASE_PATH`), backup e restart, inclusive o de uma unit cujo `ExecStartPre` falha (migração quebrada). No fim, o `restore-test.sh` do `backup-verify.yaml` com o banco do imago e um Litestream falso. O imago não passa um ensaio próprio ao `test-vm.sh`: o roteiro do `reapply-deletions` é testado no pytest (`tests/test_reapply_deletions.py`).

Em push na `main` e no `workflow_dispatch`, o workflow também faz o deploy.

## Deploy

O job `deploy` só começa depois que as checagens (backend, frontend, consistência e scripts) passam: um teste quebrado para o workflow antes de qualquer passo na VM. Ele roda em push na `main` que muda o que vai para a VM (`apps/imago/backend/`, `apps/imago/frontend/`, `packages/`, com os scripts do deploy, ou o próprio workflow). Um push que só muda arquivos lidos pelas checagens (os de `infra/` e `.github/scripts/` da lista acima), `apps/imago/dev/` ou este README roda as checagens sem deploy. Um push que só muda outra aplicação (o ethos, por exemplo) nem dispara o workflow. Em PRs, nunca há deploy.

Os passos, os detalhes (bytecode, backup, front sem `--delete`, ordem entre back e front) e o rollback são os do ethos ([apps/ethos/README.md](../ethos/README.md#deploy)), com os scripts de [packages/deploy/](../../packages/deploy/README.md) e o nome `imago`. Aqui fica o que é do imago.

### Antes do primeiro deploy

- **Variável `IMAGO_URL`** no GitHub: Settings → Secrets and variables → Actions → Variables → New repository variable, com o endereço do site, só `https://<domínio>`, sem caminho e sem barra no fim (hoje, `https://manasomali.com`, o mesmo do `ETHOS_URL`). O health check chama `$IMAGO_URL/api/imago/health`. Nenhum domínio fica fixo no workflow: trocar de domínio é trocar a variável. Sem ela, o workflow falha logo no começo (job "Preparar o deploy"), sem tocar na VM.
- **Secrets**: os mesmos do site, do Infra e do ethos, já cadastrados no repositório: `REMOTE_HOST`, `REMOTE_USER`, `SERVER_SSH_KEY` e `SSH_KNOWN_HOSTS`. O job usa o environment `production`.
- **Infra provisionado**: o workflow Infra precisa ter rodado com `infra/apps/imago/` e a linha `imago` do `databases.txt` (unit `app-imago`, parada até o primeiro deploy pelo `ConditionPathExists` da `.venv`, pastas, banco, uv, Python e os tokens da API interna em `/etc/infra/internal/imago.env`). O primeiro passo do deploy confere a unit, as pastas, o Python e o banco e, se faltar algo, falha pedindo para rodar o Infra.

### Os passos

| # | Passo | Onde |
|---|---|---|
| 1 | Checagens (needs) | runner |
| 2 | `vm.sh check`: unit `app-imago.service`, `/opt/apps/imago` e `/var/www/imago` graváveis, uv, o Python de `.python-version`, `sqlite3`, banco e pasta de backup | VM |
| 3 | rsync de `backend/` para `/opt/apps/imago/` com `--delete`, pelas regras de `packages/deploy/backend.rsync-filter` (antes, o `keep-migrations.sh` do rollback) | runner → VM |
| 4 | `vm.sh install`: `uv sync --frozen --no-dev --no-build --compile-bytecode` com o Python de `/opt/uv/python`, e `compileall` de `app/` e `migrations/` | VM |
| 5 | `vm.sh backup <sha>`: `sqlite3 .backup` como `app-imago` em `/var/backups/sqlite/imago/pre-deploy-<sha>.db` | VM |
| 6 | `vm.sh restart`: `systemctl restart app-imago`; o `ExecStartPre` roda `alembic upgrade head` | VM |
| 7 | Health check: `$IMAGO_URL/api/imago/health`, 10 tentativas, 3 s entre elas | runner |
| 8 | rsync do `dist/` (o mesmo build que passou nos testes) para `/var/www/imago/`, **sem** `--delete`, com o `index.html` por último | runner → VM |
| 9 | `clean-assets.sh`: apaga de `/var/www/imago/assets/` os arquivos com mais de 7 dias que não estão no build atual | VM |

- Os passos na VM vão pelo SSH como `bash -s -- imago <comando> < packages/deploy/vm.sh`, com o nome literal no workflow: nada fica instalado lá.
- **Todo deploy derruba a API das aplicações por alguns segundos** (depois que elas usam o imago): enquanto o `app-imago` reinicia (passo 6), o `auth_request` de `/api/<app>/` falha e a API de todas as aplicações responde 500 (menos o `/health` delas). É um risco aceito no [imago-plan.md](../../imago-plan.md) ("riscos aceitos").
- **Migração quebrada**: o `app-imago` não sobe, o job para no passo 6 e o front anterior continua no ar, como no ethos. Aqui o efeito é maior: até a correção ou o rollback, ninguém entra e a API de todas as aplicações responde 500. O log do Actions não mostra o journal (o repositório é público): na VM, `journalctl -u app-imago -n 50 --no-pager`.
- **Concorrência**: o job usa o grupo `imago-deploy`, nunca dois deploys do imago ao mesmo tempo, e os runs da `main` andam um de cada vez e na ordem (grupo `imago-checks-refs/heads/main`). Nem o grupo `infra` nem o `ethos-deploy`: um push que muda `packages/` publica o imago e o ethos em paralelo, e o deploy do ethos não depende do imago (o health check dele fica fora do `auth_request`).

### Rollback

Actions → Imago → Run workflow, a partir da `main`, com o SHA completo do commit a publicar (o anterior ao problema). Funciona como o do ethos ([Rollback](../ethos/README.md#rollback)): só commits da `main`, as checagens desse commit (os módulos de `FULL_COVERAGE` que ainda não existiam nele são pulados), os 9 passos com o código e o build dele e os scripts da `main`. As migrações não voltam: o `keep-migrations.sh` leva da `main` as que o banco já tem. O commit precisa ter o imago: um anterior a `apps/imago/` falha nas checagens, sem tocar na VM.

- **Dados estragados por uma migração**: o rollback do código e depois o restore do `pre-deploy-<sha>.db` do deploy que a aplicou, na ordem da seção do ethos no [infra/RESTORE.md](../../infra/RESTORE.md#restaurar-o-banco-de-uma-app-ethos) (o rollback roda duas vezes, e o `alembic upgrade head` manual fica de fora), com as trocas do imago: unit `app-imago`, porta 3003, `imago_cli`, `imago-cleanup.timer` no lugar do `ethos-alerts.timer` e o `reapply-deletions` do imago, que lê as linhas `app.deletion: conta <id> excluída` ([Depois de restaurar um backup](#depois-de-restaurar-um-backup)): o backup traz de volta as contas apagadas depois dele. Enquanto o `app-imago` está parado, a API de todas as aplicações responde 500.
- Um push novo na `main` depois do rollback publica a `main` de novo.

### Regras do deploy

- **Migrações só aditivas**: criar tabela ou coluna (anulável ou com default); remover ou renomear só num deploy seguinte, quando nenhum código no ar (nem o de um rollback) usa mais aquilo. **Nunca apague nem renomeie um arquivo de migração já publicado**: o rollback busca na `main` as migrações que o banco já tem. As mesmas regras do ethos ([Regras](../ethos/README.md#regras)).
- **Mudança de infra entra num PR anterior ao do imago**: unit, variável nova no `app.env`, porta, versão do Python. O Infra e o imago rodam em paralelo, sem ordem garantida entre eles; o deploy confere a unit, as pastas e o Python e falha com mensagem clara se o provision ainda não rodou.
- **O imago entra no ar antes de qualquer aplicação**: o `auth_request` de `/api/<app>/` pergunta a ele quem é o usuário, e as aplicações mandam email e buscam contas pela API interna dele. Uma aplicação só passa a usá-lo (o `auth_request` e o `IMAGO_INTERNAL_URL`, num PR de infra) depois do primeiro deploy do imago, com o `/api/imago/health` respondendo 200.
- **Contrato da API interna ou dos headers `X-User-*`: primeiro as aplicações, depois o imago.** Uma mudança no que o imago manda (os headers do `/internal/session`, as tarefas `delete` e `refresh`, as respostas de `/internal/*`) entra antes nas aplicações, que passam a aceitar os dois formatos, e só depois no imago; o formato antigo sai das aplicações num PR seguinte. O imago e as aplicações têm deploys separados, sem ordem garantida entre eles: com as aplicações aceitando os dois formatos, nenhuma ordem de deploy (nem um rollback do imago) deixa uma delas sem entender o imago. Na direção contrária (um campo que o imago passa a exigir das aplicações), o imago aceita os dois formatos primeiro, as aplicações mudam, e só então ele deixa de aceitar o antigo.
- **Nenhuma conta no imago antes da ETH-64**: as contas e o admin vêm do ethos pelo `import-users`, com os mesmos ids. Confirmar um código no `/imago/entrar` cria a conta, e o `import-users` recusaria o mesmo email (o passo 3 da [passagem do login](#passagem-do-login-do-ethos-eth-64-passo-3) diz como apagar uma conta criada por engano). Até lá, abra a tela de entrar, mas não confirme nenhum código.

### Primeiro deploy em produção (ETH-63)

O passo 2 da ordem do [imago-plan.md](../../imago-plan.md) ("migração do login do ethos"): depois do PR de infra do imago e antes do PR de infra que liga o `auth_request` do ethos. O imago fica no ar sem link em lugar nenhum e sem contas. Os comandos na VM rodam a partir de uma máquina com acesso a ela (`<REMOTE_USER>@<REMOTE_HOST>`, os mesmos dos secrets do deploy).

1. Cadastre a variável `IMAGO_URL` ([Antes do primeiro deploy](#antes-do-primeiro-deploy)) e confira que o Infra rodou com o imago: na VM, `systemctl cat app-imago` mostra a unit.
2. Faça o merge do PR. Em Actions → Imago, as checagens passam e o job Deploy faz os 9 passos.
3. Confira, de qualquer máquina:

   ```bash
   IMAGO_URL=https://manasomali.com
   curl -fsS "$IMAGO_URL/api/imago/health"; echo                             # {"status":"ok"}
   curl -s -o /dev/null -w '%{http_code}\n' "$IMAGO_URL/api/imago/me"       # 401 (sem cookie)
   ```

   E na VM:

   ```bash
   sudo journalctl -u app-imago -n 50 --no-pager      # subida sem erro, com a migração: "Running upgrade  -> 0001"
   ls /opt/apps/imago/app/__pycache__ | head -n 3      # bytecode gerado no deploy
   sudo ls /var/backups/sqlite/imago/                  # pre-deploy-<sha>.db do deploy
   sudo -u app-imago sqlite3 /var/lib/sqlite/imago/app.db 'SELECT count(*) FROM users;'   # 0
   ```

4. No navegador, `$IMAGO_URL/imago/entrar` carrega a tela de entrar. Não confirme nenhum código (ver as regras acima).
5. Ensaio de rollback, depois de um segundo deploy (qualquer push que mude o imago): Actions → Imago → Run workflow, a partir da `main`, com o SHA do primeiro deploy. O job passa, o resumo mostra esse SHA e o health responde 200; o backup desse deploy ganha a hora no nome (`pre-deploy-<sha>-<AAAAMMDDTHHMMSSZ>.db`), porque o primeiro deploy do mesmo commit já deixou um (a pasta guarda 7 dias). Depois, Run workflow com o SHA atual da `main` (ou o próximo push) volta para ela.

A migração quebrada (o serviço não sobe, o front anterior fica e o job falha) é testada pelo `test-vm.sh` no CI. Se quiser ensaiá-la em produção, o momento é antes do PR de infra que liga o `auth_request` do ethos: até lá, o `app-imago` fora do ar não derruba nenhuma aplicação.
