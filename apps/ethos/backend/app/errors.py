"""Catálogo de códigos de erro da API e os handlers que formatam toda resposta de erro.

Toda resposta de erro sai como {"error": "<codigo>", "field": "<campo>" | null}: os erros do app
(ApiError), as HTTPException do FastAPI e do Starlette (404 de rota, 405), a validação do FastAPI
(422) e qualquer exceção não tratada (500). A API nunca manda mensagem pronta para o usuário: o
front traduz o código pelo translation.json, então todo código novo entra aqui e lá.
"""

from collections.abc import Mapping
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    # Genéricos, um por status HTTP que o FastAPI/Starlette ou o app podem devolver
    BAD_REQUEST = "bad_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    VALIDATION_ERROR = "validation_error"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    # Específicos
    DATABASE_UNAVAILABLE = "database_unavailable"
    # Código de login errado, vencido, já usado, esgotado (5 tentativas) ou de conta bloqueada:
    # uma resposta só, para não dizer qual foi o caso nem se a conta existe
    INVALID_CODE = "invalid_code"
    # Fuso IANA desconhecido no primeiro acesso (conta existente ignora o fuso do verify)
    INVALID_TIMEZONE = "invalid_timezone"
    # Sessão válida, mas a versão atual dos termos não foi aceita: o front mostra os termos e
    # chama POST /auth/me/terms (403 nos endpoints do app; /auth/me e o logout funcionam)
    TERMS_NOT_ACCEPTED = "terms_not_accepted"
    # Criar outro hábito passaria do MAX_HABITS_PER_USER (ativos + pausados do dono): 409
    HABIT_LIMIT_REACHED = "habit_limit_reached"
    # Escrita num hábito arquivado, que é só leitura (desarquivar e apagar continuam): 409
    HABIT_ARCHIVED = "habit_archived"


# Código de uma HTTPException pelo status. Status fora da tabela cai no genérico da faixa
_STATUS_CODES = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}

# Primeiro item do loc de um erro de validação: de onde veio o valor, não o nome do campo
_REQUEST_PARTS = frozenset({"body", "query", "path", "header", "cookie"})


class ApiError(Exception):
    """Erro de regra do app. Vira {"error": code, "field": field} com o status dado."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        field: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not 400 <= status_code <= 599:
            raise ValueError(f"status de erro fora de 4xx/5xx: {status_code}")
        super().__init__(code.value)
        self.status_code = status_code
        self.code = code
        self.field = field
        self.headers = headers


def error_response(
    status_code: int,
    code: ErrorCode,
    field: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": code.value, "field": field},
        headers=headers,
    )


def code_for_status(status_code: int) -> ErrorCode:
    if status_code in _STATUS_CODES:
        return _STATUS_CODES[status_code]
    return ErrorCode.INTERNAL_ERROR if status_code >= 500 else ErrorCode.BAD_REQUEST


def validation_field(exc: RequestValidationError) -> str | None:
    """Campo do primeiro erro de validação, ex.: "email" ou "habits.0.name"; None se não houver."""
    errors = exc.errors()
    if not errors:
        return None
    first = errors[0]
    # JSON malformado: o loc traz a posição do erro no texto, não um campo
    if first.get("type") == "json_invalid":
        return None
    loc = [str(part) for part in first.get("loc", ())]
    if loc and loc[0] in _REQUEST_PARTS:
        loc = loc[1:]
    return ".".join(loc) or None


async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.field, exc.headers)


async def _http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # O detail é ignorado: mensagem pronta não sai na API (headers como o Allow do 405, sim)
    return error_response(exc.status_code, code_for_status(exc.status_code), headers=exc.headers)


async def _validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # O valor recebido não volta na resposta nem vai para o log
    return error_response(422, ErrorCode.VALIDATION_ERROR, validation_field(exc))


async def _unhandled_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
    # O Starlette ainda propaga a exceção depois desta resposta, e o uvicorn registra o traceback
    return error_response(500, ErrorCode.INTERNAL_ERROR)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
