"""Aplicações falsas dos testes: a API interna do ethos e do engrafi, num `httpx2.MockTransport`.

A fixture `apps` (conftest) cria uma `FakeApps` ligada ao `app` padrão; para outro app ou para o
CLI, passe `apps.transport` (`create_app(..., app_transport=apps.transport)`).

- `apps.calls`: cada chamada recebida, na ordem (`Call`: aplicação, ação, id, token e corpo);
- `apps.down`: nomes das aplicações fora do ar (a chamada levanta `ConnectError`);
- `apps.status`: status da resposta por aplicação (padrão 200);
- `apps.before_reply`: função chamada com a `Call` antes de responder (para mexer no banco no
  meio de uma chamada ou sincronizar threads).
"""

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx2

# Portas das aplicações do make_settings (IMAGO_APPS dos testes)
APP_PORTS = {3001: "ethos", 3002: "engrafi"}
_PATH = re.compile(r"/internal/users/([0-9]+)/(delete|refresh)")


@dataclass(frozen=True)
class Call:
    app: str
    action: str
    user_id: int
    token: str
    body: Any


@dataclass
class FakeApps:
    calls: list[Call] = field(default_factory=list)
    down: set[str] = field(default_factory=set)
    status: dict[str, int] = field(default_factory=dict)
    before_reply: Callable[[Call], None] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.transport = httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        assert request.url.host == "127.0.0.1"
        app = APP_PORTS[request.url.port]
        match = _PATH.fullmatch(request.url.path)
        assert match is not None, request.url.path
        content = request.read()
        auth = request.headers.get("authorization", "")
        call = Call(
            app=app,
            action=match[2],
            user_id=int(match[1]),
            token=auth.removeprefix("Bearer "),
            body=json.loads(content) if content else None,
        )
        with self._lock:
            self.calls.append(call)
        if self.before_reply is not None:
            self.before_reply(call)
        if app in self.down:
            raise httpx2.ConnectError("conexão recusada", request=request)
        status = self.status.get(app, 200)
        return httpx2.Response(status, json={"status": "ok"})

    def of(self, action: str) -> list[tuple[str, int]]:
        """(aplicação, id) das chamadas de `action`, na ordem."""
        return [(call.app, call.user_id) for call in self.calls if call.action == action]
