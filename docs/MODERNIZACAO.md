# Plano de modernização do site

Objetivo: atualizar a stack e melhorar layout, responsividade e acessibilidade
**sem perder a essência** do site — visual monocromático, tipografia Fira Mono,
navegação com bordas sólidas e o sublinhado animado no hover, herdados do tema
[hugo-coder-portfolio](https://github.com/naro143/hugo-coder-portfolio).

## 1. Diagnóstico (estado anterior)

| Área | Problema |
| --- | --- |
| Dependências | `react-router-dom` 5 (duas versões major atrás), `bootstrap` 4.6 + `react-bootstrap` 1 só para um card, `styled-components` 5, `react-iframe` só para um GIF, `react-light-accordion` sem manutenção, i18n três majors atrás. |
| Estilo | Mistura de `styled-components`, CSS global e Bootstrap; `* { color: black }` força cada componente a brigar com o global; peso 550 sem a fonte carregada. |
| Lint | Dois configs conflitantes (`.eslintrc.cjs` + `.eslintrc.yml` com airbnb), ESLint 8 (EOL). |
| Mobile | Menu quebra em várias linhas e é cortado; filtros de publicações viram uma coluna enorme; `text-align: justify` gera "rios" na fonte mono; paddings fixos de 50/80px. |
| Desktop | Linhas de texto com mais de 150 caracteres em telas largas; `CardColumns` (masonry por colunas) embaralha a ordem de leitura. |
| Acessibilidade | Ícones sociais e de download sem nome acessível, `<ul>` dentro de `<i>` (HTML inválido), barra de rolagem escondida, sem foco visível, troca de idioma sem indicar o ativo, título da aba igual em todas as páginas. |
| Performance | Bootstrap inteiro (~160 KB CSS) e runtime CSS-in-JS para um site estático; fonte do Google Fonts bloqueando renderização. |

## 2. Dependências

| Antes | Depois | Por quê |
| --- | --- | --- |
| `react-router-dom` 5 | `react-router` 8 | Versão atual; API `Routes`/`element`, `NavLink` com `end`. Pacote único (o `-dom` foi descontinuado). |
| `bootstrap` + `react-bootstrap` | CSS Grid próprio | Só o `Card` era usado. Remove ~160 KB de CSS. |
| `styled-components` 5 | CSS Modules (nativo do Vite) | Zero runtime, escopo por componente, sem conflito com o CSS global. |
| `styled-icons` | `react-icons` 5 | `styled-icons` depende de `styled-components`; `react-icons` tem os mesmos ícones (Simple Icons, Font Awesome) e tree-shaking. |
| `react-light-accordion` | `<details>/<summary>` nativo | Acessível por padrão, teclado e leitor de tela sem JS. |
| `react-iframe` | `<img>` | Um iframe para exibir um GIF era desnecessário. |
| Google Fonts (Fira Mono) | `@fontsource/fira-mono` | Fonte servida pelo próprio site: sem requisição externa, sem bloqueio, pesos 400/500/700. |
| `i18next` 23 / `react-i18next` 13 / backends | 26 / 17 / 4 / 8 | Versões atuais. |
| ESLint 8 + airbnb + config legado | ESLint 9 flat config + `react`, `react-hooks` 7, `jsx-a11y`, `react-refresh` | airbnb não suporta flat config; `jsx-a11y` ajuda a manter a acessibilidade. ESLint 10 fica para quando `eslint-plugin-react` e `jsx-a11y` o suportarem. |

## 3. Design system (mantendo a essência)

- **Tokens** em `:root`: `--fg`, `--bg`, `--muted`, `--surface`, `--border`, raio, espaçamentos e tamanhos fluidos com `clamp()`.
- **Modo escuro**: inversão do monocromático (preto ↔ branco), segue o sistema por padrão e tem botão no menu; escolha salva no navegador.
- **Tipografia**: Fira Mono em tudo, como antes; corpo em 500, títulos em 700; largura de leitura limitada (~72ch); texto alinhado à esquerda.
- **Assinaturas preservadas**: bordas sólidas de 2px no header/footer/cards, sublinhado que cresce no hover, avatar redondo, ícones sociais monocromáticos.
- **Movimento**: transições curtas; tudo desligado com `prefers-reduced-motion`.

## 4. Layout e responsividade por página

- **Header**: `sticky` (sem o hack de `padding-top` no body). Em telas pequenas vira um botão de menu que abre um painel; idioma com estado ativo (`aria-pressed`).
- **Home**: avatar com tamanho fluido, nome e ocupação centralizados, ícones sociais com rótulo acessível e área de toque ≥ 44px.
- **Sobre**: coluna de leitura centralizada; experiências em linha do tempo (borda à esquerda, período em destaque).
- **Projetos**: grade `auto-fill` (1 → 2 → 3 colunas) com ordem de leitura preservada, imagens com proporção fixa, botão sempre alinhado na base do card.
- **Publicações**: filtros como "chips" roláveis com contador, lista em `<details>` com ano em destaque, referência formatada e botões "PDF" e "Fonte".
- **404**: GIF via `<img>` com tamanho responsivo.
- **Footer**: compacto, quebra em linhas no mobile.

## 5. Qualidade, SEO e acessibilidade

- `<title>` por página usando o suporte nativo do React 19 a metadados.
- Link "Pular para o conteúdo", `:focus-visible` em todos os interativos, landmarks (`header`, `nav`, `main`, `footer`).
- Barra de rolagem visível de novo.
- Dados (projetos, publicações) extraídos para `src/data/`, componentes de classe convertidos para função.
- `manifest.json` com nome real do site.

## 6. Próximos passos (fora deste escopo)

- ESLint 10 quando os plugins suportarem.
- Gerar imagens dos projetos em WebP/AVIF e converter os GIFs em vídeo (`<video autoplay muted loop>`), que pesam bem menos.
- Pré-renderizar as rotas (ex.: modo framework/SSG do React Router) para SEO sem depender de JS.
- Testes de fumaça com Playwright no CI (navegação, troca de idioma e tema).
