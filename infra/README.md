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
