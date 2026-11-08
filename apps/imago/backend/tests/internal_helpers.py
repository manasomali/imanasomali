"""Tokens da API interna dos testes (as aplicações ethos e engrafi do `make_settings`).

- `ETHOS_TOKEN`, `ENGRAFI_TOKEN`: base64url, 43 caracteres, como os que o provision gera;
- `bearer(token)`: o header `Authorization` com o token.
"""

ETHOS_TOKEN = "ethos-test-token-AAAAAAAAAAAAAAAAAAAAAAAAAA"  # noqa: S105
ENGRAFI_TOKEN = "engrafi-test-token-BBBBBBBBBBBBBBBBBBBBBBBB"  # noqa: S105


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
