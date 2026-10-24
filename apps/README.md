# Aplicações

Cada aplicação roda ao lado do site estático, na mesma VM, com front em `manasomali.com/<nome>/` e API em `manasomali.com/api/<nome>/`.

## Convenção de uma aplicação `<nome>`

O nome segue a regra do `infra/databases.txt`: `^[a-z][a-z0-9-]{1,26}$`.

| O quê | Onde |
|---|---|
| Código (front e back) | `apps/<nome>/`, com `README.md` explicando como rodar localmente |
| Config que roda como root na VM | `infra/apps/<nome>/`: `app.conf` (porta e versão do runtime), `app.env` (config não secreta), units systemd e snippets do nginx |
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

O provision ainda não instala o que está em `infra/apps/<nome>/`. Esse suporte chega com as tasks ETH-06 a ETH-10 do ethos.
