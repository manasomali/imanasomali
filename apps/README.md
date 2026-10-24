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
| Banco SQLite | linha `<nome>` em [infra/databases.txt](../infra/databases.txt) |
| Rotas | front em `/<nome>/`, API em `/api/<nome>/` |
| Workflow | `.github/workflows/<nome>.yaml`, com `paths` em `apps/<nome>/**`, `packages/**` e no próprio workflow |
| Porta do backend | única, registrada na tabela de portas do [infra/README.md](../infra/README.md#portas-em-uso) |

## Regras

- **Independência:** cada aplicação tem o seu `package.json` e `package-lock.json` (e `pyproject.toml` e `uv.lock`, se tiver back em Python). Sem npm workspaces.
- **Dependências entre áreas:** uma aplicação não importa código do site nem de outra aplicação. O que for compartilhado vai para `packages/`.
- **Build:** sempre no CI. A VM tem 1 GB de RAM e não roda `npm install` nem compilação.
- **Ordem dos PRs:** mudança de infra de que a aplicação depende (unit nova, variável nova, porta) entra num PR anterior ao da aplicação. O deploy da aplicação confere se a unit existe e falha com mensagem clara se não existir.
- **Concorrência:** o workflow da aplicação não usa o grupo de concorrência `infra`. O GitHub mantém só um run pendente por grupo e cancelaria um deploy que estivesse na fila atrás de um provision.

Tirar a pasta `infra/apps/<nome>/` do repo desliga as units da aplicação e tira as rotas dela do nginx no próximo provision. Código, frontend e banco ficam na VM.
