"""Proteção contra CSRF: o header `Origin` das requests de escrita tem que ser a origem do app.

Além do `SameSite=Lax` do cookie, toda request com método que não seja GET, HEAD ou OPTIONS
(POST, PUT, PATCH, DELETE e qualquer outro) só passa com exatamente um header `Origin` igual a
`settings.app_origin`: esquema + host (+ porta, se não for a padrão) do `APP_URL`, ex.:
`https://manasomali.com`. A comparação é exata: o navegador manda a origem já normalizada
(minúsculas, sem porta padrão, sem caminho), então `Origin` ausente, `null`, com caminho (ou só
com a barra no fim), de outro esquema, host ou porta é recusado com 403 `forbidden`.

A exceção é a API interna (`/internal/*`), que não vem do navegador: as aplicações chamam direto
em 127.0.0.1, com o token delas (`app/internal/deps.py`), e o nginx responde 404 para
`/api/imago/internal/` de fora.

É um middleware, e não uma dependência do FastAPI, para cobrir todas as rotas (inclusive as de
login, as 404 e as 405) e recusar antes de ler o corpo ou abrir o banco: uma dependência global
só roda depois do parse do JSON e só nas rotas que existem.
"""

from collections.abc import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

from app.errors import ErrorCode, error_response

# Métodos que não mudam nada e por isso não são conferidos
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Rotas da API interna, sem a checagem de Origin
INTERNAL_PREFIX = "/internal/"
_ORIGIN = b"origin"


class OriginCheckMiddleware:
    """Middleware ASGI: 403 para escrita sem o `Origin` do app. Lê a config de `app.state`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] in SAFE_METHODS
            or route_path(scope).startswith(INTERNAL_PREFIX)
        ):
            await self.app(scope, receive, send)
            return
        # O Starlette põe o próprio app no scope; a config foi carregada no lifespan
        expected = scope["app"].state.settings.app_origin
        if not origin_allowed(scope["headers"], expected):
            response = error_response(403, ErrorCode.FORBIDDEN)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def route_path(scope: Scope) -> str:
    """Caminho que o roteador usa: o do scope sem o `root_path` na frente.

    O uvicorn com `--root-path /api/imago` põe o prefixo no `path` do scope (`/api/imago/me`),
    e o roteador do Starlette o tira antes de casar a rota. Sem o prefixo no `path` (o TestClient),
    o caminho é o próprio `path`. Mesma regra do `get_route_path` interno do Starlette.
    """
    path: str = scope["path"]
    root_path: str = scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        rest = path[len(root_path) :]
        if not rest or rest.startswith("/"):
            return rest
    return path


def origin_allowed(headers: Iterable[tuple[bytes, bytes]], expected: str) -> bool:
    """Diz se há exatamente um header `Origin` e ele é igual a `expected`."""
    # O ASGI entrega os nomes em minúsculas e os valores em bytes (latin-1 decodifica qualquer um)
    values = [value.decode("latin-1") for name, value in headers if name == _ORIGIN]
    # Dois headers Origin não acontecem num navegador: recusa em vez de escolher um
    return len(values) == 1 and values[0] == expected
