# nginx de desenvolvimento

Em produção, o nginx pergunta ao imago quem é o usuário em cada request de `/api/<app>/` (`auth_request` em `/_imago/session`) e repassa a resposta à aplicação nos headers `X-User-*`. Sem esse nginx, uma aplicação não sabe quem está logado. Esta pasta sobe o mesmo nginx da VM (`nginx:1.24`) em container, como origem única `http://localhost:8080`, com as rotas de produção de cada aplicação (`infra/apps/*/nginx.conf` e `nginx-http.conf`), na frente do imago e das aplicações rodando na máquina.

O `nginx.sh` gera a config em `.generated/` (fora do git) como o provision faz na VM: troca o `__PORTA__` pelo `PORT` do `infra/apps/<nome>/app.conf` e o `127.0.0.1` por `host.docker.internal`, que dentro do container é a máquina. O `server` do site não entra: `/` leva ao `/imago/`, e o que não é de uma aplicação dá 404.

## Como rodar

Precisa do Docker (Docker Desktop no Windows e no Mac). Cada backend sobe na porta de produção, com o `APP_URL` apontando para o nginx (a checagem de `Origin` usa a origem dele):

| Aplicação | Backend | `APP_URL` | Vite |
|---|---|---|---|
| imago | `127.0.0.1:3003` | `http://localhost:8080/imago` | 5175 |
| ethos | `127.0.0.1:3001` | `http://localhost:8080/ethos` | 5174 |

O imago chama a API interna de cada aplicação (e ela a dele) direto em `127.0.0.1`, sem o nginx, com o token da aplicação: o mesmo valor vai no `IMAGO_APP_TOKENS` do `.env` do imago (`ethos:<token>`) e no `INTERNAL_API_TOKEN` do `.env` do ethos, e o `IMAGO_APPS` do imago aponta para a porta de cada uma (`ethos=http://127.0.0.1:3001`). Um token de dev sai de `python -c "import secrets; print(secrets.token_urlsafe(32))"`. O passo a passo de cada backend (`.env`, migrações, `seed`) está no `README.md` da aplicação. Depois, da raiz do repo:

```bash
bash apps/imago/dev/nginx.sh up           # front de produção: o dist/ de cada aplicação (npm run build)
bash apps/imago/dev/nginx.sh up --vite    # front pelo dev server do Vite de cada aplicação, com HMR
```

Abra `http://localhost:8080/imago/entrar`. O cookie `__Host-imago_session` é `Secure`, e o Chrome o aceita em `http://localhost`, que ele trata como origem segura (o E2E do ethos usa o mesmo comportamento). Com o `seed` do imago e `EMAIL_BACKEND=console`, o código de login sai no terminal do backend do imago; não existe atalho de login, nem em dev.

- **Front pelo `dist/`** (padrão): o mais perto de produção, com os mesmos headers (CSP sem `'unsafe-inline'`) e o mesmo cache. Rode `npm run build` no front que mudou. Sem o `dist/`, o `/<app>/` dá 404.
- **Front pelo Vite** (`--vite`): cada front vem do `npm run dev` dele, com HMR. Só as locations do front mudam (um `location ~ ^/<app>/` de regex vence os de produção); as da API são as de produção. Sem a CSP de produção, que bloquearia o script inline do HMR.
- **Linux sem Docker Desktop** (`--host-network`): lá o `host.docker.internal` só alcança o que escuta na interface da bridge, e não um serviço em `127.0.0.1`. Com a rede do host, o container usa o `127.0.0.1` da máquina, sem troca nenhuma.

Se uma rota der **502**, o backend (ou o Vite) daquela porta não está rodando ou não é alcançável do container. O Vite em `localhost` pode escutar só em IPv6 (`::1`): suba-o com `npm run dev -- --host 127.0.0.1`.

## Checagem

`bash apps/imago/dev/nginx.sh check` gera as duas configs (front pelo `dist/` e pelo Vite) e roda `nginx -t` nelas, no `nginx:1.24`. Roda no CI (`infra.yaml`), porque uma mudança em `infra/apps/*/nginx.conf` também muda a config de dev. `bash apps/imago/dev/nginx.sh render <pasta>` só gera a config, para conferir.
