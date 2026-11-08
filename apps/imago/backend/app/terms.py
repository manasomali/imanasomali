"""Versão atual dos termos de uso e da política de privacidade, um par só para todas as aplicações.

Fica no código, e não numa variável de ambiente: a versão muda junto com os textos, no mesmo PR, e
não com o ambiente. O front tem a mesma constante, em `apps/imago/frontend/src/lib/legal.js`
(`export const TERMS_VERSION = '...'`), e o teste `src/lib/legal.test.js` do front lê este arquivo
e falha se as duas forem diferentes.

- Conta nova nasce com esta versão aceita (`users.terms_version`).
- Quando a versão muda (inclusive com a entrada de uma aplicação nova nos termos), quem aceitou uma
  anterior precisa aceitar de novo no próximo acesso: até lá, `GET /internal/session` não devolve o
  usuário às aplicações e o `PATCH /me` e o admin respondem 403 `terms_not_accepted`
  (`GET /me` e `POST /me/terms` funcionam).

Formato: data da versão (`AAAA-MM-DD`), até `TERMS_VERSION_MAX_LENGTH` caracteres. Para publicar
uma versão nova, troque o valor aqui, o do front e os textos no mesmo PR.
"""

TERMS_VERSION = "2026-11-08"
