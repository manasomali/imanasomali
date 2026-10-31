# engrafi

## estrutura
- segunda aplicação hospedada pelo `manasomali.com`, ao lado do ethos, seguindo a mesma convenção do monorepo (`apps/README.md` e a seção "monorepo" do `ethos-plan.md`)
- acessada por `manasomali.com/engrafi/` (api em `manasomali.com/api/engrafi/`)
- frontend e backend, roteados pelo nginx
- banco sqlite próprio: linha `engrafi` em `infra/databases.txt`, arquivo `/var/lib/sqlite/engrafi/app.db`
- porta do backend: 3002, registrada na tabela do `infra/README.md`
- login pelo imago, a conta única do `manasomali.com` (`/imago/`, ver "imago"), a mesma do ethos. o engrafi não tem auth próprio
- não importa código do site nem do ethos. o que for comum vai para `packages/`

## nome do projeto
engrafi (do grego *engráphō*, "inscrever, registrar": o app é o registro do que foi assistido).

### sub titulo
diário de filmes e séries assistidos

## proposta base
o engrafi substitui a planilha "Filmes Com Noiva" (Google Sheets), usada desde 2016 por duas pessoas para registrar o que assistem juntas. a planilha tem:
- **Tabelas**: três listas lado a lado
  - cinema: data e filme (158 linhas, de 23/07/2016 a 18/09/2026)
  - casa: data, filme e "dormiu" (S/N) (645 linhas, de 21/04/2018 a 16/10/2026)
  - séries: nome, status e "quem achou?" (112 linhas, sem data)
- **Oscars**: uma coluna por cerimônia (2023 a 2026). 23 categorias, cada uma com os indicados e a data em que o filme foi visto (vazia se não foi). conta os vistos por categoria (`COUNTIF` das datas) e soma as categorias no total do ano (47, 53, 58 e 83 de 120 indicações)
- **dados**: dia da semana, mês e ano de cada linha, e as contagens que alimentam os gráficos
- **gráficos**: sessões por dia da semana, por mês e por ano (cinema × casa), linha do tempo de cinema e de casa, e pizzas de "dormiu", status das séries e "quem achou"

o app deve fazer o mesmo, sem os problemas de uma planilha, e permitir que outras pessoas usem com os seus próprios diários.

### o que a planilha mostra
- mais de um filme no mesmo dia: até 3 em casa e 2 no cinema
- filme visto de novo: "Soul" duas vezes em 4 dias, "Nasce uma Estrela" no cinema (2018) e em casa (2020)
- o mesmo nome, provavelmente para obras diferentes: "Ballerina" visto em 2019 e em 2025, "Enola Holmes" em 2020 e em 2022 (ano da continuação)
- a mesma obra com nomes diferentes ou com erro: "Parasite" e "Parasita", "Frankstein" na aba de filmes e "Frankenstein" na aba do Oscar
- os indicados ao Oscar são digitados à mão, e a data de cada um é copiada da aba de filmes.

## detalhes e regras
- tudo acontece dentro de um "diário", compartilhado entre os membros. a planilha é um diário de duas pessoas
- o diário registra "sessões": um filme assistido num dia, no cinema ou em casa
- o diário tem uma lista de "séries", cada uma com um status
- o diário tem uma lista "quero ver", que também mostra os indicados ao Oscar que faltam ver
- a aba do Oscar mostra, para cada edição, quais indicados o diário já viu, calculado a partir das sessões. ninguém marca indicado à mão
- a tela de estatísticas refaz os gráficos da planilha, sempre calculados na hora
- a retrospectiva do ano vira uma imagem para compartilhar nas redes sociais
- as datas são só o dia, sem hora e sem fuso: a data informada é a mesma para todos os membros
- o login é o imago, a conta única do `manasomali.com`, a mesma de todas as aplicações
- a planilha pode ser importada, com a limpeza de eventuais  problemas
- os dados podem ser exportados em CSV e JSON

## decisões de produto

itens marcados com **(novo)** não existem na planilha.

### datas
- toda data do diário é só o dia (`aaaa-mm-dd`), sem hora, minuto, segundo nem fuso: a data da sessão, o início e a troca de status da série, a inclusão no "quero ver" e a data da cerimônia do Oscar
- a data informada é fixa: o banco guarda o dia como veio, e todos os membros veem a mesma data, em qualquer fuso
- o formulário sugere a data de hoje do navegador, e a pessoa pode trocar. o front manda a data pronta e o backend grava como veio
- o backend recusa data antes de 1900-01-01 e data depois de hoje no fuso mais adiantado do mundo (UTC+14). assim aceita o "hoje" de qualquer pessoa sem precisar saber o fuso dela
- editar a data de uma sessão grava a nova data, com a mesma validação
- quando uma regra fala em "dia" (limite de sessões por dia, aviso de sessão repetida no mesmo dia), é a data da sessão
- agrupamentos por ano, mês e dia da semana (estatísticas e retrospectiva) saem da data, e o resultado é igual para todos os membros
- o engrafi não usa fuso: ignora o header `X-User-Timezone` do imago e não guarda fuso
- os carimbos técnicos (`created_at`, `updated_at` e a auditoria) continuam como instante em UTC. servem para ordenar registros do mesmo dia, para o histórico e para a saída automática do "quero ver", nunca como data do diário. a tela de histórico mostra o horário deles no relógio do navegador

### diário e membros
- o usuário pode ser dono de mais de um diário (ex.: "com a noiva", "sozinho", "com os amigos"), até `MAX_DIARIES_PER_USER`
- no primeiro acesso o app oferece criar um diário (e importar um CSV nele) ou aceitar um convite pendente
- papéis, como no ethos:
  - dono: único que edita o nome do diário, convida, remove membros, importa e apaga o diário
  - edição: cria, edita e apaga sessões, séries, itens do "quero ver" e obras do diário, inclusive os de outras pessoas
  - visualização: só vê (inclusive o histórico) e exporta
- convites seguem as regras do ethos: só para email que já tem conta no `manasomali.com`, resposta sempre "convite enviado", não expira, o dono pode cancelar, o convidado aceita ou recusa no app e recebe um email avisando. o convidado pode sair, e o dono pode removê-lo
- cada membro aparece pelo email, que é único: é o que os outros membros veem na lista de membros e na autoria. não há apelido nem nome de exibição. quem saiu do diário continua aparecendo pelo email nos registros que criou; quem excluiu a conta aparece como "usuário removido"
- toda sessão é do diário inteiro: o app não registra quem estava presente nem quem dormiu. cada registro guarda quem o criou (`created_by`) só para a auditoria
- o diário compartilhado conta só no limite do dono. cada usuário participa de no máximo `MAX_SHARED_DIARIES_PER_USER` diários de outras pessoas
- o dono convida no máximo `MAX_INVITES_PER_DAY` pessoas por dia, somando todos os diários
- apagar o diário apaga sessões, séries, itens do "quero ver", obras do diário e a auditoria dele, e manda um email aos membros

### obras (catálogo)
- obra é um filme ou uma série: tipo (`movie` | `series`), título e, opcionalmente, ano de lançamento
- duas origens:
  - **globais**: o catálogo geral, com qualquer filme ou série, mantido pelo admin (adiciona, edita, exclui e une títulos). título em pt e, opcionalmente, em en (a tela mostra o do idioma de quem vê). inclui as obras dos indicados ao Oscar. todos os diários veem **(novo)**
  - **do diário**: criadas por membros ao registrar algo que não está no catálogo global. só o próprio diário vê. texto digitado por um usuário nunca aparece para outro diário
- ao digitar o título, a busca mostra primeiro as obras globais e depois as do diário, comparando o título normalizado (minúsculas, sem acento, pontuação vira espaço, espaços colapsados: "Past.Lives" vira "past lives"). obra nova só é criada se o usuário escolher "criar"
- ao criar, o app avisa se já existe obra do mesmo tipo com o mesmo título normalizado (e o mesmo ano, quando os dois têm ano), mas deixa criar: obras diferentes podem ter o mesmo nome
- gestão das obras do diário **(novo)**: dono e editor renomeiam, mudam o ano e o tipo, e apagam, numa tela com a lista de obras do diário e quantas sessões, séries e itens do "quero ver" usam cada uma
  - renomear vale para todos os registros que usam a obra, com o mesmo aviso de duplicata da criação
  - mudar o tipo (filme ↔ série) é permitido mesmo com a obra em uso: o que já está ligado a ela continua ligado. a regra de tipo (sessão só de filme, série só de série) é conferida só ao criar um registro ou trocar a obra dele
  - apagar só vale para obra sem uso. com a obra em uso, a resposta diz quantos registros a usam, e a pessoa troca a obra deles ou apaga esses registros antes
  - cada mudança vai para a auditoria
- cada diário tem no máximo `MAX_TITLES_PER_DIARY` obras próprias, conferido na mesma transação que cria a obra (inclusive na importação). é só um teto de segurança, muito acima do uso normal
- usuários não criam nem editam obras globais
- o Oscar só reconhece a obra global. para um indicado contar, quem registra escolhe a obra com o título como está no cadastro do Oscar (a busca mostra as globais primeiro). uma obra do diário com outro nome ("Duna 2", "Poor Things") não conta, e o app não liga uma à outra sozinho

### sessões (filmes)
- sessão = data, obra (do tipo filme), local, "dormiu", observação opcional
- local: cinema ou casa (`cinema` | `home`)
- a data é só o dia, fixa (ver "datas")
- datas aceitas: de 1900-01-01 até hoje. o formulário sugere o hoje do navegador
- o formulário de registro rápido fica no topo da tela de filmes, como a linha de entrada da planilha: data (hoje por padrão), obra, local e "dormiu"
- as listas ordenam pela data da sessão e, no mesmo dia, pela ordem de criação. registrar fora de ordem é normal e o app reordena sozinho
- a mesma obra pode ter várias sessões (filme visto de novo). nas estatísticas, cada sessão conta. "filmes diferentes" conta cada obra uma vez
- mesma obra, mesmo dia e mesmo local de uma sessão existente: o app pede confirmação (provável clique duplo), mas aceita
- "dormiu": sim ou não, padrão não
- dono e editor editam qualquer campo e apagam qualquer sessão. trocar a obra de uma sessão é como se corrige um título digitado errado
- registrar uma sessão de um filme que está no "quero ver" tira o filme da lista (ver "quero ver")
- sem nota nem avaliação por enquanto (ver "planejamento a longo prazo")

### séries
- item da lista de séries do diário: obra (do tipo série), status e observação (opcional)
- cada série aparece uma vez por diário. não há registro de episódio nem de temporada: temporadas ou edições que o diário quer contar separado são obras diferentes, como na planilha ("BBB 2019", "BBB 2020", "Masterchef 2016")
- status (`watching` | `finished` | `dropped` | `cancelled`):
  - acompanhando: o diário está assistindo ou esperando episódios novos
  - finalizada: o diário viu tudo
  - largada: o diário desistiu
  - cancelada: a série acabou antes do fim (cancelada pelo canal)
- qualquer status pode ir para qualquer outro. cada troca vai para a auditoria (quem, quando, de qual para qual)
- datas **(novo)**: `started_on` (início, hoje por padrão, editável) e `status_changed_on` (data da troca de status, hoje por padrão, editável na troca). séries importadas sem essas datas ficam sem elas, e a tela mostra "sem data"
- "quem achou" pode ser adicionado no campo "observação"
- incluir na lista uma série que está no "quero ver" tira a série de lá

### quero ver **(novo)**
- lista de obras (filmes e séries) que o diário quer assistir. item = obra, observação opcional, quem incluiu e a data de inclusão (`added_on`, hoje por padrão)
- cada obra aparece uma vez na lista do diário
- a lista ordena pela data de inclusão, mais recente primeiro, com filtro por tipo
- incluir um filme que o diário já viu é permitido (para ver de novo). o app avisa "vocês já viram em <data>"
- saída automática: uma sessão do filme criada depois da inclusão (mesmo com data no passado) tira o item da lista, e incluir a série na lista de séries tira a série. o app avisa ("removido do quero ver"). apagar essa sessão depois não devolve o item. trocar a obra de uma sessão que já existe não tira nada da lista: só a criação de sessão tira
- cada filme indicado ao Oscar mostra na lista a edição mais recente em que foi indicado e quantas indicações teve (ex.: "Oscar 2026 · 6 indicações")
- dono e editor incluem e tiram itens. visualização só vê
- até `MAX_WATCHLIST_PER_DIARY` itens

### oscar
- edição = ano da cerimônia e a data dela, cadastrados pelo admin e iguais para todos os diários
- as categorias são de cada edição, com nome em pt e en e uma ordem. a planilha usa 23 categorias, na mesma ordem nas 4 edições, mas a Academia muda a lista com o tempo (a categoria de elenco, criada para a cerimônia de 2026, não está na planilha). o admin pode copiar as categorias da edição anterior
- indicado = obra global do tipo filme + crédito opcional (pessoa ou canção). nas categorias de filme o crédito fica vazio. a planilha escreve isso de três jeitos ("Nome (Filme)", "Nome por “Filme”", "Nome, 'Filme'"); o app separa crédito e obra
- o número de indicados varia (5 na maioria, até 10 em melhor filme) e não é fixo no código
- vencedor **(novo)**: o admin marca o vencedor de cada categoria depois da cerimônia. em caso de empate, mais de um
- **visto**: um indicado conta como visto no diário quando o diário tem pelo menos uma sessão da obra, em qualquer data, antes ou depois da cerimônia. não existe marcação manual: registrar a sessão já atualiza o Oscar, e apagá-la desfaz
- a data mostrada é a da primeira sessão da obra no diário. se essa data é posterior à data da cerimônia, aparece um indicador "depois da cerimônia" (no próprio dia da cerimônia, não aparece)
- contagens:
  - por categoria: indicados vistos / indicados, como o `COUNTIF` da planilha
  - total da edição: soma das categorias, ou seja, conta indicações. um filme indicado em 6 categorias conta 6 vezes (é o "83 de 120" da planilha)
  - também mostra "filmes vistos / filmes indicados", contando cada filme uma vez **(novo)**
- **faltam ver** **(novo)**: cada edição mostra os filmes indicados que o diário ainda não viu, ordenados pelo número de indicações (maior primeiro) e depois pelo título, com as categorias de cada um. ver primeiro os mais indicados é o que mais sobe a contagem
  - cada filme tem um botão "quero ver", e a edição tem "incluir todos os que faltam", que pula os que já estão na lista
  - dono e editor incluem. visualização só vê a lista
- calculado na hora a partir das sessões, nunca gravado

### estatísticas
- tudo calculado na hora a partir das sessões e das séries, nunca gravado. a planilha mostra por que: as contagens e as imagens dos gráficos ficaram desatualizadas
- agrupadas pela data das sessões, iguais para todos os membros (ver "datas")
- filtros: período (de/até, padrão tudo) e local (cinema, casa ou os dois)
- gráficos, os da planilha menos o de "quem achou" (que agora é texto livre na observação da série):
  - sessões por ano, cinema × casa
  - sessões por mês do ano (jan a dez, somando todos os anos do período), cinema × casa
  - sessões por dia da semana, de segunda a domingo (ISO, como no ethos), cinema × casa. a planilha usa o `WEEKDAY` com domingo = 1 e reordena para começar na segunda
  - linha do tempo acumulada (total de sessões ao longo do tempo), cinema e casa
  - "dormiu": porcentagem de sessões com sim
  - séries por status
- números do topo: sessões, filmes diferentes, filmes vistos mais de uma vez, sessões no cinema e em casa
- as listas de filmes agrupam por ano, com o ano no cabeçalho (a planilha pinta cada ano de uma cor)

### retrospectiva do ano **(novo)**
- imagem do ano de um diário para postar em redes sociais, gerada no navegador como o relatório do ethos
- 1080×1350 (retrato), desenhada em `<canvas>` sem lib, com a fonte do app já carregada (`document.fonts.ready`). compartilhada pela Web Share API (`navigator.share` com arquivo); onde não houver suporte, baixa o PNG
- o usuário escolhe o ano (só anos com sessões). o ano atual aparece como "até agora". o ano é o da data das sessões
- blocos, cada um pode ser ligado ou desligado antes de gerar (todos ligados por padrão):
  - nome do diário e ano
  - total de sessões, cinema × casa
  - filmes diferentes e filmes vistos mais de uma vez
  - filme mais visto do ano (só se algum foi visto mais de uma vez)
  - mês e dia da semana com mais sessões
  - primeiro e último filme do ano
  - quantas vezes alguém dormiu
  - séries começadas e finalizadas no ano (pelo `started_on` e pelo `status_changed_on` com status finalizada; séries sem data não entram). a contagem usa só a última troca de status: uma série finalizada e reaberta depois não conta no ano em que foi finalizada (limitação aceita)
  - Oscar da edição daquele ano: indicações vistas / indicações (só se a edição existe)
- bloco sem dado no ano (ex.: nenhuma série) não aparece. títulos longos são cortados com reticências para caber
- a imagem não traz emails, só o que está nos blocos
- textos no idioma de quem gera
- qualquer membro gera, inclusive quem só visualiza
- sem link público

### importação
- o importador aceita só o CSV do próprio engrafi (o mesmo formato do export: ver "export"). não existe conversor da planilha: ela é montada uma vez, à mão, nesse formato (ver "preparar a planilha")
- só o dono importa, e só num diário sem sessões, séries e itens do "quero ver", para não duplicar dados importando duas vezes
- normalização e validação na importação:
  - `strip` em títulos e observações, e quebra de linha no título vira espaço
  - datas no formato `aaaa-mm-dd`, gravadas como vieram e com a mesma validação do formulário. outro formato é erro
  - `date` vira a data da sessão, o início da série ou a data de inclusão no "quero ver"; `status_date` vira a data da troca de status da série
  - o limite de `MAX_SESSIONS_PER_DAY` também vale na importação (a planilha chega a 3 por dia). um dia acima do limite aparece como erro na pré-visualização
  - `place`, `fell_asleep`, `status` e `kind` só aceitam os códigos do export. outro valor é erro
- pré-visualização antes de gravar (nada é gravado até o usuário confirmar):
  - contagens por tipo (sessões de cinema, de casa, séries, itens do "quero ver") e as linhas com erro, com o motivo
  - títulos repetidos: o usuário escolhe se é a mesma obra (vista de novo, o padrão) ou obras diferentes ("Ballerina"). em obras diferentes, a pré-visualização pede o ano de cada uma, para distinguir uma da outra
  - qualquer linha pode ser ignorada (ex.: o "COVID-19 INICIO", que não é filme)
  - títulos iguais (normalizados, do mesmo tipo) a uma obra global são ligados a ela, e o Oscar já sai calculado. a pré-visualização lista essas ligações e o usuário pode desfazer cada uma
- tudo numa transação `BEGIN IMMEDIATE`: importa tudo ou nada
- até `MAX_IMPORT_ROWS` linhas e 5 MB de arquivo (o `client_max_body_size` do nginx). acima disso, erro claro antes de ler o arquivo
- os itens do "quero ver" entram como estão no CSV, sem a saída automática por sessão

#### preparar a planilha
feito uma vez, fora do app, para importar o histórico da planilha "Filmes Com Noiva":
- uma linha por sessão de cinema, sessão de casa e série, nas colunas do export
- datas `dd/mm/aaaa` viram `aaaa-mm-dd`
- "dormiu": `S` vira `true`; `N`, vazio e as sessões de cinema viram `false`
- status sem os espaços sobrando: "Finalizado" → `finished`, "Largado" → `dropped`, "Acompanhando" e "Assistindo" → `watching`, "Cancelada" → `cancelled`
- o "quem achou?" vai para a observação da série ("quem achou: <nome>")
- para o Oscar contar os filmes já vistos, o título tem que ser igual ao do cadastro do Oscar (ver "oscar"). na planilha, só 20 dos 44 indicados vistos em categorias de filme estão com o mesmo nome ("Duna 2", "Poor Things", "Avatar 2" e outros não estão)
- a aba Oscars não é importada: os indicados são cadastrados pelo admin e o "visto" é calculado das sessões
- os arquivos da planilha (`.xlsx`, `.zip`, `.csv`) não entram no repo: ele é público e os arquivos têm nomes de pessoas e o histórico do casal

### export
- gerado no navegador, como no ethos, a partir de um `GET` com todos os dados do diário
- qualquer membro exporta, inclusive quem só visualiza
- CSV: uma linha por sessão, série ou item do "quero ver", com as colunas `type` (`watch` | `series` | `watchlist`), `date` (da sessão, do início da série ou da inclusão no "quero ver"), `title`, `kind`, `year`, `place`, `fell_asleep`, `status`, `status_date`, `note`. colunas que não se aplicam ficam vazias. células que começam com `=`, `+`, `-` ou `@` recebem um `'` na frente
- valores no CSV e no JSON com os códigos do banco: `place` `cinema` | `home`, `fell_asleep` `true` | `false`, `status` `watching` | `finished` | `dropped` | `cancelled`, `kind` `movie` | `series`
- datas no CSV e no JSON como `aaaa-mm-dd`, iguais às do banco
- JSON: `{ "version", "generated_at", "diary": {name}, "watches": [...], "series": [...], "watchlist": [...] }`, com o schema documentado em `apps/engrafi/frontend/src/lib/export/schema.md`
- o CSV exportado volta pelo importador sem perder sessões, séries e itens do "quero ver" (ida e volta). autoria e histórico não vão no CSV
- a imagem para redes sociais é a retrospectiva do ano

### limites (variáveis de ambiente)
- `MAX_DIARIES_PER_USER=5` (diários dos quais é dono)
- `MAX_MEMBERS_PER_DIARY=10` (membros + convites pendentes, sem contar o dono)
- `MAX_SHARED_DIARIES_PER_USER=20` (diários de outras pessoas dos quais participa)
- `MAX_INVITES_PER_DAY=20` (convites enviados por dono, somando todos os diários)
- `MAX_SESSIONS_PER_DAY=10` (por diário; a planilha chega a 3)
- `MAX_SESSIONS_PER_DIARY=20000` (a planilha tem 802 em 10 anos)
- `MAX_SERIES_PER_DIARY=5000`
- `MAX_WATCHLIST_PER_DIARY=2000`
- `MAX_TITLES_PER_DIARY=20000` (obras do diário; teto de segurança, a planilha tem uns 800 títulos em 10 anos)
- `MAX_NOTE_LENGTH=280`
- `MAX_IMPORT_ROWS=5000`

### tamanhos e formatos (fixos no código, validados no back e no front)
- nome do diário: 1 a 60 caracteres
- título da obra: 1 a 200, sem quebra de linha (o maior da planilha tem 53)
- crédito do indicado: até 200 (o maior da planilha tem 87)
- ano da obra: de 1888 até o ano atual + 2
- nome de categoria do Oscar: 1 a 80 por idioma
- banner: até 280 caracteres por idioma
- email do convite: até 254
- paginação de listas (sessões, "quero ver", histórico, admin): 50 por página por padrão, máximo 200
- lista de séries e busca de obras: sem paginação por enquanto

### retenção de dados
- auditoria do diário: enquanto o diário existir. o engrafi não grava IP (eventos de login e IPs ficam no imago)
- o engrafi não tem job agendado: não guarda nada que vença. a limpeza de sessões de login, códigos e eventos de auth roda no imago

### termos de uso e política de privacidade
- um par só para todas as aplicações, no imago (ver "imago"), com uma seção do engrafi
- a seção do engrafi nos termos: o dono controla o diário; apagar o diário apaga o que os membros registraram nele, e o diário também é apagado quando o dono exclui a conta (não há transferência de dono); a retrospectiva é gerada no navegador e só sai do aparelho se a pessoa compartilhar
- a seção do engrafi na privacidade: dados guardados (diários, sessões, séries, "quero ver", observações), quem vê (membros do diário, que também veem o email uns dos outros, e o administrador, que tem acesso ao conteúdo dos diários)

## imago
o login é o imago, a conta única do `manasomali.com`, descrito no `imago-plan.md` e compartilhado com o ethos. para o engrafi, isso quer dizer:
- o engrafi não tem auth, cookie, SMTP nem tela de conta próprios. o imago precisa estar no ar antes dele
- o usuário chega nos headers `X-User-Id`, `X-User-Email`, `X-User-Locale`, `X-User-Timezone` e `X-User-Admin`, que o nginx põe a partir do imago com `auth_request`. o engrafi ignora o `X-User-Timezone` (ver "datas"). sem `X-User-Id`, toda rota que exige login responde 401, e o front manda para `/imago/entrar?next=<caminho atual>`
- a cada request com login, o engrafi cria ou atualiza a linha em `app_users` (só grava quando algo mudou)
- csrf: recusa POST/PUT/PATCH/DELETE cujo header `Origin` não seja a origem do `APP_URL`
- emails saem pelo imago (`POST /internal/mail`, tipo `notification`) e entram no teto compartilhado entre as aplicações. o convidado é buscado por `POST /internal/users/lookup`
- o engrafi expõe `POST /internal/users/{id}/delete` e `POST /internal/users/{id}/refresh`, chamados pelo imago com o `INTERNAL_API_TOKEN` (ver "exclusão de conta e dados")
- para entrar no ar: linha `engrafi=http://127.0.0.1:3002` no `IMAGO_APPS` do imago e seção do engrafi nos termos e na privacidade, o que gera uma versão nova dos termos

## migracao de ambiente
- mesma regra do ethos: toda config por variável de ambiente. o engrafi só depende de `packages/`, de `infra/apps/engrafi/` e do imago (pela API interna e pelos headers do nginx), e pode sair do repo sem desmontar nada. levar o engrafi para outro servidor exige levar o imago junto ou trocar o `auth_request` por outro jeito de identificar o usuário

## interface
- moderna, responsiva, tema claro e escuro, pt e en, WCAG 2.1 AA, mesmos navegadores do ethos
- seletor de diário no topo quando o usuário tem mais de um
- abas do diário:
  - **filmes**: formulário rápido no topo, linha do tempo agrupada por ano, filtros de local e ano, busca por título
  - **séries**: agrupadas por status, com troca de status direto na lista
  - **quero ver**: filmes e séries, com filtro por tipo, indicação do Oscar e atalho para registrar a sessão
  - **oscar**: seletor de edição, categorias com os indicados (visto, data, vencedor), contagem por categoria e total, e "faltam ver"
  - **estatísticas**: os gráficos e números de "estatísticas", e o botão da retrospectiva do ano
  - **diário**: nome, membros, convites, obras do diário (renomear, mudar ano e tipo, apagar), importar, exportar, histórico
- página de ajuda, em pt e en, como a do ethos, com link no menu. explica as regras que não são óbvias: o Oscar só conta sessões da obra global (registrar com o título do cadastro do Oscar), a data fixa (a mesma para todos, em qualquer fuso), a saída automática do "quero ver", o que entra na retrospectiva, como montar um CSV para importar e que a exclusão da conta do dono apaga o diário compartilhado
- sair e excluir conta levam para a tela de conta do imago
- gráficos em SVG gerado pelo próprio código, sem biblioteca de gráficos (mantém o bundle pequeno e a CSP só com `'self'`). cada gráfico tem uma tabela equivalente para leitores de tela
- stack do front igual à do ethos: TanStack Query, CSS Modules com os tokens de `packages/tokens`, sem biblioteca de componentes, ícones do `react-icons` em pixels inteiros

## painel de admin
- contas ficam no painel do imago. aqui, a lista de quem usa o engrafi (`app_users`), com contagens (diários, sessões)
- catálogo global (qualquer filme ou série): adicionar, editar, excluir e unir títulos. uma obra global usada por alguma sessão, série, item do "quero ver" ou indicado não pode ser apagada, só juntada com outra: sessões, séries e itens do "quero ver" de todos os diários, e os indicados do Oscar, passam para a que fica. se um diário acompanha as duas séries, a junção é recusada e o painel mostra quais diários. se um diário tem as duas no "quero ver", fica o item mais antigo
- oscar:
  - criar edição (ano e data da cerimônia), copiar as categorias da edição anterior, criar, renomear, reordenar e apagar categorias
  - cadastrar indicados buscando a obra global ou criando na hora, e marcar vencedores
  - importação de indicados por CSV, para não digitar as 120 indicações de cada ano (ver abaixo)
- importação de indicados (dentro de uma edição):
  - colunas `category`, `title`, `title_en`, `year`, `credit` e `winner`. as quatro últimas são opcionais
  - `category` tem que ser igual (normalizado) ao nome em pt de uma categoria da edição. senão a linha é erro
  - a obra é procurada entre as globais do tipo filme pelo `title` normalizado e, quando a linha e a obra têm ano, pelo ano. sem nenhuma, a obra é criada com `title`, `title_en` e `year`. com mais de uma, a linha é erro pedindo o ano
  - a mesma obra com o mesmo crédito duas vezes na mesma categoria é erro
  - `winner` aceita `true` ou `false` (vazio é `false`)
  - pré-visualização antes de gravar: obras que vão ser criadas, obras encontradas e linhas com erro. uma transação só: grava tudo ou nada
  - substitui os indicados das categorias que aparecem no arquivo, na ordem do arquivo. as categorias que não aparecem ficam como estão. assim dá para importar de novo para corrigir
  - obras globais criadas por uma importação e que ficaram sem uso depois de uma correção podem ser apagadas pelo admin
- conteúdo dos diários: como no ethos, cada acesso grava um evento no `audit_log`
- banners: como no ethos

## planejamento a longo prazo
- integração com um catálogo externo (TMDB): pôster, sinopse, títulos em pt e en e menos obras duplicadas
- nota ou avaliação por membro
- quem estava presente e quem dormiu em cada sessão
- outros prêmios (Globo de Ouro, Cannes) e outros locais (festival, avião, casa de amigos)
- pagamentos, ads e tipos de conta, como no ethos

## stack
igual à do ethos (seção "stack" do `ethos-plan.md`), trocando `ethos` por `engrafi`. as diferenças:
- frontend em `/var/www/engrafi/` (vite `base: '/engrafi/'`, react router `basename="/engrafi"`), backend como `app-engrafi` na porta 3002
- sem auth, cookie e SMTP próprios: tudo vem do imago
- sem job agendado
- emails (templates em pt e en, enviados pelo imago como `notification`): convite para um diário, perda de acesso a um diário (conta do dono excluída), diário apagado (para os membros)
- `APP_URL=https://manasomali.com/engrafi`, `DATABASE_PATH=/var/lib/sqlite/engrafi/app.db`, `IMAGO_INTERNAL_URL` e os limites acima, em `infra/apps/engrafi/app.env`. a unit lê também `/etc/infra/internal.env`
- nginx (`infra/apps/engrafi/nginx.conf`): os mesmos blocos, headers e cache do ethos, com `auth_request` em `/api/engrafi/`, `/api/engrafi/health` fora dele e 404 em `/api/engrafi/internal/`. sem `nginx-http.conf`, porque o engrafi não tem rate limit próprio. o `client_max_body_size 5m` desses blocos é também o tamanho máximo do arquivo de importação
- deploy (`.github/workflows/engrafi.yaml`): os mesmos 9 passos do ethos, com `concurrency: engrafi-deploy`, a variável `ENGRAFI_URL` e a checagem da versão do python (`.github/scripts/check-python-version.sh`)

### estrutura no monorepo
```
.github/workflows/engrafi.yaml
infra/apps/engrafi/
  app.conf               # PORT=3002, PYTHON_VERSION
  app.env                # APP_URL, IMAGO_INTERNAL_URL, limites (sem segredos)
  app-engrafi.service
  nginx.conf             # /engrafi/ e /api/engrafi/ (com auth_request)
apps/engrafi/
  README.md
  backend/
    .python-version
    pyproject.toml
    uv.lock
    alembic.ini
    alembic/versions/
    app/
      main.py            # FastAPI(root_path="/api/engrafi"), routers, GET /health
      config.py
      db.py
      models.py
      audit.py
      errors.py
      cli.py             # seed
      normalize.py       # título normalizado, usado na busca, nas duplicatas e na importação
      identity.py        # lê os headers X-User-*, mantém app_users, require_user, require_admin
      imago_client.py    # chamadas à API interna do imago (email, busca por email)
      internal/          # /internal/users/{id}/delete e /refresh
      diaries/           # diários, membros, convites
      titles/            # catálogo e busca
      watches/           # sessões
      series/
      watchlist/         # quero ver
      oscars/            # progresso e "faltam ver", calculados das sessões
      stats/             # estatísticas e dados da retrospectiva
      imports/           # formato CSV, pré-visualização e importação
      admin/             # app_users, catálogo global, oscar, banners
    tests/
  frontend/
    package.json
    vite.config.js       # base: '/engrafi/', importa packages/tokens
    public/locales/{pt,en}/translation.json
    src/
      lib/retrospective/ # desenho da imagem no canvas
      lib/export/
    e2e/
```

### dados do app: tabelas
- `app_users`: user_id (id do usuário no imago, chave primária), email, locale, first_seen_at, updated_at. sem fuso
- `diaries`: id, name, created_at, updated_at
- `diary_members`: diary_id, user_id, role (`owner` | `editor` | `viewer`), joined_at. o dono também é uma linha, com `owner`. um índice único parcial impede dois `owner` no mesmo diário, e o serviço garante que sempre existe um
- `diary_invites`: id, diary_id, email, invited_user_id (id do usuário no imago, vazio se o email não tinha conta; sem chave estrangeira, porque o convidado pode nunca ter aberto o engrafi), role, created_at
- `titles`: id, diary_id (vazio = global), kind (`movie` | `series`), name, name_en (só global), name_norm, year, created_by, created_at, updated_at. índice em (diary_id, kind, name_norm)
- `watches`: id, diary_id, title_id, watched_on (data), place (`cinema` | `home`), fell_asleep, note, created_by, created_at, updated_at. índice em (diary_id, watched_on)
- `diary_series`: id, diary_id, title_id, status (`watching` | `finished` | `dropped` | `cancelled`), started_on, status_changed_on (datas, podem ser vazias), note, created_by, created_at, updated_at. único em (diary_id, title_id)
- `watchlist_items`: id, diary_id, title_id, added_on (data), note, created_by, created_at. único em (diary_id, title_id)
- `oscar_editions`: id, year (único), ceremony_on (data)
- colunas `_on` são `DATE` (só o dia); colunas `_at` são carimbos técnicos em UTC (ver "datas")
- `oscar_categories`: id, edition_id, name, name_en, position
- `oscar_nominees`: id, category_id, title_id (obra global do tipo filme), credit, is_winner, position
- `banners`: como no ethos
- `audit_log`: id, user_id, diary_id, event, created_at, details (json). sem IP
- `watches` e não `sessions`, para não confundir com as sessões de login do imago
- chaves estrangeiras desde a primeira migração:
  - `ON DELETE CASCADE` do diário para membros, convites, obras do diário, sessões, séries, itens do "quero ver" e linhas do `audit_log`, e de `app_users` para `diary_members`
  - `ON DELETE CASCADE` da edição do Oscar para as categorias, e da categoria para os indicados
  - `ON DELETE SET NULL` de `app_users` para autoria (`created_by`, `audit_log.user_id`)
  - `ON DELETE RESTRICT` de `watches`, `diary_series`, `watchlist_items` e `oscar_nominees` para `titles`: obra em uso não pode ser apagada (o admin junta obras globais)
- regras que o banco não garante e o serviço checa ao criar um registro ou trocar a obra dele: a obra da sessão é filme e é global ou do mesmo diário; a obra da série é série e é global ou do mesmo diário; a obra do "quero ver" é global ou do mesmo diário; a obra do indicado é global e filme. mudar o tipo de uma obra em uso não é bloqueado (ver "obras")

### endpoints (`/api/engrafi/...`)
- `GET /me`: o usuário (dos headers) e os convites pendentes
- diários: CRUD, membros e convites (convidar, cancelar, aceitar, recusar, sair, trocar papel, remover)
- obras: `GET /diaries/{id}/titles?q&kind` (busca: globais primeiro, depois as do diário), `GET /diaries/{id}/titles?scope=diary` (obras do diário, com quantos registros usam cada uma), `POST`, `PATCH` (nome, ano e tipo, só obra do diário), `DELETE` (só obra do diário sem uso; em uso responde 409 com as contagens)
- sessões: `GET /diaries/{id}/watches?from&to&place&q&cursor`, `POST`, `PATCH`, `DELETE`. o limite de `MAX_SESSIONS_PER_DAY` e a saída do "quero ver" acontecem na mesma transação `BEGIN IMMEDIATE` da inserção
- séries: CRUD em `/diaries/{id}/series?status`
- quero ver: `GET /diaries/{id}/watchlist?kind&cursor`, `POST`, `PATCH` (observação), `DELETE`, e `POST /diaries/{id}/watchlist/oscar/{year}` (inclui todos os filmes que faltam da edição)
- oscar: `GET /oscars` (edições), `GET /diaries/{id}/oscars/{year}` (categorias, indicados, visto, data, vencedor, contagens e "faltam ver")
- estatísticas: `GET /diaries/{id}/stats?from&to&place`
- retrospectiva: `GET /diaries/{id}/retrospective?year` (os números de cada bloco)
- importação: `POST /diaries/{id}/import/preview` (recebe o CSV e devolve a análise, sem gravar) e `POST /diaries/{id}/import` (CSV e decisões da pré-visualização)
- export: `GET /diaries/{id}/export`
- histórico: `GET /diaries/{id}/history` com filtros (autor, evento, período) e paginação por cursor. qualquer membro vê, inclusive quem só visualiza
- `GET /banners/active` e `GET /health`, como no ethos
- admin (tudo com `require_admin`, pelo `X-User-Admin`, e gravado no `audit_log`):
  - `GET /admin/users?q&cursor` (quem usa o engrafi, com contagens) e `GET /admin/users/{id}/diaries` (conteúdo dos diários; cada chamada grava `admin_viewed_diaries`)
  - obras globais: `GET /admin/titles?q`, `POST`, `PATCH`, `DELETE` (só sem uso) e `POST /admin/titles/{id}/merge` com `{into}`
  - edições: `POST /admin/oscars`, `PATCH` e `DELETE /admin/oscars/{year}` (apagar a edição apaga as categorias e os indicados dela)
  - categorias: `POST /admin/oscars/{year}/categories/copy` (da edição anterior) e CRUD em `/admin/oscars/{year}/categories`
  - indicados: CRUD em `/admin/oscars/{year}/nominees` (o `PATCH` também marca o vencedor), `POST /admin/oscars/{year}/nominees/import/preview` e `POST /admin/oscars/{year}/nominees/import`
  - banners: `GET`, `POST` e `PATCH /admin/banners`, como no ethos
- API interna: `POST /internal/users/{id}/delete` e `POST /internal/users/{id}/refresh` (ver "imago")
- toda criação, edição e exclusão de sessão, série, item do "quero ver" e obra grava no `audit_log` quem fez, quando e o que mudou

### exclusão de conta e dados
`POST /internal/users/{id}/delete`, chamado pelo imago, segue as regras do ethos trocando hábito por diário:
- apaga os diários dos quais a pessoa é dona, com tudo o que há neles, e avisa os membros por email
- tira a participação dela nos diários de outras pessoas e os convites pendentes enviados e recebidos
- sessões, séries e itens do "quero ver" que ela criou em diários de outras pessoas ficam, com `created_by` vazio ("usuário removido")
- apaga a linha em `app_users`
- uma transação só, `BEGIN IMMEDIATE`, com `PRAGMA secure_delete=ON`. os emails saem depois do commit
- idempotente: chamar de novo, ou para um id que o engrafi não conhece, responde 200

## pontos em aberto
- **catálogo próprio ou TMDB desde o início**: o plano começa com catálogo próprio (sem chave de API, sem dependência externa, aceita "BBB 2023"). o TMDB evitaria duplicatas e daria pôsteres, mas exige chave, atribuição e licença comercial se o app tiver ads ou planos pagos

## riscos aceitos
- os riscos do login (código no chute, admin sem segundo fator, imago como ponto único de falha, exclusão não atômica entre os bancos, teto de email compartilhado) estão no `imago-plan.md`
- emails enviados por `BackgroundTasks` (convites, avisos) se perdem se o serviço reiniciar antes de chamar o imago
- memória: com o imago, o engrafi é o terceiro processo python na VM de 1 GB (cada um com `MemoryMax=150M`), além do nginx e do litestream. medir depois do go-live
- cota do Object Storage: o `engrafi` é mais um banco no Litestream, junto com o `ethos` e o `imago`. escreve pouco, mas a estimativa de ~45 mil requisições por mês do `infra/config.env` é para um banco só. medir depois do go-live; se passar de 80% da cota, subir o `LITESTREAM_SYNC_INTERVAL`
- o Oscar só conta sessões da obra global: um indicado registrado com outro nome ou com erro de digitação fica fora da contagem até alguém trocar a obra das sessões para a global. na planilha, isso deixaria de fora 24 dos 44 indicados vistos em categorias de filme
- mudar o tipo de uma obra do diário em uso deixa sessões ligadas a uma série (ou uma série ligada a um filme). as estatísticas contam essas sessões normalmente
- excluir a conta do dono apaga o diário compartilhado inteiro, com o que os outros membros registraram nele. não há transferência de dono
- dados que a planilha não tem continuam faltando depois da importação: quem estava presente, quem dormiu, datas das séries
- LGPD ignorada por enquanto
