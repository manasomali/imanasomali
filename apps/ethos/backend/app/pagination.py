"""Cursor das listagens paginadas por um instante e o id (marcações, histórico).

O cursor é opaco para o cliente: `"<microssegundos do instante desde 1970>.<id>"` da última linha
vista. A listagem continua a partir dele com uma comparação de chave (`(instante, id)` maior ou
menor que o do cursor), sem OFFSET: linhas novas que chegam entre uma página e outra não
empurram nem repetem as que já vieram.
"""

import re
from datetime import UTC, datetime, timedelta

from app.errors import ApiError, ErrorCode
from app.habits.access import MAX_ID

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)
_CURSOR_RE = re.compile(r"(-?[0-9]{1,18})\.([0-9]{1,19})")


def encode_cursor(instant: datetime, row_id: int) -> str:
    """Cursor da linha com esse instante (com fuso) e esse id."""
    return f"{(instant - _EPOCH) // _MICROSECOND}.{row_id}"


def decode_cursor(value: str) -> tuple[datetime, int]:
    """Instante (UTC) e id do cursor; cursor inválido dá 422 `validation_error` em `cursor`."""
    match = _CURSOR_RE.fullmatch(value)
    if match is None or int(match[2]) > MAX_ID:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, field="cursor")
    try:
        instant = _EPOCH + int(match[1]) * _MICROSECOND
    except OverflowError:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, field="cursor") from None
    return instant, int(match[2])
