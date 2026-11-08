"""Cookie da sessão: `__Host-imago_session`, o mesmo para o site, o imago e as aplicações.

Atributos: `HttpOnly; Secure; SameSite=Lax; Path=/`, sem `Domain` (o prefixo `__Host-` exige
`Secure`, `Path=/` e nenhum `Domain`, e o navegador recusa o cookie sem eles). Como tudo está na
mesma origem, o cookie vale para todas as aplicações, que perguntam ao imago quem é o usuário
(`GET /internal/session`, pelo `auth_request` do nginx).

`Max-Age` de 400 dias (o máximo que o Chrome aceita), e não os 60 da sessão: quem decide a
validade é o `expires_at` do banco. A renovação feita pelo `auth_request` não chega ao navegador
(o nginx não repassa um `Set-Cookie` do imago), então um cookie de 60 dias derrubaria, 60 dias
depois do login, quem usa todo dia uma aplicação e nunca abre o `/imago/`.

O valor é o token de `app.auth.service.create_session`; no banco fica só o sha256 dele, e a sessão
é achada por `hash_secret(valor do cookie)`. O navegador trata `http://localhost` como contexto
seguro e aceita o cookie em dev. Clientes de teste (httpx) só mandam cookie `Secure` de volta em
URL https.
"""

from datetime import timedelta

from fastapi import Response

SESSION_COOKIE_NAME = "__Host-imago_session"
SESSION_COOKIE_MAX_AGE = timedelta(days=400)


def set_session_cookie(response: Response, token: str) -> None:
    """Grava o cookie da sessão na resposta (login e renovação)."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=int(SESSION_COOKIE_MAX_AGE.total_seconds()),
        path="/",
        domain=None,
        secure=True,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    """Apaga o cookie da sessão no navegador (logout).

    Os atributos são os mesmos da gravação: sem `Secure` e `Path=/`, o navegador recusaria o
    Set-Cookie de um cookie `__Host-`, e o cookie antigo ficaria.
    """
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        domain=None,
        secure=True,
        httponly=True,
        samesite="lax",
    )
