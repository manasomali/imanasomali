"""Imago falso dos testes: a API interna do imago num `httpx2.MockTransport`, sem rede.

O app recebe o transporte em `create_app(settings, imago_transport=imago.transport)` (fixtures
`imago` e `app` do `conftest.py`); o CLI dos alertas, por `ImagoClient(..., transport=...)`. Como o
imago de verdade, o falso confere o `Authorization: Bearer <INTERNAL_TOKEN>` (401 sem ele) e
responde:

- `POST /internal/users/lookup` `{email}`: 200 `{id, locale}` para as contas de `accounts`
  (`add_account`), 404 para as outras. `lookup_status` troca a resposta (ex.: 500);
- `POST /internal/mail` `{kind, user_id, subject, text, html}`: `mail_status` (202 por padrão;
  um número ou uma função do corpo). Os emails aceitos (202) ficam em `mails`.

`error`: uma exceção do httpx2 a levantar em toda chamada (rede fora, timeout). `requests`: tudo
o que chegou, na ordem.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx2

# Token da API interna nos testes (o mesmo da `settings` do conftest): 32+ caracteres base64url
INTERNAL_TOKEN = "ethos-test-internal-api-token-0123456789AB"  # noqa: S105


@dataclass(frozen=True)
class SentMail:
    """Um email que o imago falso aceitou (202)."""

    user_id: int
    kind: str
    subject: str
    text: str
    html: str


@dataclass
class FakeImago:
    token: str = INTERNAL_TOKEN
    # email -> (id, idioma): as contas ativas que o lookup encontra
    accounts: dict[str, tuple[int, str]] = field(default_factory=dict)
    mail_status: int | Callable[[dict[str, Any]], int] = 202
    lookup_status: int | None = None
    error: type[httpx2.HTTPError] | None = None
    mails: list[SentMail] = field(default_factory=list)
    requests: list[httpx2.Request] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.transport = httpx2.MockTransport(self._handle)

    def add_account(self, user_id: int, email: str, locale: str = "pt") -> None:
        self.accounts[email] = (user_id, locale)

    def mails_to(self, user_id: int) -> list[SentMail]:
        return [mail for mail in self.mails if mail.user_id == user_id]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error("falha simulada", request=request)
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx2.Response(401, json={"error": "unauthorized", "field": None})
        body = json.loads(request.content)
        if request.method == "POST" and request.url.path == "/internal/users/lookup":
            return self._lookup(body)
        if request.method == "POST" and request.url.path == "/internal/mail":
            return self._mail(body)
        return httpx2.Response(404, json={"error": "not_found", "field": None})

    def _lookup(self, body: dict[str, Any]) -> httpx2.Response:
        if self.lookup_status is not None:
            return httpx2.Response(self.lookup_status, json={"error": "x", "field": None})
        found = self.accounts.get(body["email"])
        if found is None:
            return httpx2.Response(404, json={"error": "not_found", "field": None})
        user_id, locale = found
        return httpx2.Response(200, json={"id": user_id, "locale": locale})

    def _mail(self, body: dict[str, Any]) -> httpx2.Response:
        status = self.mail_status(body) if callable(self.mail_status) else self.mail_status
        if status == 202:
            self.mails.append(
                SentMail(
                    user_id=body["user_id"],
                    kind=body["kind"],
                    subject=body["subject"],
                    text=body["text"],
                    html=body["html"],
                )
            )
            return httpx2.Response(202, json={"status": "accepted"})
        if status == 204:
            return httpx2.Response(204)
        return httpx2.Response(status, json={"error": "x", "field": None})
