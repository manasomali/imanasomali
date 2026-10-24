"""Logs do app: configuração dos loggers e uma linha por request.

A linha do request tem só método, rota, status e duração. A rota é o molde declarado
(ex.: /habits/{habit_id}), nunca o caminho recebido, e nada da query string, dos headers, dos
cookies ou do corpo entra no log: assim não vazam IP, email, código, token nem cookie.
"""

import logging
import sys
import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import AppEnv

# Logger raiz do pacote: os módulos usam logging.getLogger(__name__) ("app.xxx")
APP_LOGGER = "app"
REQUEST_LOGGER = "app.request"

_KNOWN_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))


def configure_logging(app_env: AppEnv) -> None:
    """Liga os logs do app (INFO em produção, DEBUG em dev). Pode ser chamada mais de uma vez."""
    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(logging.INFO if app_env is AppEnv.PROD else logging.DEBUG)
    # O uvicorn só configura os loggers dele; sem handler aqui, o INFO do app sumiria.
    # O journald já marca a hora de cada linha
    if _handler not in logger.handlers:
        logger.addHandler(_handler)
    # O access log do uvicorn grava o IP do cliente e o caminho com a query string. A linha do
    # RequestLogMiddleware o substitui
    logging.getLogger("uvicorn.access").disabled = True


class RequestLogMiddleware:
    """Middleware ASGI: uma linha de log por request HTTP, mesmo quando o app levanta exceção."""

    def __init__(self, app: ASGIApp, logger_name: str = REQUEST_LOGGER) -> None:
        self.app = app
        self.logger = logging.getLogger(logger_name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        # Se o app levantar exceção antes de responder, quem responde é o handler de 500
        status = 500

        async def send_and_capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_capture)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.logger.info("%s %s %d %.1fms", _method(scope), _route(scope), status, elapsed_ms)


def _method(scope: Scope) -> str:
    method = scope.get("method", "")
    return method if method in _KNOWN_METHODS else "OTHER"


def _route(scope: Scope) -> str:
    # O roteador grava no scope a rota que casou. Sem rota (404), não há molde para mostrar
    route: Any = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "-"
