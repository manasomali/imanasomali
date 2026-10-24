# Pacotes compartilhados

Código usado pelo site e pelas aplicações. É a única coisa que uma área pode importar de outra (ver [apps/README.md](../apps/README.md)).

Mudanças aqui disparam o workflow do site e os das aplicações, porque todos têm `packages/**` nos seus `paths`.
