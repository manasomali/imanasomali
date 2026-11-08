# Pacotes compartilhados

Código usado pelo site e pelas aplicações. É a única coisa que uma área pode importar de outra (ver [apps/README.md](../apps/README.md)).

| Pacote | O quê | Quem usa |
|---|---|---|
| [tokens/](tokens/README.md) | tokens de design (cores, tipografia, larguras, tema escuro) e o contrato do `localStorage` | o site e as aplicações |
| [deploy/](deploy/README.md) | scripts do deploy de uma aplicação na VM, com o nome dela como parâmetro, e os testes deles | os workflows das aplicações |

Mudanças aqui disparam o workflow do site e os das aplicações, porque todos têm `packages/**` nos seus `paths`.
