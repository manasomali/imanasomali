"""Cookie da sessão: `__Host-ethos_session`.

Atributos: `HttpOnly; Secure; SameSite=Lax; Path=/`, sem `Domain` (o prefixo `__Host-` exige
`Secure`, `Path=/` e nenhum `Domain`, e o navegador recusa o cookie sem eles). `Max-Age` é a
duração da sessão no banco. O valor é o token de `app.auth.service.create_session`; no banco
fica só o sha256 dele, e a sessão é achada por `hash_secret(valor do cookie)`.

O navegador trata `http://localhost` como contexto seguro e aceita o cookie em dev. Clientes de
teste (httpx) só mandam cookie `Secure` de volta em URL https.
"""

from datetime import timedelta

from fastapi import Response

from app.auth.service import SESSION_LIFETIME

SESSION_COOKIE_NAME = "__Host-ethos_session"


def set_session_cookie(
    response: Response, token: str, max_age: timedelta = SESSION_LIFETIME
) -> None:
    """Grava o cookie da sessão na resposta (login e renovação)."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=int(max_age.total_seconds()),
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
