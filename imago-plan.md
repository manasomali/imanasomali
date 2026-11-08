# imago

## nome do projeto
imago (do latim, "imagem, retrato"): a identidade da pessoa em todas as aplicações do site

## estrutura
- login único de todas as aplicações do `manasomali.com` (hoje o ethos e o engrafi)
- acessada por `manasomali.com/imago/` (api em `manasomali.com/api/imago/`)
- segue a convenção de aplicação do monorepo (`apps/README.md`): código em `apps/imago/`, config da VM em `infra/apps/imago/`, banco `imago` em `infra/databases.txt`, workflow `.github/workflows/imago.yaml`
- porta do backend: 3003, registrada na tabela do `infra/README.md`
- precisa estar no ar antes de qualquer aplicação: o nginx delas pergunta ao imago quem é o usuário. o ethos já está no ar com login próprio, e a passagem dele para o imago tem uma ordem certa (ver "migração do login do ethos")
- não importa código das aplicações, e elas não importam o dele. falam só por HTTP local (ver "API interna")
- o login, a sessão, os códigos, a exclusão de conta, o admin de contas e os emails de conta já existem no ethos (`apps/ethos/backend/app/auth/`, `app/mail/`, `app/admin/accounts.py`, descritos no `apps/ethos/README.md`). o imago começa movendo esse código e essas regras, com as mudanças deste plano

## proposta
uma conta, um login, uma tela de conta, um par de termos de uso e de política de privacidade e um teto de envio de email para todas as aplicações. cada aplicação guarda só os dados dela.

### o que fica onde
- no imago: email, fuso, idioma, `is_active`, `is_admin`, aceite dos termos, sessões de login, códigos, eventos de auth e o envio de todos os emails
- em cada aplicação: os dados dela, ligados ao id do usuário no imago, e em `app_users` uma cópia do que ela usa da conta (email e idioma; o ethos também o fuso), para mostrar e para jobs que rodam sem request, como os alertas do ethos
- as aplicações não leem o banco do imago, e o imago não lê o banco delas

### id da conta
- inteiro aleatório de 1 a 2^53 − 1 (cabe num `Number` do javascript), sorteado com `secrets` ao criar a conta, com outro sorteio se colidir
- nunca sequencial: depois de restaurar um backup do imago, um id sequencial voltaria a ser dado a uma conta nova, e se ele já estivesse nas aplicações (conta criada depois do ponto restaurado) a pessoa nova veria os dados de outra
- as contas que vêm do ethos mantêm os ids de lá (ver "migração do login do ethos")

## login

### fluxo (sem senha, código por email)
- cadastro e login são a mesma tela: o usuário digita o email, recebe um código de 6 dígitos e digita o código
- se o email ainda não tem conta, o usuário é criado no momento em que o código é confirmado. assim o cadastro já nasce com o email confirmado e não ficam contas pendentes no banco. a conta é criada com a versão atual dos termos aceita
- só código, sem link mágico: funciona entre aparelhos (abre o email no celular, digita no computador) e não sofre com antivírus de email que abrem links e queimam tokens de uso único
- telas em `manasomali.com/imago/`: entrar (email, código e aceite dos termos), conta, termos, privacidade e admin
- `/imago/entrar?next=<caminho>`: depois do login volta para o `next`. só aceita caminho da mesma origem: o front monta `new URL(next, location.origin)`, exige a mesma origem e recusa `next` com caractere de controle ou `\` (o navegador tira tab e quebra de linha da URL, e `/\t/site.com` viraria `//site.com`), e também o caminho que, resolvido, começa com `//` (a resolução tira os segmentos de ponto: `/.//site.com` e `/%2e%2e//site.com` dão o pathname `//site.com`, que o navegador lê como outro host). `next` inválido, ou para a própria tela de entrar, vai para `/imago/`. evita redirecionamento para outro site
- quando a API de uma aplicação responde 401, o front dela manda para `/imago/entrar?next=<caminho atual>`
- termos pendentes (versão nova) contam como sem login para as aplicações: a pessoa cai na tela de entrar, que, com a sessão válida, mostra só o aceite e depois volta para o `next`. no imago, `GET /me`, `POST /me/terms`, a exclusão de conta e o logout funcionam sem o aceite
- o tema (`localStorage.theme`) e o idioma (`localStorage.i18nextLng`) continuam compartilhados entre site, imago e aplicações. o idioma escolhido também vai para `users.locale` (`PATCH /api/imago/me`), usado nos emails
- o fuso (`users.timezone`, IANA) nasce com o do navegador no primeiro login e depois só muda na tela de conta. as aplicações sugerem a troca quando o fuso do navegador fica diferente do salvo, com um link para a tela de conta

### regras de segurança
- código: `secrets.randbelow(10**6)` com zeros à esquerda (sempre 6 dígitos). no banco fica só o sha256, comparado com `hmac.compare_digest`. o hash de 6 dígitos não segura quem já leu o banco, mas o código dura 10 min e quem leu o banco já tem os dados
- cada código vale 10 min e uma vez só. pedir um código novo invalida os anteriores do mesmo email e propósito
- no máximo 5 tentativas por código, depois disso ele morre e é preciso pedir outro. o `attempts` é incrementado antes de comparar, na mesma transação `BEGIN IMMEDIATE`, para requests em paralelo não passarem do limite
- verificação inteira numa transação só: incrementa `attempts`, compara, marca `used_at`, cria o usuário (se precisar) e cria a sessão. o `email` único em `users` resolve dois verify simultâneos do mesmo primeiro acesso
- limite de envio por email: 1 código por minuto e 5 por hora, somando login e exclusão de conta, contados pelas linhas de `login_codes` (sem tabela extra). responde 429 igual para qualquer email, então não revela quem tem conta
- teto global de envio: ver "envio de email e limite compartilhado"
- captcha no `POST /auth/code/request` só se começar a ter abuso
- rate limit por IP: `limit_req` no nginx para `/api/imago/auth/` (10 por minuto, `burst=5`, `nodelay`, resposta 429)
- limpeza: sessões vencidas e linhas de `login_codes` criadas há mais de 1 dia saem ao criar um código novo e no `cleanup` de hora em hora. o código vence em 10 min, mas a linha fica: o limite por hora conta essas linhas, e apagá-las ao vencer deixaria passar 60 códigos por hora em vez de 5
- texto do email: no idioma do usuário (`users.locale`, ou o `Accept-Language` no primeiro acesso), com "nunca compartilhe este código" e "se não foi você, ignore este email". nunca o código no assunto, que aparece em notificações de tela bloqueada
- token de sessão: `secrets.token_urlsafe(32)`. no banco fica só o sha256, então um vazamento do banco não dá acesso às sessões. sessão expira em 60 dias sem uso e renova com o uso, inclusive no `/internal/session`, então usar qualquer aplicação mantém a sessão viva. `last_seen_at` e `expires_at` atualizam no máximo uma vez por dia, para não escrever no banco a cada request
- cookie `__Host-imago_session`: `HttpOnly; Secure; SameSite=Lax; Path=/`, sem `Domain`. como site, imago e aplicações estão na mesma origem, ele vale para todas
- o `Max-Age` do cookie é de 400 dias (o máximo que o Chrome aceita), e quem decide a validade é o `expires_at` do banco. a renovação feita no `auth_request` não chega ao navegador (o nginx não repassa um `Set-Cookie` do imago), então um cookie de 60 dias derrubaria, 60 dias depois do login, quem usa todo dia uma aplicação e nunca abre o `/imago/`
- csrf: além do `SameSite=Lax`, o imago e cada aplicação recusam com 403 toda request que não seja GET, HEAD ou OPTIONS sem exatamente um header `Origin` igual à origem do `APP_URL` (esquema + host, ex.: `https://manasomali.com`). sem `Origin` também é recusada. a exceção é `/internal/*`, que não vem do navegador e confere o token
- nunca logar código, token, cookie nem os headers `X-User-*`
- admin: só pelo `is_admin`. o primeiro admin é marcado por um comando de linha (`python -m app.cli create-admin <email>`), nunca por endpoint
- o admin não bloqueia a própria conta, e o último admin ativo não é bloqueado nem apagado. cada ação do admin confere de novo, dentro do `BEGIN IMMEDIATE`, que quem age continua admin ativo
- admin entra só com o código por email, sem segundo fator. proteger a conta de email do admin no provedor (passkey ou chave física)

### troca de email (só pelo suporte)
- o usuário não troca o email sozinho. a tela de conta mostra o `SUPPORT_EMAIL` e explica como pedir
- o pedido tem que vir do email atual da conta. se a pessoa perdeu acesso a ele, a decisão é manual e é o caminho mais usado para roubar conta, então pedir provas (ex.: dados que só o dono saberia nas aplicações) antes de trocar
- antes de trocar, o admin confirma o email novo pedindo uma resposta a partir dele. isso evita erro de digitação que entregaria a conta para um estranho
- `PATCH /api/imago/admin/users/{id}/email` (só admin): recebe `{new_email}`, responde 409 se o email já tiver conta, apaga todas as sessões do usuário, vence os códigos pendentes do email antigo, grava no `audit_log` o email antigo, o novo e qual admin fez a troca, e cria tarefas `refresh` para as aplicações atualizarem `app_users`
- depois da troca, manda um aviso para o email antigo e para o novo

## como as aplicações sabem quem é o usuário
- o nginx pergunta ao imago em cada request de `/api/<app>/`, com `auth_request`, e repassa o resultado em headers
- o imago responde ao `auth_request` sempre com 200: com os headers `X-User-Id`, `X-User-Email`, `X-User-Locale` (`pt` ou `en`), `X-User-Timezone` (IANA) e `X-User-Admin` (`1`, só para admin) quando o cookie é válido (sessão viva, conta ativa, termos aceitos), sem eles quando não é. assim rotas públicas das aplicações (ex.: banner ativo) continuam funcionando. cada aplicação decide quais rotas exigem login (401 sem `X-User-Id`)
- o nginx sempre define esses headers a partir da resposta do imago (`auth_request_set` + `proxy_set_header`), o que apaga qualquer `X-User-*` mandado pelo navegador. isso só é seguro porque os backends escutam em `127.0.0.1` e só o nginx chega neles
- toda `location` que chega ao backend de uma aplicação define os cinco headers: as com `auth_request`, a partir da resposta do imago; as sem (o `/health`), vazios (`proxy_set_header X-User-Id "";`, que não manda o header). sem isso, um `X-User-Admin` mandado pelo navegador chegaria ao backend. o teste do nginx no CI confere, em todas as rotas de cada aplicação, que nenhum `X-User-*` do cliente chega ao backend
- `GET /api/<app>/health` não passa pelo `auth_request`, para o monitor de cada aplicação não depender do imago
- a cada request com login, a aplicação cria ou atualiza a linha dela em `app_users`. só grava quando algo mudou
- `is_admin` chega às aplicações pelo `X-User-Admin`. cada aplicação confere esse header no `require_admin`
- cada request de API de qualquer aplicação passa pelo imago (uma leitura no sqlite). se o imago cai ou reinicia (em todo deploy dele), a API das aplicações responde 500 até ele voltar

```nginx
# infra/apps/imago/nginx.conf (dentro do server, junto com /imago/ e /api/imago/)
location = /_imago/session {
        internal;
        proxy_pass http://127.0.0.1:__PORTA__/internal/session;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Real-IP $remote_addr;
}
location /api/imago/internal/ { return 404; }

# infra/apps/<app>/nginx.conf
location /api/<app>/ {
        auth_request /_imago/session;
        auth_request_set $imago_user_id $upstream_http_x_user_id;
        # ... idem para email, locale, timezone e admin
        proxy_set_header X-User-Id $imago_user_id;
        # ... idem para os outros quatro
        proxy_pass http://127.0.0.1:__PORTA__/;
}
location = /api/<app>/health {
        # fora do auth_request: os cinco vazios, para os do cliente não passarem
        proxy_set_header X-User-Id "";
        # ... idem para os outros quatro
        proxy_pass http://127.0.0.1:__PORTA__/health;
}
location /api/<app>/internal/ { return 404; }
```

### desenvolvimento local
- um nginx em container (`nginx:1.24`, o mesmo do CI do infra) com os mesmos snippets faz o papel do de produção, na frente do imago e das aplicações rodando na máquina. a config fica em `apps/imago/dev/`
- dentro do container, `127.0.0.1` é o próprio container: o script de dev que troca o `__PORTA__` troca também `127.0.0.1` por `host.docker.internal` (Docker Desktop, no Windows e no Mac)
- não existe atalho de login no backend, nem em dev: o E2E também passa pelo código de login, lido no SMTP falso

## API interna
- só entre os serviços, direto em `127.0.0.1:<porta>`, nunca pelo nginx. o nginx responde 404 para `/api/<app>/internal/` no imago e em todas as aplicações
- autenticada por `Authorization: Bearer <token>`, comparado com `hmac.compare_digest`, com um token por aplicação:
  - o provision gera o token de cada aplicação de `infra/apps/` (menos o imago) na própria VM, uma vez (só se ainda não existir, para continuar idempotente), em `/etc/infra/internal/<app>.env` (`0600`, root, com `INTERNAL_API_TOKEN`), lido pela unit da aplicação com `EnvironmentFile=`
  - o provision monta, a partir desses arquivos, `/etc/infra/internal/imago.env` (`0600`, root, com `IMAGO_APP_TOKENS=ethos:<token>,engrafi:<token>`) e reinicia o `app-imago` quando ele muda
  - os tokens não passam pelo GitHub nem saem da VM
  - o mesmo token vale nos dois sentidos entre o imago e aquela aplicação. o imago sabe pelo token qual aplicação chamou (é esse o nome que vai no `mail_log` e no remetente), e uma aplicação não chama a API interna de outra: um bug ou uma invasão no engrafi não apaga dados do ethos
- exceção: `GET /internal/session`, chamado pelo nginx, não usa token. ele só lê o cookie que veio no request e devolve o que o próprio dono do cookie já vê em `/me`
- o imago expõe:
  - `GET /internal/session` (para o `auth_request`)
  - `POST /internal/mail` (envio de email, ver abaixo)
  - `POST /internal/users/lookup` com `{email}` (para convites: id e idioma, ou 404; conta inativa ou em exclusão também é 404). o email vai no corpo, nunca na URL, para não parar em log
  - `GET /internal/users/{id}` (email, idioma, fuso, ativo)
- cada aplicação expõe:
  - `POST /internal/users/{id}/delete`: apaga os dados daquela pessoa, com as regras do plano da aplicação. idempotente: id que a aplicação não conhece também é 200
  - `POST /internal/users/{id}/refresh`: recebe email, idioma e fuso e atualiza `app_users`. id que a aplicação não conhece é 200 sem criar nada
- o imago manda no `refresh` os valores da conta na hora da chamada, nunca os do momento em que a tarefa foi criada: uma tarefa que falhou e roda depois não desfaz uma mudança mais nova
- o imago sabe quais aplicações existem por `IMAGO_APPS` no `app.env` dele (ex.: `ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002`). o CI confere se cada aplicação de `infra/apps/` (menos o imago) está lá, com a porta igual ao `PORT` do `app.conf` dela. o imago não sobe se uma aplicação do `IMAGO_APPS` não tiver token no `IMAGO_APP_TOKENS`
- as aplicações acham o imago por `IMAGO_INTERNAL_URL` (`http://127.0.0.1:3003`)

## envio de email e limite compartilhado
- só o imago fala com o SMTP: só a unit dele lê `/etc/infra/smtp.env`. as aplicações mandam email por `POST /internal/mail`, com o tipo, o id do destinatário, o assunto e o corpo (texto e HTML, com todo dado do usuário escapado) já no idioma dele. o imago põe o endereço atual da pessoa
- só para usuários do imago, por id, nunca para um endereço qualquer: um bug numa aplicação não vira envio para fora. destinatário inativo ou em exclusão: 204, sem envio e sem contar no teto; id que não existe: 404
- remetente: `MAIL_FROM_ADDRESS` (`no-reply@manasomali.com`), com o nome da aplicação do token (ex.: "ethos <no-reply@manasomali.com>"). os emails do próprio imago saem como "manasomali.com"
- SMTP só com STARTTLS e certificado verificado, como no ethos: sem STARTTLS, nada sai
- **um teto só para todas as aplicações**, contado em janelas móveis (assim nunca passa da cota diária da Brevo, seja qual for a hora em que ela zera):
  - `MAX_EMAILS_PER_DAY=275`, em 24 h: os 300 da Brevo menos 25 para o aviso de teto ao `SUPPORT_EMAIL`, que fica fora da contagem e sai no máximo uma vez por hora (até 24 em 24 h)
  - `MAX_EMAILS_PER_HOUR=60`, em 1 h: segura rajadas
  - `MAIL_RESERVED_FOR_CODES_PER_DAY=60` e `MAIL_RESERVED_FOR_CODES_PER_HOUR=15`: o fim de cada janela fica só para códigos e emails de conta. notificações param quando a janela de 24 h chega a 215 ou a de 1 h chega a 45. sem a reserva por hora, os alertas do ethos de um horário cheio (20:00 é o padrão) gastariam a hora inteira e ninguém receberia código até a hora seguinte
- tipos: `code` (login, exclusão de conta), `account` (conta excluída, troca de email) e `notification` (convites, alertas e avisos das aplicações)
- ao bater o teto:
  - código: 429 ("tente mais tarde") e aviso ao `SUPPORT_EMAIL` (no máximo um por hora; o último aviso é o evento `send_cap_reached` do `audit_log`, lido e gravado na mesma transação). protege a cota e a reputação do domínio contra quem pede código para milhares de endereços trocando de IP
  - notificação: o imago responde 429 e a aplicação grava só uma linha de aviso no log, sem endereço. o que gerou o email continua visível no app (ex.: o convite pendente aparece para o convidado). cada aplicação decide se tenta de novo depois (os alertas do ethos tentam na hora seguinte)
- a contagem fica na tabela `mail_log` (aplicação, tipo e instante, sem destinatário), gravada na mesma transação `BEGIN IMMEDIATE` que confere o teto, antes de chamar o SMTP. se o SMTP falhar, a linha fica: conta a mais, nunca a menos
- envio em `BackgroundTasks`, depois do commit. o `POST /internal/mail` responde 202 assim que a linha do `mail_log` está gravada, sem esperar o SMTP: a aplicação não fica sabendo de falha de SMTP, que vira uma linha de erro no log do imago (tipo do email e do erro, sem destinatário)
- emails do próprio imago (templates em pt e en): código de login, código de exclusão de conta, conta excluída, troca de email (para o antigo e para o novo), teto de envio atingido (para o `SUPPORT_EMAIL`)
- os emails de cada aplicação (convite, alerta, avisos) ficam no plano dela

## exclusão de conta
- pedida na tela de conta (`POST /me/delete/request` manda um código para o email atual, `DELETE /me` com `{code}` apaga) ou pelo admin (`DELETE /admin/users/{id}`, mesma função de serviço). apaga a pessoa de todas as aplicações
- a tela avisa antes o que vai sumir e mostra o link de export de cada aplicação, para a pessoa levar os dados
- passos:
  1. numa transação `BEGIN IMMEDIATE` do imago: confere que não é o último admin ativo, status `deleting`, apaga sessões, códigos e tarefas `refresh` pendentes, e cria uma tarefa `delete` para cada aplicação de `IMAGO_APPS`. depois do commit, grava no journald só o id numérico da conta (`conta <id> excluída`). a pessoa já não entra
  2. ainda depois do commit (em `BackgroundTasks`), o imago chama `POST /internal/users/{id}/delete` em cada aplicação. cada uma apaga na própria transação, com as regras dela, e manda os avisos dela (ex.: "você perdeu acesso a um hábito") depois do commit
  3. quando a última tarefa termina (na request ou no timer), numa transação `BEGIN IMMEDIATE` que confere se a linha ainda existe (assim o passo roda uma vez só, mesmo com a request e o timer ao mesmo tempo): lê o email da linha, apaga a linha em `users`, apaga os eventos da própria conta no `audit_log` (auth, termos, perfil), tira o IP e os emails das linhas que citam a conta (ações do admin sobre ela, pelo `target_user_id`), como o ethos já faz, e grava um evento `account_deleted` com o id numérico e quem apagou (a própria pessoa ou qual admin), sem email. depois do commit, manda "conta excluída" ao email lido
- tarefa que falha fica para o `imago-cleanup.timer` (de hora em hora). depois de 5 falhas seguidas, grava uma linha de erro no journald a cada tentativa
- enquanto a exclusão não termina, o email não pode criar conta nova ("tente mais tarde")
- a conta do último admin ativo não pode ser apagada, nem pelo admin nem pelo `DELETE /me`
- para só bloquear sem apagar, o admin usa `is_active=false`: a pessoa não recebe código nem entra, e os dados ficam
- exclusão imediata, sem período de arrependimento. o código de confirmação já é a proteção contra clique por engano
- `PRAGMA secure_delete=ON` em todos os bancos, para o sqlite sobrescrever com zeros as páginas apagadas

### backups
- os dados apagados continuam nos backups até eles vencerem: snapshots locais guardam 7 dias (`infra/scripts/snapshot.sh`) e o litestream guarda 168h no object storage (`infra/lib/backups.sh`). ou seja, em até uns 8 dias o dado some de todo lugar
- se for preciso restaurar um backup (do imago ou de qualquer aplicação), as contas apagadas depois daquele ponto voltam. por isso, depois de um restore, rodar `python -m app.cli reapply-deletions` no imago antes de abrir os apps de novo: ele lê os ids do journal do `app-imago` e refaz as exclusões no imago e em todas as aplicações, sem mandar email
- restaurar o imago também perde as contas criadas depois daquele ponto. a pessoa entra de novo como conta nova, e os dados antigos dela ficam órfãos nas aplicações (ninguém os vê, porque o id aleatório não volta a ser sorteado) até serem religados ou apagados à mão
- a política de privacidade explica o que é apagado, o que fica sem identificação e o prazo de até 8 dias nos backups

## admin
- painel em `/imago/admin`, só para `is_admin`
- contas: listagem com email, datas (cadastro, último login) e status, busca por email, bloquear (`is_active=false`, apaga as sessões; nunca a própria conta), trocar email e excluir
- envios de email: quantos cada aplicação mandou nas últimas 24 h, por tipo, e quanto falta para o teto
- toda ação do admin grava no `audit_log`, com a conta alvo em `details.target_user_id`
- o painel de cada aplicação cuida só do conteúdo dela (e de quem usa aquela aplicação)

## tela de conta
- email (só leitura) e como pedir a troca ao `SUPPORT_EMAIL`
- idioma e fuso (lista de fusos IANA com busca)
- sair e sair de todos os aparelhos (`POST /auth/logout-all`, que substitui o "trocar senha" para expulsar um aparelho perdido)
- exclusão de conta em passos: aviso do que some em cada aplicação → links de export → código → confirmação final
- lista das aplicações, com link para cada uma
- a lista vem do `IMAGO_APPS` (o `GET /me` devolve os nomes, e o link é `/<nome>/`). os textos de cada aplicação (o que some na exclusão e onde exportar) ficam nos `translation.json` do imago, em pt e en, e o CI confere que toda aplicação do `IMAGO_APPS` tem os dela

## termos de uso e política de privacidade
- um par só para todas as aplicações: `/imago/termos` e `/imago/privacidade`, em pt e en, com link no rodapé do imago e das aplicações e na tela de entrar ("ao continuar, você concorda com os termos de uso e a política de privacidade")
- cada versão tem um identificador (a data, `AAAA-MM-DD`), fixo no código do back (`app/terms.py`) e do front, nunca em variável de ambiente: a versão muda no mesmo PR dos textos, e um teste falha se as duas forem diferentes, como no ethos. `users.terms_version` guarda a versão aceita. qualquer mudança (inclusive a entrada de uma aplicação nova) pede o aceite de novo no próximo acesso
- termos de uso devem cobrir: serviço gratuito sem garantia de disponibilidade, planos pagos e anúncios no futuro, uso aceitável (sem abuso de convites e envio de códigos), bloqueio e exclusão de conta por abuso, limites de uso, a conta vale para todas as aplicações, troca de email só pelo suporte, contato (`SUPPORT_EMAIL`), e uma seção por aplicação com as regras dela
- política de privacidade deve cobrir: dados da conta (email, fuso, idioma, IP e navegador nas sessões e na auditoria de login), os dados de cada aplicação (numa seção por aplicação), para que são usados, onde ficam (VM e Object Storage da Oracle, provedor de email), quem vê (membros do que for compartilhado em cada aplicação e o administrador do serviço, que tem acesso ao conteúdo das aplicações), prazos (sessão 60 dias, código 10 min, auditoria de auth e IPs 90 dias), exclusão (imediata em todas as aplicações, até 8 dias nos backups), quais emails o serviço manda (só de conta, segurança, convite, alerta e avisos das aplicações; nada de marketing), único cookie é o de sessão, sem rastreamento e sem venda de dados, contato
- o texto de cada seção de aplicação vem do plano dela

## retenção de dados
- sessões: 60 dias sem uso, renovadas com o uso
- códigos: valem 10 min; a linha fica 1 dia, porque o limite de envio por email conta essas linhas
- eventos de auth no `audit_log` (login, logout etc.): 90 dias
- ações do admin e eventos da conta (termos, perfil): enquanto a conta existir
- IP nas linhas do `audit_log` e de `sessions`: apagado (vira `NULL`) depois de 90 dias
- `mail_log`: 48 h
- tarefas `app_tasks` concluídas: 7 dias
- a limpeza roda no `imago-cleanup.timer` (`python -m app.cli cleanup`)

## config (variáveis de ambiente)
- `APP_ENV` (`prod`; `dev` só na máquina de quem desenvolve), `APP_URL` (`https://manasomali.com/imago`; a origem dele é a do `Origin` aceito), `DATABASE_PATH`, `SUPPORT_EMAIL`, `MAIL_FROM_ADDRESS`, `EMAIL_BACKEND` (`smtp`; `console` só com `APP_ENV=dev`), `IMAGO_APPS`
- `MAX_EMAILS_PER_DAY=275`, `MAX_EMAILS_PER_HOUR=60`, `MAIL_RESERVED_FOR_CODES_PER_DAY=60`, `MAIL_RESERVED_FOR_CODES_PER_HOUR=15`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (de `/etc/infra/smtp.env`) e `IMAGO_APP_TOKENS` (de `/etc/infra/internal/imago.env`)
- a versão dos termos não é config: fica no código (ver "termos de uso e política de privacidade")

### tamanhos e formatos
- email: até 254 caracteres, salvo com strip + lower. só ASCII (domínio internacional em punycode), porque vai no header `X-User-Email`
- fuso: um nome de `zoneinfo.available_timezones()`. idioma: `pt` ou `en`
- paginação de listas (admin): 50 itens por página por padrão, máximo 200

## stack
igual à do ethos (seção "stack" do `ethos-plan.md`): react + vite, python + fastapi, sqlalchemy 2 síncrono + alembic, `uv`, os mesmos PRAGMAs e `BEGIN IMMEDIATE`, `uvicorn --workers 1`, `MemoryMax=150M`, erros no formato `{"error", "field"}` com catálogo próprio, logs sem IP, email, código, token nem cookie.
- frontend em `/var/www/imago/` (vite `base: '/imago/'`, react router `basename="/imago"`), com os tokens de `packages/tokens`
- backend como `app-imago` em `/opt/apps/imago/`, porta 3003, com `--root-path /api/imago` no `uvicorn` da unit (o parâmetro `root_path` do `FastAPI()` está obsoleto desde o FastAPI 0.162)
- a unit lê `/etc/infra/smtp.env`, `/etc/infra/internal/imago.env` e `/etc/infra/apps/imago.env`. é a única que lê o `smtp.env`: o provision passa a reiniciar só o `app-imago` quando as credenciais SMTP mudam (hoje `provision_apps` reinicia todas as aplicações)
- agendador: `imago-cleanup.timer` (de hora em hora) roda `python -m app.cli run-tasks` (tarefas pendentes para as aplicações) e `python -m app.cli cleanup`
- CLI: `create-admin`, `run-tasks`, `cleanup`, `reapply-deletions`, `import-users` (migração do ethos, uma vez só) e `seed`
- o `seed` (só em dev) cria as contas de exemplo com ids fixos, que os seeds das aplicações usam para criar os dados delas
- nginx (`infra/apps/imago/nginx.conf` e `nginx-http.conf`): `/imago/` com os mesmos headers e cache do frontend do ethos, `/api/imago/` com proxy, `/api/imago/auth/` com `limit_req` (zona `imago_auth`), `/_imago/session` interno e 404 em `/api/imago/internal/`
- deploy (`.github/workflows/imago.yaml`): os mesmos 9 passos do ethos, com `concurrency: imago-deploy`, a variável `IMAGO_URL` e a checagem da versão do python (`.github/scripts/check-python-version.sh`)
- os scripts do deploy ficam em `packages/deploy/` e recebem o nome da aplicação (`bash -s -- imago <passo> < packages/deploy/vm.sh`; contrato em `packages/deploy/README.md` e "stack" do `engrafi-plan.md`), porque o imago não importa código do ethos. o imago é a primeira aplicação nova a usá-los
- monitoramento: o monitor externo chama `/api/imago/health`, além do health de cada aplicação
- o login depende 100% do email chegar: DKIM e DMARC no domínio (feitos na ETH-01; não há SPF próprio, o envelope sai pelo domínio da Brevo e o DMARC alinha pelo DKIM) e a cota do provedor (Brevo, 300 por dia), que define os tetos acima

### estrutura no monorepo
```
.github/workflows/imago.yaml
infra/apps/imago/
  app.conf               # PORT=3003, PYTHON_VERSION
  app.env                # APP_URL, SUPPORT_EMAIL, MAIL_FROM_ADDRESS, IMAGO_APPS, tetos de email
  app-imago.service
  imago-cleanup.service
  imago-cleanup.timer
  nginx.conf             # /imago/, /api/imago/ e /_imago/session (dentro do server)
  nginx-http.conf        # limit_req_zone imago_auth (contexto http)
apps/imago/
  README.md
  dev/                   # nginx em container para desenvolvimento e E2E
  backend/
    .python-version
    pyproject.toml
    uv.lock
    alembic.ini
    alembic/versions/
    app/
      main.py            # FastAPI(), routers, GET /health (o prefixo vem do --root-path)
      config.py
      db.py
      models.py
      audit.py
      errors.py
      terms.py           # TERMS_VERSION
      cli.py             # create-admin, run-tasks, cleanup, reapply-deletions, import-users, seed
      auth/
        router.py        # /auth/*, /me
        service.py       # pedir e verificar código, sessão
        security.py      # códigos, tokens, hashes, id da conta
        deps.py          # current_user, require_admin, checagem de Origin
      mail/
        quota.py         # teto compartilhado e reserva para códigos
        sender.py        # SMTP
        templates/       # emails do imago, em pt e en
      internal/
        router.py        # /internal/session, /mail, /users/*, token de cada aplicação
        tasks.py         # tarefas delete e refresh para as aplicações
      deletion.py        # exclusão de conta, usada pelo usuário e pelo admin
      admin/
        router.py
    tests/
  frontend/
    package.json
    vite.config.js       # base: '/imago/', importa packages/tokens
    public/locales/{pt,en}/translation.json
    src/
    e2e/
```

### tabelas
- `users`: id (inteiro aleatório, ver "id da conta"), email (único, salvo com strip + lower), status (`active` | `deleting`), is_active, is_admin, timezone, locale, terms_version, terms_accepted_at, created_at, updated_at, last_login_at
- `sessions`: token_hash (sha256 do token, chave primária), user_id, created_at, expires_at, last_seen_at, ip, user_agent
- `login_codes`: id, email (destino do código), user_id (vazio no login, preenchido nas ações de conta), purpose (`login` | `delete_account`), code_hash, attempts, expires_at, used_at, created_at
- `audit_log`: id, user_id, event, ip, created_at, details (json). eventos de auth e ações do admin sobre contas (a conta alvo em `target_user_id`)
- `mail_log`: id, app, kind (`code` | `account` | `notification`), created_at. sem destinatário
- `app_tasks`: id, user_id, app, action (`delete` | `refresh`), attempts, last_attempt_at, done_at, created_at. no máximo uma pendente por (user_id, app, action)
- chaves estrangeiras: `ON DELETE CASCADE` de `users` para `sessions`, `login_codes` e `app_tasks`, e `ON DELETE SET NULL` em `audit_log.user_id`

### endpoints (`/api/imago/...`)
- `POST /auth/code/request`: recebe `{email}`. sempre responde 202 com o mesmo corpo, exista a conta ou não. conta inativa não recebe email
- `POST /auth/code/verify`: recebe `{email, code, timezone, locale}`. cria o usuário se for o primeiro acesso (com o fuso e o idioma do navegador), cria uma sessão nova e seta o cookie. para quem já tem conta, `timezone` e `locale` são ignorados. código recusado (errado, vencido, usado ou sem código) dá sempre o mesmo 400; fuso desconhecido no primeiro acesso, 422
- `POST /auth/logout`: apaga a sessão atual
- `POST /auth/logout-all`: apaga todas as sessões do usuário
- `GET /me`: usuário logado, se precisa aceitar uma versão nova dos termos e a lista das aplicações
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

## migração do login do ethos
o ethos está no ar com login próprio: `users`, `sessions`, `login_codes` e o cookie `__Host-ethos_session` no banco dele. as contas passam para o imago com os mesmos ids, para os hábitos continuarem ligados às mesmas pessoas. a ordem, que segue a regra de a infra entrar num PR anterior ao da aplicação:
1. infra: `infra/apps/imago/`, a linha `imago` no `databases.txt` e os tokens da API interna. nada muda para o ethos ainda
2. deploy do imago, sem link para ele em lugar nenhum. ele ainda não tem contas
3. infra: `auth_request` em `/api/ethos/` (o imago já responde), `IMAGO_INTERNAL_URL` e o token nas units do ethos. continuam a location `/api/ethos/auth/`, o `nginx-http.conf` do ethos e o `smtp.env` nas units dele: o ethos atual ignora os `X-User-*` e segue com o login dele
4. com o `app-ethos` e o `ethos-alerts.timer` parados (assim nenhuma conta nasce ou some no ethos no meio da passagem): `export-users` no ethos (comando que entra antes, num deploy normal do ethos) e `import-users` no imago, ligados por um pipe (`systemd-run ... export-users | systemd-run ... import-users -`), sem arquivo em disco. passam id, email, `is_active`, `is_admin`, fuso, idioma, `created_at` e `last_login_at`. o import roda numa transação só e não grava nada se algum id ou email já existir no imago. sessões e aceite dos termos não passam: todo mundo entra de novo uma vez e aceita os termos novos
5. logo em seguida, deploy do ethos que lê os headers: `users` vira `app_users` (mesmos ids; o `ALTER TABLE ... RENAME` do sqlite leva junto as chaves estrangeiras), os eventos de auth e os IPs do `audit_log` do ethos são apagados, e o ethos para de usar `sessions` e `login_codes` e apaga o cookie antigo (`Max-Age=0`) quando o recebe. as tabelas e colunas que sobram saem num deploy seguinte. o rename é a exceção à regra das migrações só aditivas: voltar deste deploy exige o `pre-deploy-<sha>.db`, e não só o commit anterior
6. infra: saem a location `/api/ethos/auth/`, o `nginx-http.conf` do ethos e o `smtp.env` das units dele
7. o `infra/RESTORE.md` passa a mandar rodar o `reapply-deletions` do imago (journal do `app-imago`). o do ethos continua valendo só para as exclusões de antes da passagem
- entre os passos 2 e 5 o imago não tem link em lugar nenhum. se alguém achar o `/imago/` e criar conta, nada quebra: o import só recusa id ou email repetido, e uma tarefa `delete` para o ethos falha e é repetida pelo timer até o ethos ter o `/internal/users/{id}/delete`
- o ethos fica fora do ar do passo 4 até o fim do deploy do passo 5. o README do imago traz o roteiro desses passos com os comandos

## planejamento a longo prazo
- captcha no `POST /auth/code/request`, só se houver abuso
- segundo fator para o admin

## riscos aceitos
- código no chute: com 5 tentativas por código e 5 códigos por hora, quem insistir contra uma conta o ano inteiro tem cerca de 20% de chance de acertar. a vítima recebe até 120 emails por dia enquanto isso, e o ataque gasta quase metade do teto diário. vale também para a conta do admin
- teto esgotado de propósito: quem pede código para muitos endereços, trocando de IP, esgota o teto diário, e ninguém recebe código até a janela de 24 h andar. quem já tem sessão continua entrando. o aviso ao `SUPPORT_EMAIL` mostra o problema; a resposta é o captcha
- admin sem segundo fator: quem invadir o email do admin ou acertar o código dele vira admin de todos os usuários, e passa a ver o conteúdo de todas as aplicações
- o imago é ponto único de falha: se ele cair ou reiniciar (em todo deploy dele), o `auth_request` falha e a API de todas as aplicações responde 500 (menos o `/health` delas) até ele voltar
- exclusão de conta não é atômica entre os bancos: se uma aplicação falhar, os dados dela ficam até o timer conseguir. a pessoa já não entra durante esse tempo
- emails enviados por `BackgroundTasks` se perdem se o serviço reiniciar antes de enviar
- reaplicar exclusões depois de um restore depende do journald, que tem limite de 100M e some junto se a VM for perdida
- teto de email compartilhado: uma aplicação com muitas notificações pode gastar a parte das outras. a reserva para códigos garante que o login continua funcionando
- descadastro na Brevo: ela põe `List-Unsubscribe` nos emails transacionais, e quem clica entra na lista de bloqueio dela e deixa de receber o código de login. o suporte tira a pessoa da lista no painel da Brevo
- mesma origem: site, imago e aplicações dividem a origem, então um XSS em qualquer um deles age como a pessoa em todos (o cookie é `HttpOnly`, mas o script faz requests com ele). o imago e as aplicações têm CSP sem `'unsafe-inline'`; o site é estático e não mostra conteúdo de usuário
- memória: o imago é mais um processo python na VM de 1 GB (com `MemoryMax=150M`). medir depois do go-live
- cota do Object Storage: o banco `imago` é mais um no Litestream. escreve pouco (logins e uma renovação de sessão por dia), mas medir depois do go-live junto com os outros
- LGPD ignorada por enquanto
