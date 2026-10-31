# ethos

## estrutura
- o site `manasomali.com` é o produto principal e hospeda aplicações. o ethos é a primeira (por enquanto a única)
- tudo fica num monorepo só (este repo): site, aplicações e infra (ver "monorepo")
- aplicação que roda em paralelo ao site estático, acessada pelo path `manasomali.com/ethos/` (api em `manasomali.com/api/ethos/`)
- conta com um frontend e um backend
- usa o nginx para roteamento
- usa banco de dados sqlite já provisionado
- login pela conta única do `manasomali.com` (`/conta/`), compartilhada com as outras aplicações (ver `conta-plan.md`). o ethos não tem auth próprio

## monorepo

### layout
```
imanasomali/
  README.md                                 # visão geral do monorepo
  site/                                     # site (produto principal)
    src/, public/, index.html
    package.json, package-lock.json
    vite.config.js, eslint.config.js
    README.md
  packages/
    tokens/tokens.css                       # tokens de design compartilhados entre site e apps
  apps/
    README.md                               # convenção para criar uma aplicação nova
    conta/                                  # login único de todas as aplicações (conta-plan.md)
    ethos/
      README.md
      backend/
      frontend/
  infra/
    apps/
      conta/
      ethos/                                # o que roda como root na VM: units, nginx, config
  .github/workflows/
    deploy.yaml                             # site (já existe)
    conta.yaml                              # conta: checagens em PR, deploy na main
    ethos.yaml                              # ethos: checagens em PR, deploy na main
    infra.yaml
    backup-verify.yaml
```
- o site sai da raiz e vai para `site/`, com a mesma estrutura de uma aplicação: cada área tem a sua pasta e a raiz só guarda o que é do monorepo inteiro (README, `.gitignore`, `.gitattributes`, workflows)
- a mudança é feita com `git mv`, num commit só de movimentação (sem editar conteúdo junto), para o git reconhecer os arquivos como renomeados e `git log --follow` / `git blame` continuarem mostrando o histórico
- o deploy do site muda: build dentro de `site/` e publicação de `site/dist/`. o resultado publicado em `/var/www/html/` tem que ser o mesmo de antes
- o site é independente como as aplicações: `package.json` e `package-lock.json` próprios no front, `pyproject.toml` e `uv.lock` próprios no back. sem npm workspaces, para o `npm ci` do site não instalar dependências do ethos e vice-versa
- uma aplicação não importa código do site nem de outra aplicação. a única coisa compartilhada é `packages/`. assim dá para tirar uma aplicação para outro repo ou outro servidor sem desmontar nada

### convenção de uma aplicação `<nome>`
- código em `apps/<nome>/`
- config que roda como root em `infra/apps/<nome>/`: `app.conf` (porta e versão do runtime), `app.env` (config não secreta), units systemd e snippets do nginx
- banco: linha `<nome>` em `infra/databases.txt`
- rotas: front em `/<nome>/`, api em `/api/<nome>/`
- workflow: `.github/workflows/<nome>.yaml`
- porta registrada na tabela do `infra/README.md`
- o provision instala tudo que estiver em `infra/apps/*/` sem código específico por aplicação
- remover a pasta não apaga dados nem código: o provision para e desabilita as units da aplicação, tira os snippets do nginx e avisa no log. o banco segue a regra do `databases.txt`
- uma aplicação conta como publicada quando existe `/var/www/<nome>/index.html`. só aí o smoke test checa as rotas dela

### workflows por caminho
- site (`deploy.yaml`): roda em `site/**`, `packages/**` (o site usa os tokens) e no próprio workflow. troca o `paths-ignore` atual por `paths`, como os outros workflows
- ethos (`ethos.yaml`): roda em `apps/ethos/**`, `packages/**` e no próprio workflow
- infra (`infra.yaml`): continua em `infra/**`, o que inclui `infra/apps/**`
- um push que toca mais de uma área dispara mais de um workflow, em paralelo. não existe ordem garantida entre eles
- regra: mudança de infra de que a aplicação depende (unit nova, variável nova, porta) entra num PR anterior ao da aplicação. o deploy da aplicação confere se a unit existe e falha com mensagem clara se não existir
- o deploy do ethos não usa o grupo de concorrência `infra`: o GitHub mantém só um run pendente por grupo e cancelaria um deploy na fila atrás de um provision ou de um teste de restauração

### checagens entre áreas (só possíveis no monorepo)
- a versão do python em `infra/apps/ethos/app.conf` é igual à de `apps/ethos/backend/.python-version`
- a porta de cada aplicação é única e está na tabela do `infra/README.md`
- cada aplicação de `infra/apps/` (menos a conta) está no `CONTA_APPS` da conta, com a mesma porta
- a versão dos termos é igual no front e no back da conta

### identidade compartilhada
- tokens de design (cores, tipografia, larguras, valores do tema escuro) saem do `site/src/index.css` para `packages/tokens/tokens.css`, usado pelo site e pelas aplicações
- site e aplicações estão na mesma origem (`manasomali.com`), então dividem o `localStorage`. o tema (`localStorage.theme`) e o idioma (`localStorage.i18nextLng`) usam as mesmas chaves em todos: quem escolhe tema escuro no site entra no ethos com tema escuro
- a conta também é compartilhada: um login vale para todas as aplicações (ver `conta-plan.md`)
- o site ganha uma vitrine de aplicações, com link para o ethos, quando ele entrar no ar

## nome do projeto
ethos (representa os hábitos, os costumes sociais e as práticas culturais que se repetem até virar um padrão automático na sociedade)

### sub titulo
aplicativo para cadastro de habitos

## proposta base
o produto server para monitorar certo "habitos" no decorrer do tempo, a pagina principal do app eh um calendario anual, dividido por mes, e cada dia eh um botao para clicar quando o habito foi cumprido no dia. Por exemplo, habito de "exercicio fisico", quando foi realizado exercicio no dia o usuario marca no dia e fica o botao muda de status mostrando que a tarefa foi executada

## detalhes e regras:

- para cada "habito", pode ser definido a possibilidade de marcar mais de uma vez por dia, o padrao eh uma marcacao por dia, resultando em um "toggle", mas em "configuracoes" do "habito" pode-se definir que ele pode receber mais de uma "marcacao" por dia, nesse caso a interface fica mais complexa

- o produto deve ter uma aba por "habito", para o usuario ser capaz de marcar e ver isoladamente cada um. tambem deve ter uma aba principal para mostrar o todas as marcacoes de todos os habitos em uma unica visualizacao

- para cada "habito" deve ter uma tela de configuracao, "nome", "descricao", "periodicidade desejada", "cor", "codigo". o "codigo" eh uma sigla opcional; quando definido, aparece no lugar do nome. a "periodicidade desejada" eh uma definicao do usuario dependendo do "habito". Por exemplo, "desejo fazer execicio fisico 3 vezes por semana", ou "desejo meditar uma vez na semana", ou "desejo comer pizza somente duas vezes por mes", ou "desejo viajar uma vez por ano".

- o produto deve ter um relatorio do "progresso do habito"
 
- o produto deve ter a opcao de criar "alertas" por "habito", caso o objetivo nao esteja sendo cumprido (mediante a configuracao).

- cada "habito" pode ou nao ter uma "duracao", por exemplo, "desejo meditar durante 40 min, uma vez na semana", essa eh uma configuracao adicional para cada "habito" e nao eh obrigatoria. essa configuracao eh desativada por padrao mas pode ser ativada em "configuracoes" de determinado "habito".

- para cada "marcacao", pode ou nao ter uma descricao de texto em aberto/livre, como se fosse uma "observacao", essa configuracao eh desativada por padrao mas pode ser ativada em "configuracoes" de determinado "habito". essa feature serve somente como um lembrete e nao eh obrigatoria.

- cada "habito" vai ter uma "pontuacao" de 0 a 100, de acordo com o cumprimento dele, essa "pontuacao" eh definida de maneira deterministica. dependendo do valor da "pontuacao" o "habito" aparece "sucesso" ou "falha", o valor limite eh configurado pelo usuario na tela de configuracoes do habito. essa configuracao serve somente como um lembrete e nao eh obrigatoria. essa configuracao eh desativada por padrao mas pode ser ativada em "configuracoes" de determinado "habito".

- cada "habito" pode ter uma "recompensa" a ser configurada caso "sucesso". por exemplo, "desejo fazer execicio fisico 3 vezes por semana" caso sucesso "como recompensa posso comer uma pizza", ou "quero nao fumar todos os dias da semana" caso sucesso "como recompensa posso viajar nas ferias". essa configuracao serve somente como um lembrete e nao eh obrigatoria. essa configuracao depende da definicao de "pontuacao", eh desativada por padrao mas pode ser ativada em "configuracoes" de determinado "habito".

- cada "habito" pode ter uma "punição" caso nao for cumprido com "sucesso", "desejo fazer execicio fisico 3 vezes por semana" caso falha "como punicao devo correr 50 min no domingo", essa configuracao tambem serve somente como um lembrete e nao eh obrigatoria. essa configuracao depende da definicao de "pontuacao", eh desativada por padrao mas pode ser ativada em "configuracoes" de determinado "habito"

- adicionalmente, cada "habito" por ter um "custo" associado, o usuario pode definir um valor, somente monetario, e caso for definido esse "custo" ele aparece na tela de relatorio e. por exemplo "quero parar de apostar", o custo nesse caso eh o valor monetario da aposta, e pode-se definir um limite mensal, semanal ou anual para esse habito, quando estourar o limite ou estiver perto pode ser exibido um alerta. esse "custo" pode ser definido a "nivel de habito" ou a "nivel de marcacao", por exemplo "o habito de tomar uma lava de coca cola por dia tem o custo de 8,00 reais fixo (nivel de habito)", ou "o habito de apostar todo dia tem o custo da aposta em questao, varia para cada marcacao (nivel de marcacao), entretanto pode ser definido um valor padrao para faciliar". essa configuracao tambem serve somente como um lembrete e nao eh obrigatoria. essa configuracao eh desativada por padrao mas pode ser ativada em "configuracoes" de determinado "habito"

- na aplicacao deve existir uma tela de "relatorio" ou "status" que pode ser acessada a qualquer momento para verificar como esta o andamento do "habito". nessa tela eh possivel realizar o export dos resultados em varios formatos de arquivo, podendo escolher qual o periodo e o habito vai aparecer no relatorio (pode ser mais de um) e pode tambem ativar ou desativar a exibicao de outras informacoes, como "obeservacao", "recomenpensa", "punicao" etc. adicionalmente o usuario pode compartilhar o relatorio em redes sociais.

- a aplicacao permite compartilhar determinados "habitos" com outras pessoas, dessa forma, outros usuarios podem editar/marcar junto com voce, para ativar isso o usuario convidado deve aceitar o convite e ele pode ser deletado pelo dono original do "habito", adicionalmente o dono do "habito" pode-se definir um nivel de permissao para o convidado, "visualizacao" ou somente "edicao"

- a aplicacao deve contar com uma auditoria realizando a persistencia da informacao do momento e quem realizou a marcacao. essa informacao pode ser vista em "detalhes" de cada marcacao ou no formato de historico em uma tela dedicada, com filtros

- a aplicacao deve uma documentacao bem clara e objetiva em relacao ao uso do sistema, talvez uma tela dedicada para isso

## decisões de produto

### meta e periodicidade
- a periodicidade é sempre "N vezes por semana, mês ou ano"
- "tipo da meta": `mínimo` (pelo menos N), `máximo` (no máximo N) ou `exato` (exatamente N)
- semana começa na segunda (padrão ISO)
- com "duração" ligada, conta a soma dos minutos de todas as marcações do período, comparada com N × duração pelo mesmo tipo de meta. ex.: "meditar 40 min, 1 vez por semana, mínimo" cumpre com duas sessões de 20 min
- num hábito "toggle" (uma marcação por dia), o valor do período é o número de dias marcados. com várias marcações por dia, é o número de marcações
- valores de N:
  - N ≥ 1 em `mínimo` e `exato`. N = 0 é permitido só em `máximo` (hábito de "não fazer", ex.: "quero não fumar": máximo 0 vezes por semana)
  - toggle: N ≤ dias do período (7 na semana, 28 no mês, 365 no ano), para a meta ser sempre possível
  - várias marcações por dia: N ≤ `MAX_MARKS_PER_DAY` × dias do período
- mudar a configuração não apaga dados:
  - recurso desligado (duração, custo, observação) fica escondido e é ignorado no cálculo. religar mostra os dados antigos de novo
  - de várias marcações para toggle: dia com 1 ou mais marcações conta como dia marcado; as marcações extras continuam guardadas

### pontuação
- desligada por padrão (`score_enabled`). ligar a pontuação mostra a pontuação, o limite e o sucesso/falha, e libera recompensa e punição
- 0 a 100 = porcentagem dos períodos considerados em que a meta foi cumprida, arredondada meio para cima (o `round` do python arredonda para o par, então não usar). sem nenhum período considerado, mostra "sem dados" em vez de um número
- sucesso quando a pontuação é maior ou igual ao limite (`score_threshold`, de 1 a 100, padrão 70). falha quando é menor. "sem dados" não é sucesso nem falha
- períodos considerados: do primeiro período completo depois da criação até o anterior ao atual. ignora o período em que o hábito foi criado (começou pela metade), o período atual (ainda não terminou), tudo antes da criação e qualquer período em que o hábito ficou pausado. ex.: hábito semanal criado numa quarta só começa a contar na segunda seguinte
- não é gravada no banco: é calculada na hora a partir das marcações e da meta atual. por isso, mudar a meta recalcula o histórico inteiro
- calculada no fuso de quem vê, como o calendário. num hábito compartilhado entre fusos diferentes, dois membros podem ver pontuações um pouco diferentes (a documentação explica)
- uma função só (`score.py`) calcula para a tela e para os alertas

### marcações e fuso horário
- tudo é salvo em UTC. o front converte para o fuso de quem está vendo
- marcar hoje grava o instante atual. marcar um dia passado grava 12:00 do fuso de quem marcou naquele dia, convertido para UTC
- só passado e hoje, livremente. o backend recusa `marked_at` no futuro (com 1 min de tolerância para relógio)
- dias antes da criação do hábito podem ser marcados (para registrar o histórico), mas ficam fora da pontuação
- toggle com duração ligada: o clique marca com a duração padrão do hábito (`duration_minutes`). os minutos podem ser editados nos detalhes da marcação
- editar marcação: dono e editor editam observação, duração e custo de qualquer marcação. a data não muda; para mudar, apaga e cria de novo
- o fuso (`users.timezone`, IANA) fica na conta e chega ao ethos no header `X-User-Timezone`, com uma cópia em `app_users` para os alertas. é só preferência, usado pelo backend para calcular pontuação e alertas. os dados continuam em UTC
- o fuso nasce com o do navegador no primeiro login e depois só muda na tela de conta (`/conta/`). quando o fuso do navegador fica diferente do salvo (ex.: numa viagem), o app sugere a troca, com um link para lá
- limitação aceita: num hábito compartilhado entre fusos muito distantes, uma marcação pode aparecer no dia vizinho para o outro membro

### pausar e arquivar
- pausado: continua visível e marcável, mas os períodos com pausa não contam na pontuação e não disparam alertas
- arquivado: some da tela principal, fica só leitura (não marca, não dispara alerta), a pontuação congela na data do arquivamento. pode ser desarquivado
- arquivado não conta no limite de hábitos por usuário

### compartilhamento
- o hábito compartilhado é conjunto: um calendário só, e a marcação de qualquer membro aparece para todos
- num hábito "toggle", se duas pessoas marcam o mesmo dia, conta uma vez só. desmarcar tira a marcação do dia para todos
- papéis:
  - dono: único que edita a configuração, convida, remove membros e apaga o hábito
  - edição: marca, desmarca e apaga marcações, inclusive de outras pessoas
  - visualização: só vê
- todos os membros veem custo, recompensa, punição e observações
- só dá para convidar email que já tem conta no `manasomali.com` (o ethos pergunta à conta por `POST /internal/users/lookup`). para não revelar quem tem conta, a resposta é sempre "convite enviado". se o email não tem conta, o convite fica pendente para sempre e nunca é entregue (nem se a conta for criada depois)
- o convite não expira. o dono pode cancelar um convite pendente
- o convidado aceita ou recusa dentro do app e recebe um email avisando do convite
- o convidado pode sair sozinho, e o dono pode removê-lo. nos dois casos, as marcações dele continuam no hábito e os alertas dele naquele hábito são apagados
- o hábito compartilhado conta só no limite do dono
- cada usuário participa de no máximo `MAX_SHARED_HABITS_PER_USER` hábitos de outras pessoas
- o dono convida no máximo `MAX_INVITES_PER_DAY` pessoas por dia, somando todos os hábitos (protege contra abuso de envio de email)
- apagar o hábito manda um email aos membros e apaga junto a auditoria daquele hábito

### alertas
- por email, configurados pelo dono e por cada editor em cada hábito, desligados por padrão. quem tem papel de visualização não liga alertas
- quando o dono rebaixa um editor para visualização, os alertas dele naquele hábito são apagados
- não disparam no período em que o hábito foi criado, pela mesma razão da pontuação (o ritmo seria medido desde o início de um período que o hábito não viveu inteiro)
- um registro por membro e hábito, com duas chaves independentes: alerta de meta e alerta de custo
- o usuário escolhe quando o alerta é avaliado: horário (hora cheia, no fuso dele) e frequência (diária ou semanal, com o dia da semana)
- quando dispara, olhando o período atual:
  - `mínimo`: está atrasado no ritmo, ou seja, valor < `floor(N × fração do período que já passou)`, calculado com inteiros (`N × segundos passados // segundos do período`) para não errar por arredondamento de float. ex.: 3x por semana sem nenhuma marcação fica atrasado a partir de quarta às 08:00 (3 × 56 h / 168 h = 1)
  - `máximo`: atingiu ou passou de N
  - `exato`: passou de N, ou está atrasado no ritmo
  - custo: o gasto do período chegou a 80% do limite (aviso) ou passou do limite
- no máximo um email por membro e hábito por dia, juntando tudo o que disparou (meta e custo). o email tem link para a tela de configuração do alerta
- o email sai pela conta, como `notification`, e entra no teto compartilhado entre as aplicações. se o teto recusar, o alerta não grava `last_sent_at` e tenta de novo na hora seguinte

### custo
- só monetário, numa unidade genérica de dinheiro: sem símbolo de moeda, número formatado pelo idioma com 2 casas
- guardado em centavos, como número inteiro
- "nível de hábito": todo mundo que marca gera o custo fixo do hábito. "nível de marcação": cada marcação tem o seu valor, com o custo do hábito preenchido como padrão
- o custo é gravado na marcação no momento em que ela é criada (`marks.cost_cents`), nos dois níveis. mudar o custo do hábito não reescreve o gasto passado
- limite opcional por semana, mês ou ano, que alimenta o alerta de custo

### relatório e export
- tudo gerado no navegador
- formato principal: imagem para postar em redes sociais, compartilhada pela Web Share API (`navigator.share` com arquivo). onde não houver suporte, baixa o PNG
- imagem: 1080×1350 (retrato, bom para redes sociais), gerada em `<canvas>` sem lib. traz o mapa de calor do período, a pontuação e o sucesso/falha de cada hábito (quando a pontuação está ligada) e as informações escolhidas pelo usuário
- também exporta CSV e JSON:
  - CSV: uma linha por marcação, com as colunas hábito, data, horário, autor, duração, custo e observação. colunas de recursos desligados ou não escolhidos saem do arquivo. células que começam com `=`, `+`, `-` ou `@` recebem um `'` na frente, para o Excel não executar fórmula
  - JSON: `{ "version", "generated_at", "period": {from, to}, "habits": [{ configuração, "marks": [...], "periods": [resumo de cada período] }] }`, com o schema documentado em `apps/ethos/frontend/src/lib/export/schema.md`
- o usuário escolhe período, hábitos e quais informações aparecem (observação, recompensa, punição etc.)
- o período máximo de um relatório é 5 anos
- sem link público por enquanto
- sem relatório periódico por email por enquanto

### limites (variáveis de ambiente)
- `MAX_HABITS_PER_USER=10` (ativos + pausados)
- `MAX_MARKS_PER_DAY=999`
- `MAX_NOTE_LENGTH=140`
- `MAX_GUESTS_PER_HABIT=5` (membros + convites pendentes)
- `MAX_SHARED_HABITS_PER_USER=20` (hábitos de outras pessoas dos quais o usuário participa)
- `MAX_INVITES_PER_DAY=20` (convites enviados por dono, somando todos os hábitos)

### tamanhos e formatos (fixos no código, validados no back e no front)
- nome do hábito: 1 a 60 caracteres
- descrição: até 500
- recompensa e punição: até 140 cada
- sigla: 1 a 4 caracteres, só letras e números, salva em maiúsculas
- banner: até 280 caracteres por idioma
- email: até 254 caracteres
- cor do hábito: uma das 12 cores de uma paleta fixa, testadas para contraste nos temas claro e escuro. no banco fica o nome da cor (ex.: `teal`), não o hex
- paginação de listas (histórico, admin): 50 itens por página por padrão, máximo 200

### retenção de dados
- eventos de auth, sessões, códigos e IPs ficam na conta, com os prazos de lá (`conta-plan.md`, "retenção de dados")
- auditoria de marcações e de configuração: enquanto o hábito existir. o ethos não grava IP
- o ethos não tem limpeza agendada: o `ethos-alerts.timer` só roda os alertas

### termos de uso e política de privacidade
- um par só para todas as aplicações, na conta (`/conta/termos` e `/conta/privacidade`, ver `conta-plan.md`), com uma seção do ethos. o rodapé do ethos tem link para as duas páginas
- seção do ethos nos termos: limites de uso do ethos e regras do compartilhamento (o dono controla, apagar o hábito apaga as marcações dos convidados)
- seção do ethos na privacidade: dados guardados (hábitos, marcações, observações, custos, configuração dos alertas), quem vê (membros dos hábitos compartilhados e o administrador do serviço, que tem acesso ao conteúdo dos hábitos), emails que o ethos manda (convite, alerta, hábito apagado e perda de acesso a um hábito)

## migracao de ambiente
- o sistema deve ser desenvolvido de modo que seja possivel migrar de infraestrutura de forma facil e rapida (hospedagem, dominio, banco de dados, etc)
- no monorepo, isso também vale para tirar o ethos do repo: ele só depende de `packages/`, da config em `infra/apps/ethos/` e da conta (`conta-plan.md`). levar o ethos para outro servidor exige levar a conta junto ou trocar o `auth_request` por outro jeito de identificar o usuário

## interface
- a aplicacao deve ser moderna e ter uma interface atrativa e responsiva para ser usada em diferentes tamanhos de tela
- a aplicacao deve ter tema claro e escuro
- a aplicacao deve ter internacionalizacao (eng e ptbr)
- aba principal com vários hábitos no mesmo dia: até 4 pontos coloridos por dia (a sigla, ou o nome, aparece no hover e no foco) e "+N" para o resto
- acessibilidade: WCAG 2.1 AA em todas as telas
- navegadores: as duas últimas versões de Chrome, Edge, Firefox e Safari, e iOS 16+. onde o compartilhamento de arquivo não existir, o relatório é baixado
- stack do front (fixada para todas as telas ficarem iguais):
  - TanStack Query para buscar e atualizar dados
  - CSS Modules, como no site, com os tokens de `packages/tokens`
  - sem biblioteca de componentes
  - ícones do `react-icons`, como no site, em pixels inteiros

## painel de admin
- a aplicacao deve ter um painel de admin somente para mim, onde consigo executar acoes na aplicao e nos usuarios
- contas (listar, bloquear, trocar email, excluir) ficam no painel da conta (`/conta/admin`). aqui, a lista de quem usa o ethos (`app_users`), com email, primeiro acesso e contagens (hábitos, marcações)
- o admin vê o conteúdo dos hábitos de qualquer usuário (configuração, marcações, observações). cada acesso a esse conteúdo grava um evento no `audit_log`, e a política de privacidade avisa que esse acesso existe
- notificações, disparo de avisos globais (banners no app, com texto em pt e em en)
- ~~e-mails diretamente pelo painel admin para grupos específicos de usuários~~: cancelado. o admin não manda email em massa; os únicos emails são os de conta, segurança, convite e alerta
- banner: um ativo por vez. se houver mais de um dentro da janela de datas, aparece o mais recente

## planejamento a longo prazo
- pagamentos
- ads
- tipos de conta: standard, plus, premium
- limitar funcionalidades baseado no plano contratado (tipo de conta)
- celular, notificacoes push e mensagens

## stack
- frontend: react + vite, servido em `manasomali.com/ethos/` (vite `base: '/ethos/'`, react router `basename="/ethos"`). arquivos em `/var/www/ethos/`, fora do `/var/www/html/`: o deploy do site faz `rsync --delete` lá e apagaria o ethos
- backend: python + fastapi, rodando como `app-ethos`. sem auth próprio: o login é da conta, e o usuário chega nos headers `X-User-*` (ver "login" e `conta-plan.md`)
- python: última versão estável, fixada em `apps/ethos/backend/.python-version` e repetida em `infra/apps/ethos/app.conf` (o CI confere se são iguais). o apt do ubuntu não traz a última versão, então quem instala é o `uv` (`uv python install`, binário pronto, sem compilar). o `uv` entra no provision com versão e SHA256 fixos, como o litestream
- banco: o sqlite já provisionado em `/var/lib/sqlite/ethos/app.db` (adicionar `ethos` em `infra/databases.txt`), um banco só para auth e dados do app
- acesso ao banco: sqlalchemy 2 síncrono + alembic com `render_as_batch=True` (o sqlite não altera coluna nem chave estrangeira sem recriar a tabela, e o batch mode faz isso). endpoints `def` (não `async def`), o fastapi roda em threadpool, o que basta para sqlite
- ao abrir cada conexão: `PRAGMA busy_timeout=5000; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON; PRAGMA secure_delete=ON;`. transações de escrita com `BEGIN IMMEDIATE` para evitar "database is locked" no meio da transação
- servidor: `uvicorn --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1`, com `MemoryMax=150M` na unit
- dependências: `uv` + `uv.lock`. lint e testes no CI. na VM, só `uv sync --frozen --no-dev --no-build`: baixa wheels prontas e falha se faltar alguma, em vez de tentar compilar com 1 GB de RAM
- agendador: `ethos-alerts.timer` (systemd, de hora em hora) roda `python -m app.cli run-alerts` como `app-ethos`. não existe outro job agendado por enquanto. `OnFailure=` grava uma linha de erro no journald quando o job falha
- email: o ethos não fala com o SMTP. manda cada email pela conta (`POST /internal/mail`, tipo `notification`), que aplica o teto compartilhado entre as aplicações. envio em `BackgroundTasks`, depois do commit
- emails que o ethos envia (templates em pt e en, no idioma do destinatário):
  - convite para um hábito
  - alerta (meta e custo, num email só)
  - perda de acesso a um hábito (conta do dono excluída)
  - hábito apagado (para os membros)
- os emails de conta (código de login, código de exclusão, conta excluída, troca de email, teto de envio) são da conta
- erros da API: corpo `{"error": "<codigo>", "field": "<campo>" | null}`. os códigos ficam num catálogo em `app/errors.py` e cada um tem tradução nos `translation.json` do front. a API nunca manda mensagem pronta para o usuário
- logs: uma linha por request (método, rota, status, duração), nível `INFO` em produção. nunca IP, email, token, cookie nem os headers `X-User-*`
- dados de desenvolvimento: `python -m app.cli seed` cria usuários e hábitos de exemplo e recusa rodar fora de dev
- monitoramento: um monitor externo gratuito chama `/api/ethos/health` de tempos em tempos e avisa por email se falhar (configurado à mão)
- toda config por variável de ambiente, nada fixo no código (facilita migrar):
  - `DATABASE_PATH`, `APP_URL` (ex.: `https://manasomali.com/ethos`)
  - `CONTA_INTERNAL_URL` (ex.: `http://127.0.0.1:3003`) e `INTERNAL_API_TOKEN` (de `/etc/infra/internal.env`)
  - os limites de "decisões de produto"

### onde cada coisa fica na VM
- código do backend: `/opt/apps/ethos/`, dono `ubuntu` (quem faz deploy), só leitura para o `app-ethos`. o serviço não consegue alterar o próprio código
- frontend: `/var/www/ethos/`, dono `ubuntu`
- credenciais SMTP: só a conta lê `/etc/infra/smtp.env`. o ethos lê `/etc/infra/internal.env` (`0600`, root), com o token da API interna, gerado pelo provision na própria VM
- config não secreta do ethos (`APP_URL`, `CONTA_INTERNAL_URL`, limites): versionada em `infra/apps/ethos/app.env` e instalada em `/etc/infra/apps/ethos.env` (`0644`, root)
- a unit lê os dois arquivos com `EnvironmentFile=`
- unit `app-ethos.service`, `ethos-alerts.service` / `.timer` e os snippets do nginx ficam em `infra/apps/ethos/` e são instalados pelo provision, como root. o workflow do ethos só entrega código

### nginx (`infra/apps/ethos/nginx.conf` → `/etc/nginx/apps.d/ethos.conf`)
```nginx
location = /ethos { return 301 /ethos/; }

location /ethos/ {
        root /var/www;
        try_files $uri /ethos/index.html =404;
}

location /api/ethos/ {
        # quem é o usuário: o nginx pergunta à conta (ver conta-plan.md)
        auth_request /_conta/session;
        auth_request_set $conta_user_id $upstream_http_x_user_id;
        # ... idem para email, locale, timezone e admin
        proxy_set_header X-User-Id $conta_user_id;
        proxy_pass http://127.0.0.1:__PORTA__/;
}

location = /api/ethos/health { proxy_pass http://127.0.0.1:__PORTA__/health; }
location /api/ethos/internal/ { return 404; }
```
- `__PORTA__` é trocado pelo provision a partir do `infra/apps/ethos/app.conf`
- o `/health` fica fora do `auth_request`, para o monitor e o deploy não dependerem da conta
- `/api/ethos/internal/` só é usado pela conta direto em `127.0.0.1`, nunca pelo nginx
- o rate limit do login fica na conta (`/api/conta/auth/`). o ethos não tem `nginx-http.conf`
- `index.html` sem cache, arquivos de `assets/` (nome com hash) com cache longo e `immutable`
- headers de segurança em `/ethos/` e `/api/ethos/`:
  - `Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: same-origin`
  - sem `'unsafe-inline'`: o ethos não tem script inline. o tema é aplicado antes da primeira pintura por `/ethos/theme-init.js`, carregado no `<head>` sem `defer`
- o nginx tira o prefixo `/api/ethos`, então as rotas do fastapi ficam em `/habits/...` e o app usa `root_path="/api/ethos"`
- porta do backend: 3001 (`PORT=3001` no `infra/apps/ethos/app.conf`), registrada na tabela do `infra/README.md`

### deploy (`.github/workflows/ethos.yaml`)
roda em PRs (só as checagens) e a cada push na `main` que toca `apps/ethos/**`, `packages/**` ou o próprio workflow, com `concurrency: ethos-deploy` (nunca dois deploys ao mesmo tempo):
1. checagens: `ruff`, `pytest`, `npm ci && npm run lint && npm run build` (dentro de `apps/ethos/`)
2. confere na VM se a unit `app-ethos` já foi instalada pelo provision. se não, falha pedindo para rodar o Infra antes
3. rsync de `apps/ethos/backend/` para `/opt/apps/ethos/` com `--delete`, sem mexer na `.venv`
4. na VM: `uv sync --frozen --no-dev --no-build --compile-bytecode`. o `app-ethos` não consegue gravar `__pycache__` na pasta do código, então o bytecode é gerado aqui
5. backup antes da migração: `sudo -u app-ethos sqlite3 /var/lib/sqlite/ethos/app.db ".backup /var/backups/sqlite/ethos/pre-deploy-<sha>.db"`. o provision cria a pasta com dono `app-ethos` (hoje ela só nasce no primeiro snapshot), e o `snapshot.sh` apaga esses arquivos depois de 7 dias junto com os snapshots
6. `sudo systemctl restart app-ethos`. o `ExecStartPre` roda `alembic upgrade head`; se a migração falhar, o serviço não sobe
7. health check: `curl -fsS "$ETHOS_URL/api/ethos/health"` com 10 tentativas, 3 s entre elas. `ETHOS_URL` é uma variável do GitHub (ex.: `https://manasomali.com`), para trocar de domínio sem mexer no workflow. se falhar, o job falha aqui
8. só então rsync de `apps/ethos/frontend/dist/` para `/var/www/ethos/`, **sem** `--delete`: os arquivos de `assets/` da versão anterior ficam, para quem está com o app aberto não receber 404 ao carregar uma tela. o `index.html` novo substitui o antigo
9. limpeza: apaga de `/var/www/ethos/assets/` os arquivos com mais de 7 dias que não fazem parte da versão atual. assim o frontend novo nunca fica no ar com o backend velho e as abas abertas continuam funcionando

- secrets do workflow: os mesmos do site, no mesmo repo (`REMOTE_HOST`, `REMOTE_USER`, `SERVER_SSH_KEY`, `SSH_KNOWN_HOSTS`). variável: `ETHOS_URL`
- migrações só aditivas (criar tabela ou coluna; remover só num deploy seguinte), para o código anterior continuar funcionando com o banco novo
- rollback: rodar o workflow de novo (`workflow_dispatch`) apontando para o commit anterior. se uma migração estragou dados, restaurar o `pre-deploy-<sha>.db` seguindo o `infra/RESTORE.md`
- `GET /health`: responde 200 se o banco responde a `SELECT 1`
- a conta precisa estar no ar antes do primeiro deploy do ethos: sem ela, o `auth_request` faz toda a API responder 500 (menos o `/health`)

### estrutura do ethos no monorepo
```
.github/workflows/ethos.yaml
infra/apps/ethos/
  app.conf             # PORT=3001, PYTHON_VERSION
  app.env              # APP_URL, CONTA_INTERNAL_URL, limites (sem segredos)
  app-ethos.service
  ethos-alerts.service
  ethos-alerts.timer
  nginx.conf           # /ethos/ e /api/ethos/ com auth_request (dentro do server)
apps/ethos/
  README.md
  backend/
    .python-version
    pyproject.toml
    uv.lock
    alembic.ini
    alembic/versions/
    app/
      main.py          # FastAPI(root_path="/api/ethos"), inclui os routers, GET /health
      config.py        # settings e limites lidos do ambiente
      db.py            # engine, PRAGMAs, sessão por request
      models.py
      audit.py         # grava eventos na tabela audit_log
      errors.py        # catálogo de códigos de erro da API
      cli.py           # run-alerts, seed
      identity.py      # lê os headers X-User-*, mantém app_users, require_user, require_admin, checagem de Origin
      conta_client.py  # API interna da conta: envio de email e busca de usuário por email
      mail.py          # templates dos emails do ethos (convite, alerta, avisos)
      internal/
        router.py      # /internal/users/{id}/delete e /refresh, chamados pela conta
      habits/
        router.py      # hábitos, marcações, membros e convites
        service.py
        score.py       # pontuação e checagem de meta (tela e alertas)
      alerts/
        service.py     # avaliação e envio dos alertas
      admin/
        router.py      # quem usa o ethos, conteúdo dos hábitos, banners
    tests/
  frontend/
    package.json       # independente do package.json do site
    vite.config.js     # base: '/ethos/', importa packages/tokens
    public/locales/{pt,en}/translation.json
    src/
    e2e/               # playwright
```

### dados do app: tabelas
- `app_users`: user_id (id da conta, chave primária), email, locale, timezone, first_seen_at, updated_at. `owner_id`, `user_id` e `created_by` das outras tabelas apontam para cá
- `habits`: id, owner_id, name, code (sigla), description, color (nome da cor da paleta), goal_type (`min` | `max` | `exact`), goal_count, goal_period (`week` | `month` | `year`), multi_mark, duration_enabled, duration_minutes, notes_enabled, score_enabled, score_threshold, reward, punishment, cost_enabled, cost_level (`habit` | `mark`), cost_cents, cost_limit_cents, cost_limit_period, status (`active` | `paused` | `archived`), archived_at, created_at, updated_at
- `habit_pauses`: habit_id, started_at, ended_at. diz quais períodos a pontuação ignora
- `habit_members`: habit_id, user_id, role (`viewer` | `editor`), joined_at
- `habit_invites`: id, habit_id, email, invited_user_id (id da conta, vazio se o email não tinha conta no convite; sem chave estrangeira, porque o convidado pode nunca ter aberto o ethos), role, created_at
- `marks`: id, habit_id, user_id (autor), marked_at (UTC), duration_minutes, cost_cents (custo gravado na criação), note, created_at, updated_at
- `alerts`: habit_id, user_id, goal_enabled, cost_enabled, hour, frequency (`daily` | `weekly`), weekday, last_sent_at
- `banners`: id, text_pt, text_en, starts_at, ends_at, created_by
- `audit_log`: id, user_id, event, created_at, details (json). auditoria das marcações e da configuração, sem IP (os eventos de login ficam na conta)

### hábitos: endpoints além de marcar
- CRUD de hábitos, pausar/retomar, arquivar/desarquivar
- `GET /habits/progress?from&to&habit_ids`: valor de cada período, meta cumprida, pontuação, sucesso/falha e gasto, calculados pelo `score.py`. intervalo máximo de 5 anos
- membros e convites: convidar, cancelar, aceitar, recusar, sair, trocar papel, remover
- histórico: `GET /history` com filtros (hábito, autor, evento, período) e paginação por cursor
- alertas: ler e salvar a configuração do dono ou do editor no hábito (visualização recebe 403)
- `GET /banners/active`: o banner ativo, sem login
- `GET /me`: o usuário (dos headers) e os convites pendentes
- API interna, chamada pela conta: `POST /internal/users/{id}/delete` e `POST /internal/users/{id}/refresh` (ver `conta-plan.md`)
### marcar e desmarcar
- hábito "toggle": `POST /habits/{id}/toggle` recebe o início e o fim do dia de quem clicou (em UTC). o intervalo tem entre 23 h e 25 h (dias com mudança de horário de verão), senão é recusado. numa transação `BEGIN IMMEDIATE`: se já existe marcação nesse intervalo, apaga todas; senão, cria uma. isso resolve clique duplo e dois membros clicando ao mesmo tempo
- hábito com várias marcações por dia: `POST /habits/{id}/marks`. o limite `MAX_MARKS_PER_DAY` é checado no dia de quem marcou, na mesma transação da inserção
- toda marcação e desmarcação grava no `audit_log` quem fez, quando e o que mudou

### login
o ethos não tem auth próprio. login, sessão, cookie, termos, tela de conta, troca de email e o teto de envio de email ficam na conta (`conta-plan.md`). o ethos:
- lê o usuário dos headers `X-User-*` que o nginx põe a partir da conta, e responde 401 sem `X-User-Id` em toda rota que exige login
- cria ou atualiza a linha em `app_users` a cada request com login (só grava quando algo mudou)
- confere o `X-User-Admin` no `require_admin`
- recusa POST/PUT/PATCH/DELETE cujo header `Origin` não seja a origem do `APP_URL` (esquema + host, ex.: `https://manasomali.com`). o `Origin` nunca traz o caminho, então comparar com o `APP_URL` inteiro recusaria tudo
- no 401, o front manda para `/conta/entrar?next=<caminho atual>`
- confere o token da API interna (`INTERNAL_API_TOKEN`, com `hmac.compare_digest`) em `/internal/*`

### exclusão de conta e dados
a exclusão de conta é pedida e coordenada pela conta (`conta-plan.md`, "exclusão de conta"): pela própria pessoa, com código por email, ou pelo admin. o ethos apaga a parte dele em `POST /internal/users/{id}/delete`, chamado pela conta.

o que é apagado:
- os hábitos dos quais a pessoa é dona, com todas as marcações deles, inclusive as feitas por convidados. os convidados perdem o acesso e recebem um email avisando
- os convites pendentes enviados e recebidos pela pessoa, e a participação dela em hábitos de outras pessoas (`habit_members`)
- os alertas dela
- as linhas do `audit_log` que se referem aos hábitos que foram apagados
- a linha em `app_users`

o que fica, sem identificar a pessoa:
- marcações que ela fez em hábitos de outras pessoas continuam lá, porque fazem parte do histórico do hábito. o autor vira `NULL` e a tela mostra "usuário removido"
- linhas do `audit_log` sobre hábitos de outras pessoas: `user_id` vira `NULL` e o `details` perde qualquer email

como é feito:
- tudo numa transação só, `BEGIN IMMEDIATE`. ou apaga tudo ou nada
- as chaves estrangeiras definem o comportamento no próprio banco: `ON DELETE CASCADE` de `app_users` para o que é da pessoa e `ON DELETE SET NULL` para autoria em dados de outras pessoas (`marks.user_id`, `audit_log.user_id`). funciona porque a conexão já usa `PRAGMA foreign_keys=ON`. as tabelas precisam nascer com essas regras desde a primeira migração
- `PRAGMA secure_delete=ON` faz o sqlite sobrescrever com zeros as páginas apagadas em vez de só marcá-las como livres no arquivo
- os ids dos convidados afetados são lidos antes de apagar, e os avisos ("você perdeu acesso a este hábito") vão pela conta depois do commit. não antes, para não avisar de uma exclusão que falhou
- idempotente: chamar de novo, ou para um id que o ethos não conhece, responde 200. é o que permite à conta repetir a chamada quando ela falha e depois de um restore
- backups, prazo de até 8 dias e reaplicação das exclusões depois de um restore: ver `conta-plan.md`

## riscos aceitos
- os riscos do login (código no chute, admin sem segundo fator, conta como ponto único de falha, exclusão não atômica entre os bancos, reaplicação de exclusões dependente do journald) estão no `conta-plan.md`
- cota do Object Storage: o `infra/config.env` estima ~45 mil requests por mês para um banco com escrita contínua (`LITESTREAM_SYNC_INTERVAL=1m`), perto das ~50 mil do Always Free. o `exemplo` sai do `databases.txt` quando o ethos entra, mas a conta e o engrafi trazem mais dois bancos. depois do go-live, medir o uso; se passar de 80% da cota, subir o intervalo
- emails enviados por `BackgroundTasks` (alertas, avisos de exclusão, convites) se perdem se o serviço reiniciar antes de chamar a conta
- teto de email compartilhado: os alertas do ethos disputam o teto com as outras aplicações. um alerta recusado tenta de novo na hora seguinte
- LGPD ignorada por enquanto, mesmo que alguns hábitos (fumo, apostas, saúde) possam ser dados sensíveis
- hábito compartilhado entre fusos muito distantes pode mostrar uma marcação no dia vizinho
