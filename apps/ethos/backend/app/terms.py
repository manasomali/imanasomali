"""Versão atual dos termos de uso e da política de privacidade.

Fica no código, e não numa variável de ambiente (decisão da ETH-11): a versão muda junto com os
textos dos termos, no mesmo PR, e não com o ambiente. O front usa o mesmo identificador.

- Conta nova nasce com esta versão aceita (`users.terms_version`, ETH-17).
- Quando a versão muda, quem aceitou uma anterior precisa aceitar de novo no próximo acesso
  (`GET /auth/me` e `POST /auth/me/terms`, ETH-18).

Formato: data da versão (`AAAA-MM-DD`), até `TERMS_VERSION_MAX_LENGTH` caracteres. Para publicar
uma versão nova, troque o valor aqui e os textos no front no mesmo PR.
"""

TERMS_VERSION = "2026-10-24"
