# Aplicações

Cada aplicação roda ao lado do site estático, na mesma VM, com front em `manasomali.com/<nome>/` e API em `manasomali.com/api/<nome>/`.

## Convenção de uma aplicação `<nome>`

O nome segue a regra do `infra/databases.txt`: `^[a-z][a-z0-9-]{1,26}$`.

| O quê | Onde |
|---|---|
| Código (front e back) | `apps/<nome>/`, com `README.md` explicando como rodar localmente |
| Na VM | código do backend em `/opt/apps/<nome>/` e frontend em `/var/www/<nome>/`, criados pelo provision com dono do usuário de deploy; o `app-<nome>` só lê |
| Config que roda como root na VM | `infra/apps/<nome>/`: `app.conf` (porta e versão do runtime), `app.env` (config não secreta), units systemd e snippets do nginx |
| Units systemd | `infra/apps/<nome>/app-<nome>.service` (serviço principal) e `<nome>-*.service`/`.timer` (jobs). O provision troca `__PORTA__` pelo `PORT` do `app.conf`, liga o serviço e os timers e sobe o serviço se estiver parado. Use `ConditionPathExists` no binário da `.venv`, para a unit ficar parada antes do primeiro deploy, e `OnFailure=infra-unit-failed@%n.service` nos jobs |
| Rotas no nginx | `infra/apps/<nome>/nginx.conf` (locations dentro do server 443, instalado em `/etc/nginx/apps.d/<nome>.conf`) e, se precisar do contexto `http` (`limit_req_zone`), `nginx-http.conf` (em `/etc/nginx/conf.d/<nome>.conf`). `__PORTA__` vira o `PORT` do `app.conf`. Um `add_header` dentro de `location` apaga os do server: repita o HSTS do site |
| Banco SQLite | linha `<nome>` em [infra/databases.txt](../infra/databases.txt) |
| Rotas | front em `/<nome>/`, API em `/api/<nome>/` |
| Workflow | `.github/workflows/<nome>.yaml`, com `paths` em `apps/<nome>/**`, `packages/**` e no próprio workflow. O deploy usa os scripts de [packages/deploy/](../packages/deploy/README.md), com o nome da aplicação como parâmetro |
| Porta do backend | única, registrada na tabela de portas do [infra/README.md](../infra/README.md#portas-em-uso) |
| Login | do imago, a conta única ([imago-plan.md](../imago-plan.md)): a `location /api/<nome>/` usa `auth_request /_imago/session` e repassa os cinco `X-User-*`, e toda location que chega ao backend os define (vazios fora do `auth_request`); modelo em [.github/scripts/nginx-auth/teste.conf](../.github/scripts/nginx-auth/teste.conf). A aplicação entra no `IMAGO_APPS` do `infra/apps/imago/app.env`, com os textos dela no front do imago |
| API interna | só em `127.0.0.1`, com o token da aplicação, que o provision gera em `/etc/infra/internal/<nome>.env` (`EnvironmentFile=` nas units); o nginx responde 404 para `/api/<nome>/internal/`. Ver [infra/README.md](../infra/README.md#conta-única-imago-e-api-interna) |

## Regras

- **Independência:** cada aplicação tem o seu `package.json` e `package-lock.json` (e `pyproject.toml` e `uv.lock`, se tiver back em Python). Sem npm workspaces.
- **Dependências entre áreas:** uma aplicação não importa código do site nem de outra aplicação. O que for compartilhado vai para `packages/`.
- **Build:** sempre no CI. A VM tem 1 GB de RAM e não roda `npm install` nem compilação.
- **Ordem dos PRs:** mudança de infra de que a aplicação depende (unit nova, variável nova, porta) entra num PR anterior ao da aplicação. O deploy da aplicação confere se a unit existe e falha com mensagem clara se não existir.
- **Concorrência:** o workflow da aplicação não usa o grupo de concorrência `infra`. O GitHub mantém só um run pendente por grupo e cancelaria um deploy que estivesse na fila atrás de um provision.

Tirar a pasta `infra/apps/<nome>/` do repo desliga as units da aplicação e tira as rotas dela do nginx no próximo provision. Código, frontend e banco ficam na VM.
