# Tokens de design

`tokens.css` guarda a identidade visual comum ao site e às aplicações: cores, tipografia, larguras e os valores do tema escuro. Tudo são propriedades customizadas do CSS em `:root` (`--fg`, `--bg`, `--text-base`, `--wide-width`...), mais o `color-scheme` de cada tema, que acompanha as cores para que barras de rolagem e controles nativos sigam o tema.

O arquivo só tem tokens. Estilos de elementos (`body`, `h1`, `:focus-visible`, `interpolate-size`...) ficam em quem consome, como o `site/src/index.css`.

## Como importar

O site importa no topo do `site/src/index.css`, junto com as fontes:

```css
@import '../../packages/tokens/tokens.css';
```

O Vite embute o arquivo no CSS final no build. No dev, o `site/vite.config.js` libera `../packages` em `server.fs.allow`. Definir `allow` substitui o padrão do Vite, então a raiz do próprio site continua na lista.

As aplicações importam o mesmo arquivo do mesmo jeito, com o caminho relativo a partir de `apps/<nome>/` e a mesma configuração de `server.fs.allow`. Não copie os valores para dentro da aplicação.

`--font` só dá o nome da família (`Fira Mono`). Quem usa o token carrega a fonte por conta própria (o site usa `@fontsource/fira-mono`, pesos 400, 500 e 700).

## Tema escuro: valores em dois lugares

Os valores escuros aparecem duas vezes, e as duas cópias precisam ser iguais:

- `:root[data-theme='dark']`: tema escuro escolhido pela pessoa.
- `@media (prefers-color-scheme: dark)` com `:root:not([data-theme='light'])`: sem escolha salva, segue o sistema. O `:not` faz a escolha explícita do tema claro vencer o sistema escuro.

Ao mudar ou criar um token escuro, edite os dois blocos. Tokens que não mudam com o tema (tipografia, larguras, `--border`, que deriva de `--fg`) ficam só no `:root`.

## Contrato do `localStorage`

Site e aplicações rodam na mesma origem (`manasomali.com`, com as aplicações em `/<nome>/`), e o `localStorage` é por origem, não por caminho. Por isso dividem as mesmas chaves: quem escolhe o tema escuro no site entra numa aplicação com o tema escuro, e o mesmo vale para o idioma. Todos precisam ler e gravar essas chaves de forma compatível.

| Chave | Valores | Ausente | Quem grava |
|---|---|---|---|
| `theme` | `'light'` ou `'dark'` | segue `prefers-color-scheme` | o botão de tema, só quando a pessoa escolhe |
| `i18nextLng` | código de idioma: `'pt'` ou `'en'`, às vezes com região (`'pt-BR'`) | detecta pelo navegador, com `en` como fallback | `i18next-browser-languagedetector`, ao detectar ou trocar o idioma |

Regras:

- **`theme`:** grave só `'light'` ou `'dark'`. Para voltar a seguir o sistema, remova a chave, não grave outro valor. Aplique o valor como `data-theme` no `<html>` antes da primeira pintura, com um script inline no `<head>` (como em `site/index.html`), para não piscar o tema errado. Os seletores de `tokens.css` dependem desse atributo.
- **`i18nextLng`:** use o `i18next-browser-languagedetector` com a chave padrão (`lookupLocalStorage: 'i18nextLng'`), ou leia e grave a mesma chave com os mesmos códigos. Ao ler, aceite também variantes regionais (`pt-BR`) e reduza ao idioma base, como faz o site com `load: 'languageOnly'`.
- **Falhas:** o acesso ao `localStorage` pode lançar exceção (modo privado, armazenamento bloqueado). Leia e grave dentro de `try`/`catch` e, se falhar, siga o sistema e o idioma do navegador.
- **Chaves próprias:** chave que só uma aplicação usa leva o nome dela como prefixo (`<nome>:...`), para não colidir com as do site nem com as de outra aplicação. Sem prefixo, só as chaves compartilhadas desta tabela.

No dev, site e aplicações rodam em portas diferentes, então são origens diferentes e não dividem o `localStorage`. O contrato só aparece de verdade em produção, ou servindo os dois atrás da mesma origem.
