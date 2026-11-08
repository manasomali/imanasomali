"""Tamanho máximo do corpo de qualquer request: 100 KB (`MAX_BODY_BYTES`).

O maior corpo que o imago aceita é o do `POST /internal/mail` (assunto, texto e HTML de um email),
limitado a 100 KB pelo contrato da API interna; os corpos da API pública são bem menores. O limite
vale para todas as rotas e é conferido antes de ler o corpo, pelo `Content-Length`:

- `Content-Length` acima do limite, malformado ou repetido com valores diferentes: 422
  `validation_error`, sem ler o corpo;
- corpo sem `Content-Length` (`Transfer-Encoding: chunked`): 422. Nenhum cliente do imago manda
  assim: o nginx repassa com `Content-Length` (HTTP/1.0 até o backend) e o httpx das aplicações
  também, num JSON. Recusar é o jeito de garantir o limite sem contar os bytes no meio da leitura.

O servidor (h11, no uvicorn) não deixa o corpo passar do `Content-Length` declarado, então
conferir o header basta.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

from app.errors import ErrorCode, error_response

MAX_BODY_BYTES = 100 * 1024

_CONTENT_LENGTH = b"content-length"
_TRANSFER_ENCODING = b"transfer-encoding"
_MAX_LENGTH_DIGITS = 18


class BodyLimitMiddleware:
    """Middleware ASGI: 422 para corpo maior que `MAX_BODY_BYTES` ou sem `Content-Length`."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self._allowed(scope["headers"]):
            response = error_response(422, ErrorCode.VALIDATION_ERROR)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _allowed(self, headers: list[tuple[bytes, bytes]]) -> bool:
        lengths = {value.strip() for name, value in headers if name == _CONTENT_LENGTH}
        if any(name == _TRANSFER_ENCODING for name, _ in headers):
            return False
        if not lengths:
            return True
        if len(lengths) > 1:
            return False
        [length] = lengths
        # bytes.isdigit só aceita 0-9. O tamanho antes do int(): um número com milhares de
        # dígitos levantaria ValueError (limite de conversão do Python) em vez de ser recusado
        return (
            len(length) <= _MAX_LENGTH_DIGITS and length.isdigit() and int(length) <= self.max_bytes
        )
