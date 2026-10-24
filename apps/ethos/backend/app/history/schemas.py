"""Resposta de `GET /history`. As regras (eventos, acesso, `details`) ficam em `service.py`."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.history.service import HistoryEvent
from app.marks.schemas import Author


class HistoryHabit(BaseModel):
    id: int
    # A sigla, se definida, senão o nome (como o `label` do `GET /habits`)
    label: str


class HistoryEntryOut(BaseModel):
    id: int
    event: HistoryEvent
    # Quando aconteceu, em UTC
    created_at: datetime
    habit: HistoryHabit
    # Quem fez; null quando a conta foi apagada ("usuário removido")
    author: Author | None
    # Só as chaves públicas do evento (`service.PUBLIC_DETAILS`)
    details: dict[str, Any]


class HistoryList(BaseModel):
    events: list[HistoryEntryOut]
    # Passe em `?cursor=` (com os mesmos filtros) para a próxima página; null na última
    next_cursor: str | None
