# Infra da VM

Provisionamento da VM Oracle (site estático + bancos SQLite por projeto), aplicado pelo workflow **Infra** a cada push em `infra/**`.

- [PLANO.md](PLANO.md): decisões, arquitetura e histórico da implementação
- [RESTORE.md](RESTORE.md): como restaurar um banco ou recriar a VM

## Usar num projeto novo

1. **Criar o banco:** adicione o nome do projeto em [databases.txt](databases.txt) e faça o merge. O usuário `app-<nome>`, a pasta, o banco `/var/lib/sqlite/<nome>/app.db` e o backup são criados sozinhos.
2. **Conectar o backend:** no código da aplicação (`apps/<nome>/`, ver [apps/README.md](../apps/README.md)), o backend usa `DATABASE_PATH=/var/lib/sqlite/<nome>/app.db`.
   - Use como base os modelos [app.service.tmpl](templates/app.service.tmpl) (unit systemd) e [app-nginx.conf.tmpl](templates/app-nginx.conf.tmpl) (rota `/api/<nome>/`), com uma porta diferente por projeto (registre na tabela abaixo).
   - Faça o build no CI, nunca na VM: com 1 GB de RAM, `npm install` ou compilação na VM pode estourar a memória.
   - Backend em Python: a versão exata vai em `PYTHON_VERSION` no `infra/apps/<nome>/app.conf`, igual ao `apps/<nome>/backend/.python-version` (o CI confere). O provision instala esse Python já compilado, com o `uv`, em `/opt/uv/python`.
   - Ao abrir a conexão, aplique `PRAGMA busy_timeout=5000; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;`. O modo WAL já vem ativado no arquivo.
3. **Remover um banco:** tire a linha do [databases.txt](databases.txt). O provision não apaga os dados, só avisa no log (`<pasta> não está em databases.txt: dados mantidos, mas SEM backup`) a cada execução. Foi assim que o `exemplo`, banco de teste do pipeline de backup, saiu quando o ethos entrou.

## Portas em uso

| Projeto | Porta | Rota |
|---|---|---|
| ethos | 3001 | `/api/ethos/` |
| imago | 3003 | `/api/imago/` |

## Conta única (imago) e API interna

O imago (`infra/apps/imago/`, plano em [imago-plan.md](../imago-plan.md)) é o login de todas as aplicações (o ethos ainda tem o login próprio em `/api/ethos/auth/` até a passagem das contas para o imago, na ETH-64). O nginx de cada aplicação pergunta a ele quem é o usuário (`auth_request` em `/_imago/session`, um `location` interno do `infra/apps/imago/nginx.conf`) e repassa a resposta nos headers `X-User-*`. Toda `location` que chega ao backend de uma aplicação define os cinco headers (`X-User-Id`, `X-User-Email`, `X-User-Locale`, `X-User-Timezone` e `X-User-Admin`): a partir do imago ou vazios (o `/health`), para nenhum mandado pelo navegador chegar ao backend. O modelo está em [.github/scripts/nginx-auth/teste.conf](../.github/scripts/nginx-auth/teste.conf), testado no CI pelo `test-nginx-auth.sh`. Parado, o imago derruba a API de todas as aplicações (500), menos o `/health` delas.

O imago e as aplicações também conversam direto, em `127.0.0.1:<porta>/internal/*` (o nginx responde 404 para `/api/<nome>/internal/`), com um token por aplicação que o provision gera na própria VM. Os tokens nunca passam pelo GitHub, nunca saem da VM e nunca são impressos:

| Arquivo (0600, root) | Conteúdo | Lido por |
|---|---|---|
| `/etc/infra/internal/<nome>.env`, para cada pasta de `infra/apps/` menos o imago | `INTERNAL_API_TOKEN=<32 bytes aleatórios em base64url>` | as units da aplicação (`EnvironmentFile=`) |
| `/etc/infra/internal/imago.env` | `IMAGO_APP_TOKENS=<nome>:<token>,...`, em ordem alfabética | as units do imago |

- O token de uma aplicação nasce no primeiro provision em que ela aparece e não muda mais: um provision seguinte não mexe no arquivo, e uma aplicação nova ganha o dela sem mudar o das outras.
- O `imago.env` é montado a cada provision a partir desses arquivos. Quando muda (aplicação nova ou que saiu), o `app-imago` reinicia, se estiver rodando. Uma aplicação que sai de `infra/apps/` sai do `imago.env` e o token dela deixa de valer; o arquivo dela fica na VM.
- Para trocar o token de uma aplicação (vazou, por exemplo), apague o arquivo dela e rode o Infra: nasce outro, e a aplicação e o imago reiniciam com ele.
- Uma aplicação nova entra no `IMAGO_APPS` do `infra/apps/imago/app.env` (`<nome>=http://127.0.0.1:<porta>`), com os textos dela no front do imago (`apps.<nome>.*` em `apps/imago/frontend/public/locales/{pt,en}/translation.json`). O `.github/scripts/check-imago-apps.sh` confere as portas, a lista e os textos.
- O imago manda os emails de todas as aplicações (o ethos ainda manda os dele até a passagem do login para o imago, na ETH-64). Uma mudança nas credenciais SMTP reinicia só os serviços com `EnvironmentFile=/etc/infra/smtp.env`.
- Para desenvolver, [apps/imago/dev/](../apps/imago/dev/README.md) sobe o mesmo nginx em container, com as rotas de produção, na frente dos backends rodando na máquina.
