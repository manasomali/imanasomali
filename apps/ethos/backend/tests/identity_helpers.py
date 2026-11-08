"""Os headers `X-User-*` que o nginx põe a partir do imago, para os testes.

- `identity_headers(usuário, admin=False)`: os headers de um usuário de `app_users`, como o imago
  os manda (com `X-User-Admin: 1` só para admin). A fixture `make_account` do `conftest.py` cria
  o usuário e devolve `Account(user, headers)` com eles.
"""

from app.models import AppUser


def identity_headers(user: AppUser, *, admin: bool = False) -> dict[str, str]:
    headers = {
        "X-User-Id": str(user.id),
        "X-User-Email": user.email,
        "X-User-Locale": user.locale,
        "X-User-Timezone": user.timezone,
    }
    if admin:
        headers["X-User-Admin"] = "1"
    return headers
