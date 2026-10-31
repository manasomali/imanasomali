# conta

## estrutura
- login único de todas as aplicações do `manasomali.com` (hoje o ethos e o engrafi)
- acessada por `manasomali.com/conta/` (api em `manasomali.com/api/conta/`)
- segue a convenção de aplicação do monorepo (`apps/README.md`): código em `apps/conta/`, config da VM em `infra/apps/conta/`, banco `conta` em `infra/databases.txt`, workflow `.github/workflows/conta.yaml`
- porta do backend: 3003, registrada na tabela do `infra/README.md`
- precisa estar no ar antes de qualquer aplicação: o nginx delas pergunta à conta quem é o usuário
- não importa código das aplicações, e elas não importam o dela. falam só por HTTP local (ver "API interna")

## proposta
uma conta, um login, uma tela de conta, um par de termos de uso e de política de privacidade e um teto de envio de email para todas as aplicações. cada aplicação guarda só os dados dela.

### o que fica onde
- na conta: email, fuso, idioma, `is_active`, `is_admin`, aceite dos termos, sessões de login, códigos, eventos de auth e o envio de todos os emails
- em cada aplicação: os dados dela, ligados ao id do usuário na conta, e uma cópia de email, fuso e idioma em `app_users` (para mostrar e para jobs que rodam sem request, como os alertas do ethos)
- as aplicações não leem o banco da conta, e a conta não lê o banco delas

## login

### fluxo (sem senha, código por email)
- cadastro e login são a mesma tela: o usuário digita o email, recebe um código de 6 dígitos e digita o código
- se o email ainda não tem conta, o usuário é criado no momento em que o código é confirmado. assim o cadastro já nasce com o email confirmado e não ficam contas pendentes no banco. a conta é criada com a versão atual dos termos aceita
- só código, sem link mágico: funciona entre aparelhos (abre o email no celular, digita no computador) e não sofre com antivírus de email que abrem links e queimam tokens de uso único
- telas em `manasomali.com/conta/`: entrar (email, código e aceite dos termos), conta, termos, privacidade e admin
- `/conta/entrar?next=<caminho>`: depois do login volta para o `next`. só aceita caminho relativo que começa com uma `/` (não `//` nem `/\`), senão vai para `/conta/`. evita redirecionamento para outro site
- quando a API de uma aplicação responde 401, o front dela manda para `/conta/entrar?next=<caminho atual>`
- termos pendentes (versão nova) contam como sem login: a pessoa passa pela tela de entrar, aceita e volta
- o tema (`localStorage.theme`) e o idioma (`localStorage.i18nextLng`) continuam compartilhados entre site, conta e aplicações. o idioma escolhido também vai para `users.locale` (`PATCH /api/conta/me`), usado nos emails
- o fuso (`users.timezone`, IANA) nasce com o do navegador no primeiro login e depois só muda na tela de conta. as aplicações sugerem a troca quando o fuso do navegador fica diferente do salvo, com um link para a tela de conta

### regras de segurança
- código: `secrets.randbelow(10**6)` com zeros à esquerda (sempre 6 dígitos). no banco fica só o sha256, comparado com `hmac.compare_digest`. o hash de 6 dígitos não segura quem já leu o banco, mas o código dura 10 min e quem leu o banco já tem os dados
- cada código vale 10 min e uma vez só. pedir um código novo invalida os anteriores do mesmo email e propósito
- no máximo 5 tentativas por código, depois disso ele morre e é preciso pedir outro. o `attempts` é incrementado antes de comparar, na mesma transação `BEGIN IMMEDIATE`, para requests em paralelo não passarem do limite
- verificação inteira numa transação só: incrementa `attempts`, compara, marca `used_at`, cria o usuário (se precisar) e cria a sessão. o `email` único em `users` resolve dois verify simultâneos do mesmo primeiro acesso
- limite de envio por email: 1 código por minuto e 5 por hora, contados pelas linhas de `login_codes` (sem tabela extra). responde 429 igual para qualquer email, então não revela quem tem conta
- teto global de envio: ver "envio de email e limite compartilhado"
- captcha no `POST /auth/code/request` só se começar a ter abuso
- rate limit por IP: `limit_req` no nginx para `/api/conta/auth/` (10 por minuto, `burst=5`, `nodelay`, resposta 429)
- limpeza: apagar `login_codes` e `sessions` vencidos ao criar um código novo e no `cleanup` de hora em hora
- texto do email: no idioma do usuário (`users.locale`, ou o `Accept-Language` no primeiro acesso), com "nunca compartilhe este código" e "se não foi você, ignore este email". nunca o código no assunto, que aparece em notificações de tela bloqueada
- token de sessão: `secrets.token_urlsafe(32)`. no banco fica só o sha256, então um vazamento do banco não dá acesso às sessões. sessão expira em 60 dias e renova com o uso. `last_seen_at` e `expires_at` atualizam no máximo uma vez por dia, para não escrever no banco a cada request
- cookie `__Host-conta_session`: `HttpOnly; Secure; SameSite=Lax; Path=/`, sem `Domain`. como site, conta e aplicações estão na mesma origem, ele vale para todas
- csrf: além do `SameSite=Lax`, a conta e cada aplicação recusam POST/PUT/PATCH/DELETE cujo header `Origin` não seja `APP_ORIGIN` (esquema + host, ex.: `https://manasomali.com`)
- nunca logar código, token, cookie nem os headers `X-User-*`
- admin: só pelo `is_admin`. o primeiro admin é marcado por um comando de linha (`python -m app.cli create-admin <email>`), nunca por endpoint
- admin entra só com o código por email, sem segundo fator. proteger a conta de email do admin no provedor (passkey ou chave física)

### troca de email (só pelo suporte)
- o usuário não troca o email sozinho. a tela de conta mostra o `SUPPORT_EMAIL` e explica como pedir
- o pedido tem que vir do email atual da conta. se a pessoa perdeu acesso a ele, a decisão é manual e é o caminho mais usado para roubar conta, então pedir provas (ex.: dados que só o dono saberia nas aplicações) antes de trocar
- antes de trocar, o admin confirma o email novo pedindo uma resposta a partir dele. isso evita erro de digitação que entregaria a conta para um estranho
- `PATCH /api/conta/admin/users/{id}/email` (só admin): recebe `{new_email}`, responde 409 se o email já tiver conta, apaga todas as sessões do usuário, grava no `audit_log` o email antigo, o novo e qual admin fez a troca, e cria tarefas `refresh` para as aplicações atualizarem `app_users`
- depois da troca, manda um aviso para o email antigo e para o novo

## como as aplicações sabem quem é o usuário
- o nginx pergunta à conta em cada request de `/api/<app>/`, com `auth_request`, e repassa o resultado em headers
- a conta responde ao `auth_request` sempre com 200: com os headers `X-User-Id`, `X-User-Email`, `X-User-Locale`, `X-User-Timezone` e `X-User-Admin` quando o cookie é válido (sessão viva, conta ativa, termos aceitos), sem eles quando não é. assim rotas públicas das aplicações (ex.: banner ativo) continuam funcionando. cada aplicação decide quais rotas exigem login (401 sem `X-User-Id`)
- o nginx sempre define esses headers a partir da resposta da conta (`auth_request_set` + `proxy_set_header`), o que apaga qualquer `X-User-*` mandado pelo navegador. isso só é seguro porque os backends escutam em `127.0.0.1` e só o nginx chega neles
- `GET /api/<app>/health` não passa pelo `auth_request`, para o monitor de cada aplicação não depender da conta
- a cada request com login, a aplicação cria ou atualiza a linha dela em `app_users`. só grava quando algo mudou
- `is_admin` chega às aplicações pelo `X-User-Admin`. cada aplicação confere esse header no `require_admin`

```nginx
# infra/apps/conta/nginx.conf (dentro do server, junto com /conta/ e /api/conta/)
location = /_conta/session {
        internal;
        proxy_pass http://127.0.0.1:__PORTA__/internal/session;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Real-IP $remote_addr;
}
location /api/conta/internal/ { return 404; }

# infra/apps/<app>/nginx.conf
location /api/<app>/ {
        auth_request /_conta/session;
        auth_request_set $conta_user_id $upstream_http_x_user_id;
        # ... idem para email, locale, timezone e admin
        proxy_set_header X-User-Id $conta_user_id;
        proxy_pass http://127.0.0.1:__PORTA__/;
}
location = /api/<app>/health { proxy_pass http://127.0.0.1:__PORTA__/health; }
location /api/<app>/internal/ { return 404; }
```

### desenvolvimento local
- um nginx em container (`nginx:1.24`, o mesmo do CI do infra) com os mesmos snippets faz o papel do de produção, na frente da conta e das aplicações rodando na máquina. a config fica em `apps/conta/dev/`
- não existe atalho de login no backend, nem em dev: o E2E também passa pelo código de login, lido no SMTP falso

## API interna
- só entre os serviços, direto em `127.0.0.1:<porta>`, nunca pelo nginx. o nginx responde 404 para `/api/<app>/internal/` na conta e em todas as aplicações
- autenticada por `Authorization: Bearer <INTERNAL_API_TOKEN>`, comparado com `hmac.compare_digest`. o token é gerado pelo provision na própria VM, uma vez (só se ainda não existir, para continuar idempotente), em `/etc/infra/internal.env` (`0600`, root), lido pelas units com `EnvironmentFile=`. não passa pelo GitHub nem sai da VM
- exceção: `GET /internal/session`, chamado pelo nginx, não usa token. ele só lê o cookie que veio no request e devolve o que o próprio dono do cookie já vê em `/me`
- a conta expõe:
  - `GET /internal/session` (para o `auth_request`)
  - `POST /internal/mail` (envio de email, ver abaixo)
  - `POST /internal/users/lookup` com `{email}` (para convites: id e idioma, ou 404). o email vai no corpo, nunca na URL, para não parar em log
  - `GET /internal/users/{id}` (email, idioma, fuso, ativo)
- cada aplicação expõe:
  - `POST /internal/users/{id}/delete`: apaga os dados daquela pessoa, com as regras do plano da aplicação. idempotente: id que a aplicação não conhece também é 200
  - `POST /internal/users/{id}/refresh`: recebe email, idioma e fuso novos e atualiza `app_users`
- a conta sabe quais aplicações existem por `CONTA_APPS` no `app.env` dela (ex.: `ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002`). o CI confere se cada aplicação de `infra/apps/` (menos a conta) está lá, com a porta igual ao `PORT` do `app.conf` dela
- as aplicações acham a conta por `CONTA_INTERNAL_URL` (`http://127.0.0.1:3003`)

## envio de email e limite compartilhado
- só a conta fala com o SMTP: só a unit dela lê `/etc/infra/smtp.env`. as aplicações mandam email por `POST /internal/mail`, com o tipo, o id do destinatário, o assunto e o corpo (texto e HTML) já no idioma dele. a conta põe o endereço atual da pessoa
- só para usuários da conta, por id, nunca para um endereço qualquer: um bug numa aplicação não vira envio para fora. conta inativa não recebe
- remetente: `MAIL_FROM_ADDRESS` (`no-reply@manasomali.com`), com o nome da aplicação que pediu (ex.: "ethos <no-reply@manasomali.com>"). os emails da própria conta saem como "manasomali.com"
- **um teto só para todas as aplicações**, contado numa janela móvel de 24 h (assim nunca passa da cota diária da Brevo, seja qual for a hora em que ela zera):
  - `MAX_EMAILS_PER_DAY=280`: os 300 da Brevo menos uma margem para o aviso de teto ao `SUPPORT_EMAIL` (no máximo um por hora, fora da contagem)
  - `MAX_EMAILS_PER_HOUR=60`: segura rajadas
  - `MAIL_RESERVED_FOR_CODES=60`: os últimos 60 envios das 24 h ficam só para códigos e emails de conta. notificações param quando a janela chega a 220
- tipos: `code` (login, exclusão de conta), `account` (conta excluída, troca de email) e `notification` (convites, alertas e avisos das aplicações)
- ao bater o teto:
  - código: 429 ("tente mais tarde") e aviso ao `SUPPORT_EMAIL` (no máximo um por hora). protege a cota e a reputação do domínio contra quem pede código para milhares de endereços trocando de IP
  - notificação: a conta responde 429 e a aplicação grava só uma linha de aviso no log, sem endereço. o que gerou o email continua visível no app (ex.: o convite pendente aparece para o convidado). cada aplicação decide se tenta de novo depois (os alertas do ethos tentam na hora seguinte)
- a contagem fica na tabela `mail_log` (aplicação, tipo e instante, sem destinatário), gravada na mesma transação `BEGIN IMMEDIATE` que confere o teto, antes de chamar o SMTP. se o SMTP falhar, a linha fica: conta a mais, nunca a menos
- envio em `BackgroundTasks`, depois do commit
- emails da própria conta (templates em pt e en): código de login, código de exclusão de conta, conta excluída, troca de email (para o antigo e para o novo), teto de envio atingido (para o `SUPPORT_EMAIL`)
- os emails de cada aplicação (convite, alerta, avisos) ficam no plano dela

## exclusão de conta
- pedida na tela de conta (`POST /me/delete/request` manda um código para o email atual, `DELETE /me` com `{code}` apaga) ou pelo admin (`DELETE /admin/users/{id}`, mesma função de serviço). apaga a pessoa de todas as aplicações
- a tela avisa antes o que vai sumir e mostra o link de export de cada aplicação, para a pessoa levar os dados
- passos:
  1. numa transação `BEGIN IMMEDIATE` da conta: status `deleting`, apaga sessões e códigos, cria uma tarefa `delete` para cada aplicação de `CONTA_APPS` e grava no journald só o id numérico da conta. a pessoa já não entra
  2. a conta chama `POST /internal/users/{id}/delete` em cada aplicação. cada uma apaga na própria transação, com as regras dela, e manda os avisos dela (ex.: "você perdeu acesso a um hábito") depois do commit
  3. com todas as tarefas feitas, a conta apaga a linha em `users`, apaga os eventos de auth da pessoa no `audit_log`, grava um evento `account_deleted` com o id numérico e quem apagou (a própria pessoa ou qual admin), sem email, e manda "conta excluída" ao email lido no passo 1
- tarefa que falha fica para o `conta-cleanup.timer` (de hora em hora). depois de 5 falhas seguidas, grava uma linha de erro no journald a cada tentativa
- enquanto a exclusão não termina, o email não pode criar conta nova ("tente mais tarde")
- a conta do último `is_admin` não pode ser apagada, nem pelo admin nem pelo `DELETE /me`
- para só bloquear sem apagar, o admin usa `is_active=false`: a pessoa não recebe código nem entra, e os dados ficam
- exclusão imediata, sem período de arrependimento. o código de confirmação já é a proteção contra clique por engano
- `PRAGMA secure_delete=ON` em todos os bancos, para o sqlite sobrescrever com zeros as páginas apagadas

### backups
- os dados apagados continuam nos backups até eles vencerem: snapshots locais guardam 7 dias (`infra/scripts/snapshot.sh`) e o litestream guarda 168h no object storage (`infra/lib/backups.sh`). ou seja, em até uns 8 dias o dado some de todo lugar
- se for preciso restaurar um backup (da conta ou de qualquer aplicação), as contas apagadas depois daquele ponto voltam. por isso, depois de um restore, rodar `python -m app.cli reapply-deletions` na conta antes de abrir os apps de novo: ele lê os ids do journald e refaz as exclusões na conta e em todas as aplicações
- a política de privacidade explica o que é apagado, o que fica sem identificação e o prazo de até 8 dias nos backups

## admin
- painel em `/conta/admin`, só para `is_admin`
- contas: listagem com email, datas (cadastro, último login) e status, busca por email, bloquear (`is_active=false`, apaga as sessões), trocar email e excluir
- envios de email: quantos cada aplicação mandou nas últimas 24 h, por tipo, e quanto falta para o teto
- toda ação do admin grava no `audit_log`
- o painel de cada aplicação cuida só do conteúdo dela (e de quem usa aquela aplicação)

## tela de conta
- email (só leitura) e como pedir a troca ao `SUPPORT_EMAIL`
- idioma e fuso (lista de fusos IANA com busca)
- sair e sair de todos os aparelhos (`POST /auth/logout-all`, que substitui o "trocar senha" para expulsar um aparelho perdido)
- exclusão de conta em passos: aviso do que some em cada aplicação → links de export → código → confirmação final
- lista das aplicações, com link para cada uma

## termos de uso e política de privacidade
- um par só para todas as aplicações: `/conta/termos` e `/conta/privacidade`, em pt e en, com link no rodapé da conta e das aplicações e na tela de entrar ("ao continuar, você concorda com os termos de uso e a política de privacidade")
- cada versão tem um identificador, igual no front e no back da conta (o CI confere). `users.terms_version` guarda a versão aceita. qualquer mudança (inclusive a entrada de uma aplicação nova) pede o aceite de novo no próximo acesso
- termos de uso devem cobrir: serviço gratuito sem garantia de disponibilidade, planos pagos e anúncios no futuro, uso aceitável (sem abuso de convites e envio de códigos), bloqueio e exclusão de conta por abuso, limites de uso, a conta vale para todas as aplicações, troca de email só pelo suporte, contato (`SUPPORT_EMAIL`), e uma seção por aplicação com as regras dela
- política de privacidade deve cobrir: dados da conta (email, fuso, idioma, IP e navegador nas sessões e na auditoria de login), os dados de cada aplicação (numa seção por aplicação), para que são usados, onde ficam (VM e Object Storage da Oracle, provedor de email), quem vê (membros do que for compartilhado em cada aplicação e o administrador do serviço, que tem acesso ao conteúdo das aplicações), prazos (sessão 60 dias, código 10 min, auditoria de auth e IPs 90 dias), exclusão (imediata em todas as aplicações, até 8 dias nos backups), quais emails o serviço manda (só de conta, segurança, convite, alerta e avisos das aplicações; nada de marketing), único cookie é o de sessão, sem rastreamento e sem venda de dados, contato
- o texto de cada seção de aplicação vem do plano dela

## retenção de dados
- sessões: 60 dias, renovadas com o uso
- códigos: 10 min
- eventos de auth no `audit_log` (login, logout etc.): 90 dias
- IP nas linhas do `audit_log` e de `sessions`: apagado (vira `NULL`) depois de 90 dias
- `mail_log`: 48 h
- tarefas `app_tasks` concluídas: 7 dias
- a limpeza roda no `conta-cleanup.timer` (`python -m app.cli cleanup`)

## config (variáveis de ambiente)
- `DATABASE_PATH`, `APP_ORIGIN` (`https://manasomali.com`), `SUPPORT_EMAIL`, `MAIL_FROM_ADDRESS`, `CONTA_APPS`, `TERMS_VERSION`
- `MAX_EMAILS_PER_DAY=280`, `MAX_EMAILS_PER_HOUR=60`, `MAIL_RESERVED_FOR_CODES=60`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (de `/etc/infra/smtp.env`) e `INTERNAL_API_TOKEN` (de `/etc/infra/internal.env`)

### tamanhos e formatos
- email: até 254 caracteres, salvo com strip + lower
- paginação de listas (admin): 50 itens por página por padrão, máximo 200

## stack
igual à do ethos (seção "stack" do `ethos-plan.md`): react + vite, python + fastapi, sqlalchemy 2 síncrono + alembic, `uv`, os mesmos PRAGMAs e `BEGIN IMMEDIATE`, `uvicorn --workers 1`, `MemoryMax=150M`, erros no formato `{"error", "field"}` com catálogo próprio, logs sem IP, email, código, token nem cookie.
- frontend em `/var/www/conta/` (vite `base: '/conta/'`, react router `basename="/conta"`), com os tokens de `packages/tokens`
- backend como `app-conta` em `/opt/apps/conta/`, porta 3003
- a unit lê `/etc/infra/smtp.env`, `/etc/infra/internal.env` e `/etc/infra/apps/conta.env`
- agendador: `conta-cleanup.timer` (de hora em hora) roda `python -m app.cli run-tasks` (tarefas pendentes para as aplicações) e `python -m app.cli cleanup`
- CLI: `create-admin`, `run-tasks`, `cleanup`, `reapply-deletions`, `seed`
- nginx (`infra/apps/conta/nginx.conf` e `nginx-http.conf`): `/conta/` com os mesmos headers e cache do frontend do ethos, `/api/conta/` com proxy, `/api/conta/auth/` com `limit_req` (zona `conta_auth`), `/_conta/session` interno e 404 em `/api/conta/internal/`
- deploy (`.github/workflows/conta.yaml`): os mesmos 9 passos do ethos, com `concurrency: conta-deploy` e a variável `CONTA_URL`
- monitoramento: o monitor externo chama `/api/conta/health`, além do health de cada aplicação
- o login depende 100% do email chegar: SPF, DKIM e DMARC no domínio (feitos na ETH-01) e a cota do provedor (Brevo, 300 por dia), que define os tetos acima

### estrutura no monorepo
```
.github/workflows/conta.yaml
infra/apps/conta/
  app.conf               # PORT=3003, PYTHON_VERSION
  app.env                # APP_ORIGIN, SUPPORT_EMAIL, MAIL_FROM_ADDRESS, CONTA_APPS, tetos de email
  app-conta.service
  conta-cleanup.service
  conta-cleanup.timer
  nginx.conf             # /conta/, /api/conta/ e /_conta/session (dentro do server)
  nginx-http.conf        # limit_req_zone conta_auth (contexto http)
apps/conta/
  README.md
  dev/                   # nginx em container para desenvolvimento e E2E
  backend/
    .python-version
    pyproject.toml
    uv.lock
    alembic.ini
    alembic/versions/
    app/
      main.py            # FastAPI(root_path="/api/conta"), routers, GET /health
      config.py
      db.py
      models.py
      audit.py
      errors.py
      cli.py             # create-admin, run-tasks, cleanup, reapply-deletions, seed
      auth/
        router.py        # /auth/*, /me
        service.py       # pedir e verificar código, sessão
        security.py      # códigos, tokens, hashes
        deps.py          # current_user, require_admin, checagem de Origin
      mail/
        quota.py         # teto compartilhado e reserva para códigos
        sender.py        # SMTP
        templates/       # emails da conta, em pt e en
      internal/
        router.py        # /internal/session, /mail, /users/*
        tasks.py         # tarefas delete e refresh para as aplicações
      deletion.py        # exclusão de conta, usada pelo usuário e pelo admin
      admin/
        router.py
    tests/
  frontend/
    package.json
    vite.config.js       # base: '/conta/', importa packages/tokens
    public/locales/{pt,en}/translation.json
    src/
    e2e/
```

### tabelas
- `users`: id, email (único, salvo com strip + lower), status (`active` | `deleting`), is_active, is_admin, timezone, locale, terms_version, terms_accepted_at, created_at, updated_at, last_login_at
- `sessions`: token_hash (sha256 do token, chave primária), user_id, created_at, expires_at, last_seen_at, ip, user_agent
- `login_codes`: id, email (destino do código), user_id (vazio no login, preenchido nas ações de conta), purpose (`login` | `delete_account`), code_hash, attempts, expires_at, used_at, created_at
- `audit_log`: id, user_id, event, ip, created_at, details (json). eventos de auth e ações do admin sobre contas
- `mail_log`: id, app, kind (`code` | `account` | `notification`), created_at. sem destinatário
- `app_tasks`: id, user_id, app, action (`delete` | `refresh`), attempts, last_attempt_at, done_at, created_at
- chaves estrangeiras: `ON DELETE CASCADE` de `users` para `sessions`, `login_codes` e `app_tasks`, e `ON DELETE SET NULL` em `audit_log.user_id`

### endpoints (`/api/conta/...`)
- `POST /auth/code/request`: recebe `{email}`. sempre responde 202 com o mesmo corpo, exista a conta ou não. conta inativa não recebe email
- `POST /auth/code/verify`: recebe `{email, code, timezone, locale}`. cria o usuário se for o primeiro acesso (com o fuso e o idioma do navegador), cria uma sessão nova e seta o cookie. para quem já tem conta, `timezone` e `locale` são ignorados
- `POST /auth/logout`: apaga a sessão atual
- `POST /auth/logout-all`: apaga todas as sessões do usuário
- `GET /me`: usuário logado, incluindo se precisa aceitar uma versão nova dos termos
- `PATCH /me`: muda `timezone` e `locale` e cria tarefas `refresh` para as aplicações
- `POST /me/terms`: aceita a versão atual dos termos
- `POST /me/delete/request` e `DELETE /me`: exclusão de conta
- admin: `GET /admin/users`, `PATCH /admin/users/{id}` (`is_active`), `PATCH /admin/users/{id}/email`, `DELETE /admin/users/{id}`, `GET /admin/mail`
- API interna: ver "API interna"
- `GET /health`: responde 200 se o banco responde a `SELECT 1`

## quem usa
- ethos (porta 3001): `ethos-plan.md`
- engrafi (porta 3002): `engrafi-plan.md`
- cada plano diz o que a aplicação apaga no `POST /internal/users/{id}/delete`, quais emails ela manda e o texto da seção dela nos termos e na privacidade

## planejamento a longo prazo
- captcha no `POST /auth/code/request`, só se houver abuso
- segundo fator para o admin

## riscos aceitos
- código no chute: com 5 tentativas por código e 5 códigos por hora, quem insistir contra uma conta o ano inteiro tem cerca de 20% de chance de acertar (a vítima recebe dezenas de emails por dia enquanto isso). vale também para a conta do admin
- admin sem segundo fator: quem invadir o email do admin ou acertar o código dele vira admin de todos os usuários, e passa a ver o conteúdo de todas as aplicações
- a conta é ponto único de falha: se ela cair, o `auth_request` falha e a API de todas as aplicações responde 500 (menos o `/health` delas)
- exclusão de conta não é atômica entre os bancos: se uma aplicação falhar, os dados dela ficam até o timer conseguir. a pessoa já não entra durante esse tempo
- emails enviados por `BackgroundTasks` se perdem se o serviço reiniciar antes de enviar
- reaplicar exclusões depois de um restore depende do journald, que tem limite de 100M e some junto se a VM for perdida
- teto de email compartilhado: uma aplicação com muitas notificações pode gastar a parte das outras. a reserva para códigos garante que o login continua funcionando
- memória: a conta é mais um processo python na VM de 1 GB (com `MemoryMax=150M`). medir depois do go-live
- cota do Object Storage: o banco `conta` é mais um no Litestream. escreve pouco (logins e uma renovação de sessão por dia), mas medir depois do go-live junto com os outros
- LGPD ignorada por enquanto
