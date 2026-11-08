## Frontend

```bash
cd apps/imago/frontend
npm ci
npm run dev                                # http://localhost:5175/imago/
```

O dev server usa a porta 5175 (o site usa a 5173 e o ethos a 5174) e falha se ela estiver ocupada. Também dá para subir pela entrada `imago` do `.claude/launch.json`. Em dev, o Vite repassa `/api/imago/*` para o backend em `http://127.0.0.1:3003` (a porta de produção), sem o prefixo, como o nginx faz em produção; suba o backend antes de usar as telas que chamam a API. Em dev o site, o imago e as aplicações rodam em portas diferentes, então não dividem o cookie nem o `localStorage`: para o fluxo entre aplicações (o `next` de volta para o ethos), use o nginx de dev em `http://localhost:8080`.

```bash
npm run lint                               # ESLint com jsx-a11y; qualquer aviso falha
npm test                                   # vitest com cobertura, roda uma vez e sai
npm run build                              # gera dist/
npm run preview                            # serve o dist/ localmente
```

### Telas

| Rota | Tela | Login |
|---|---|---|
| `/imago/` | Conta: email (só leitura, com a troca pelo `support_email` do `GET /me`), as aplicações, idioma, fuso, sair, sair de todos os aparelhos e a exclusão da conta | sim; sem sessão vai para `/imago/entrar?next=/imago/`. Com termos pendentes mostra o aviso do aceite e só o que funciona sem ele (sair e excluir) |
| `/imago/entrar?next=<caminho>` | Entrar (email → código) e o aceite de termos novos. Destino do 401 do imago e de todas as aplicações | não |
| `/imago/termos`, `/imago/privacidade` | Termos de uso e política de privacidade de todas as aplicações | não |
| `/imago/admin` | Contas (busca, bloquear, trocar email, excluir) e os envios de email das últimas 24 h | `is_admin` e termos aceitos; quem não é admin volta para a conta, e termos pendentes vão para o aceite |

O rodapé de toda tela tem os links dos termos e da privacidade.

### Estrutura

| Caminho | O quê |
|---|---|
| `index.html` | Carrega `/imago/theme-init.js` no `<head>`, sem `defer`, antes do app |
| `public/theme-init.js` | Aplica o tema salvo (`localStorage.theme`) como `data-theme` antes da primeira pintura. É arquivo, não script inline, por causa da CSP (`script-src 'self'`) |
| `public/locales/{pt,en}/translation.json` | Traduções, baixadas em runtime (não vão no bundle). `errors.<codigo>` traduz os códigos da API; `apps.<nome>` tem os textos de cada aplicação (abaixo) |
| `src/main.jsx`, `src/bootstrap.js`, `src/App.jsx` | Inicia o i18n, cria o router (`basename="/imago"`) e o QueryClient (`createApp`): um 401 em qualquer chamada leva para a tela de entrar com o caminho atual no `next` |
| `src/routes.jsx`, `src/paths.js` | Todas as rotas e `BASENAME`/`PATHS` (`/`, `/entrar`, `/termos`, `/privacidade`, `/admin`). Use as constantes, nunca o caminho escrito à mão |
| `src/i18n.js` | `createI18n()`, `LANGUAGES` e a detecção do idioma (chave compartilhada `i18nextLng`; `pt-BR` vira `pt`) |
| `src/index.css` | Estilos globais. Importa as fontes e `@tokens/tokens.css` (alias para `packages/tokens`) |
| `src/api/account.js` | `/auth` e `/me`: `useMe`, `useSignedInMe` (o `/me` já carregado, sem buscar, só se a última busca deu certo: para o topo), `requestCode`, `verifyCode` (manda o fuso do navegador e o idioma da tela), `acceptTerms` (manda o `TERMS_VERSION`), `useUpdateMe` (`PATCH /me`; idioma novo vira também o da tela), `useLogout`, `useLogoutAll`, `requestAccountDeletion`, `useDeleteAccount` (os três limpam o cache e vão para a tela de entrar) |
| `src/api/admin.js` | `/admin`: `useAccounts(query)` (páginas por cursor), `setAccountActive`, `changeAccountEmail`, `deleteAccount`, `useMailStats` |
| `src/components/` | `Layout` (pular para o conteúdo, topo, `<main>`, rodapé), `Header` (conta, admin só para `is_admin`, volta ao site, idioma da tela e tema), `RequireSession`, `RequireAdmin`, `ErrorMessage`, `PageTitle`, `TextDocument` (texto puro com sumário e âncoras) |
| `src/pages/` | `Login` (`CodeForm` e `TermsAcceptance`), `Account` (`Apps`, `LanguageForm`, `TimezoneForm`, `Sessions`, `DeleteAccount`), `Legal`, `Admin` (`AccountCard`, `MailStats`), `NotFound` |
| `src/legal/{pt,en}/{terms,privacy}.json` | Textos legais (abaixo) |
| `src/lib/` | Utilitários sem React, com cobertura mínima de 80% (abaixo) |
| `src/test/` | Setup dos testes: MSW (`server`, `api(path)`, `apiError`, `trackRequests`), `renderApp(path)`, `meFixture()`, `signedIn()`, `createTestI18n()`, `axe`, `readFrontendFile()`; do admin, `src/test/admin.js` (`ADMIN`, `accountFixture`, `mailFixture`) |
| `tests/` | Testes do build de produção, no Node |
| `build-targets.js` | Converte o `browserslist` do `package.json` no `build.target` do Vite |

### `src/lib/`

- `api.js`: `apiFetch(path, {method, query, body, signal})` chama `/api/imago<path>` na mesma origem, com `credentials: 'include'` (o cookie `__Host-imago_session` é HttpOnly; o front nunca o lê). Erro sempre vira `ApiError {status, code, field}`: o código vem do corpo `{"error", "field"}` ou, quando o corpo não é JSON (o nginx responde 429, 502 e 504 em HTML), do status. Sem resposta: status 0 e `network_error`.
- `queryClient.js`: leitura só repete falha de rede e 5xx; escrita nunca repete; todo 401 chama `onUnauthorized`.
- `next.js`: o `next` da tela de entrar. `resolveNext(valor)` monta `new URL(next, location.origin)`, exige a mesma origem e recusa caractere de controle (C0, DEL e C1) e `\`; `next` ausente, inválido ou para a própria tela de entrar (em qualquer grafia que o router aceita) vira `/imago/`. `appRoute(caminho)` diz se o destino é do próprio imago (navegação pelo router) ou de fora (navegação de página inteira, por `pageLocation.replace` de `location.js`, que tira a tela de entrar do histórico).
- `session.js`: `loginPath(next)` (`/entrar?next=/imago/admin`, barras legíveis) e `redirectToLogin(router)`, o destino do 401. `SESSION_NOT_SAVED`: código só do front para o código aceito sem sessão no `/me` seguinte (cookie não guardado).
- `apps.js`: aplicações do `GET /me` (`accountApps`, nomes com a regra do `databases.txt`), `appPath(nome)` (`/<nome>/`) e `appTexts(nome, t, exists)`, os textos de `apps.<nome>` (sem tradução, o nome cru; `export_path` só vale na mesma origem).
- `legal.js`: `TERMS_VERSION`, `SUPPORT_EMAIL` (dos textos legais, que abrem sem login), `loadLegalDocument(nome, idioma)` e `contactEmail(valor)` (o `support_email` do `/me` se for um email simples).
- `admin.js`: filtros da listagem (`accountQuery`, `ACCOUNT_STATUSES`), `accountStatus` (`active`, `blocked` ou `deleting`), `confirmsEmail` (a confirmação digitando o email) e `accountApiPath(id)`.
- `mail.js`: o `GET /admin/mail` para a tela: `mailWindow` (quanto falta para o teto e para as notificações pararem) e `mailTable` (linhas por aplicação e totais).
- `code.js` (6 dígitos, `onlyDigits`, espera de 60 s para reenviar), `locale.js` (`apiLocale`), `time.js` e `timezones.js` (fuso do navegador, lista IANA com offset e busca sem acento), `datetime.js` (`formatDateTime` no fuso de quem vê), `theme.js` e `storage.js` (chaves compartilhadas sem lançar exceção).

### Login e `next`

Cadastro e login são a mesma tela: email → código de 6 dígitos (`inputmode="numeric"`, `autocomplete="one-time-code"`, reenviar depois de 60 s, "já tenho um código" depois de um 429). As mensagens são iguais para qualquer email. A tela busca o `/me` sempre que abre (nunca confia no cache, que pode ser de uma sessão que acabou):

- sem sessão (401): o formulário, com o aviso "ao continuar, você concorda com os termos de uso e a política de privacidade";
- com sessão e termos em dia: vai direto para o `next`;
- com sessão e termos pendentes: só o aceite (`POST /me/terms` com o `TERMS_VERSION` do build). Um 409 quer dizer que o backend já tem uma versão mais nova que a desta aba: a tela pede para recarregar a página, que traz os textos novos. Dá para sair dali, e quem não concordar pode excluir a conta na tela de conta.

As aplicações mandam para `/imago/entrar?next=<caminho atual>` quando a API delas responde 401 (termos pendentes contam como sem login para elas).

### Textos de cada aplicação

Cada aplicação do `IMAGO_APPS` tem, nos dois `translation.json`, o objeto `apps.<nome>` com `name`, `description` (lista da tela de conta), `deletion` (o que some na exclusão), `export_label` e `export_path` (caminho absoluto do export, ex.: `/ethos/relatorio`, a tela do "exportar tudo"). `src/lib/apps.test.js` confere as 5 chaves em pt e en e que o export do ethos é o `PATHS.report` de `apps/ethos/frontend/src/paths.js`; o `.github/scripts/check-imago-apps.sh` confere que toda aplicação do `IMAGO_APPS` tem os dela. Aplicação nova: acrescente os textos e a seção dela nos termos e na privacidade (versão nova dos termos).

### Termos e privacidade

Os textos ficam em `src/legal/<idioma>/<documento>.json` (`terms` e `privacy`, em `pt` e `en`), texto puro, no mesmo formato do ethos: `{title, sections: [{id, title, paragraphs}]}`, cada parágrafo um texto ou uma lista de textos, e o único marcador é `{{supportEmail}}`. A parte geral vale para todas as aplicações; cada aplicação tem uma seção com o nome dela como `id` (`/imago/termos#ethos`). Os JSON não vão no bundle principal: cada um vira um chunk com hash.

`src/lib/legal.test.js` falha se a versão for diferente do `TERMS_VERSION` de `backend/app/terms.py`, se pt e en não tiverem as mesmas seções (mesmos ids, na mesma ordem e com a mesma forma), se um texto tiver marcação ou outro marcador, se faltar a seção de uma aplicação de `apps`, se a política não citar o cookie `__Host-imago_session` e se os prazos não baterem (sessão 60 dias, código 10 minutos, eventos de auth e IPs 90 dias, contagem de emails 48 horas e cópias de segurança de `infra/scripts/snapshot.sh` e `infra/lib/backups.sh`). O `SUPPORT_EMAIL` é comparado com o de `infra/apps/imago/app.env` quando esse arquivo existe.

Para publicar uma versão nova (inclusive a entrada de uma aplicação nova): mude os textos nos dois idiomas, `TERMS_VERSION` aqui e em `backend/app/terms.py`, no mesmo PR. Os textos são um rascunho técnico e precisam da revisão do dono antes de entrar no ar.

### Testes

Os testes rodam no vitest em dois projetos: `app` (jsdom, `src/**/*.test.*`, com MSW, i18n e o setup de `src/test/setup.js`) e `build` (Node, `tests/*.test.js`). `npm test` liga a cobertura e falha abaixo de 80% em `src/lib/`. Toda request sem handler do MSW falha o teste, e todo teste de tela confere acessibilidade com o `axe` de `src/test/axe.js`:

```jsx
expect(await axe(container)).toHaveNoViolations();
```

Navegação de página inteira (o `next` de outra aplicação, recarregar a página) passa por `pageLocation` (`src/lib/location.js`), que os testes trocam com `vi.spyOn`: o jsdom não navega. Checagens entre áreas: a versão dos termos (`backend/app/terms.py`), o catálogo de erros (`backend/app/errors.py`: todo código tem tradução) e o export do ethos.

`tests/build.test.js` roda o `vite build` de verdade e confere que os tokens de `packages/tokens` entram no CSS (e que trocar um token muda o CSS), que o `index.html` carrega o `theme-init.js` no `<head>` sem `defer`, que não há script nem estilo inline, que tudo é servido em `/imago/` e que os textos legais ficam fora do bundle principal.
