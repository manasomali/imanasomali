"""Atalhos dos testes de login (ETH-17) que as tasks seguintes reusam.

- `Outbox`: backend de email que só guarda as mensagens (`.messages`), sem rede. App com ele:
  `create_app(settings, mail_backend=outbox)` (fixture `outbox` no conftest);
- `code_in(message)`: o código de 6 dígitos do texto de um email de código;
- `session_token(response)`: o valor do cookie `__Host-ethos_session` no Set-Cookie;
- `login(client, outbox, email)`: pede o código, lê no outbox e verifica. Devolve o token da
  sessão. O cookie é `Secure`, e o TestClient (http://testserver) não o manda de volta sozinho:
  passe o token no header `Cookie` ou use um TestClient com `base_url="https://testserver"`.
- `cookie(token)`: o header `Cookie` com a sessão, para mandar em cada request;
- `open_session(session, user)`: cria uma sessão do usuário agora, direto no banco (sem email), e
  devolve o token. O usuário precisa ter `terms_version=TERMS_VERSION` para passar no
  `CurrentUser`.
"""

import re
from email.message import EmailMessage
from http.cookies import SimpleCookie

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.cookies import SESSION_COOKIE_NAME
from app.auth.service import create_session
from app.db import write_transaction
from app.models import User, utcnow

_CODE_LINE = re.compile(r"^([0-9]{6})$", re.MULTILINE)


class Outbox:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.messages.append(message)

    def to(self, address: str) -> list[EmailMessage]:
        return [message for message in self.messages if message["To"] == address]


def code_in(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    assert part is not None
    found = _CODE_LINE.search(part.get_content())
    assert found is not None
    return found.group(1)


def session_token(response) -> str:
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie[SESSION_COOKIE_NAME].value


def login(
    client: TestClient,
    outbox: Outbox,
    email: str,
    *,
    timezone: str = "America/Sao_Paulo",
    locale: str = "pt",
) -> str:
    response = client.post("/auth/code/request", json={"email": email})
    assert response.status_code == 202
    code = code_in(outbox.to(email)[-1])
    response = client.post(
        "/auth/code/verify",
        json={"email": email, "code": code, "timezone": timezone, "locale": locale},
    )
    assert response.status_code == 200
    return session_token(response)


def cookie(token: str) -> dict[str, str]:
    # O cookie é Secure e o TestClient roda em http: vai no header
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def open_session(session: Session, user: User) -> str:
    with write_transaction(session):
        return create_session(session, user.id, now=utcnow(), ip=None, user_agent=None)
