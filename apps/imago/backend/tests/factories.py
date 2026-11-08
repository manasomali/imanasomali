"""Fábricas e atalhos de banco compartilhados pelos testes.

- `new_user(email, **campos)`: conta válida, ainda não salva, com um id aleatório (como a do
  login) se `id` não vier;
- `save(session, *objetos)`: grava num `write_transaction` próprio;
- `count(session, Modelo, *where)`: quantas linhas batem.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.security import generate_account_id
from app.db import write_transaction
from app.models import User

TERMS_ACCEPTED_AT = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def new_user(email: str = "ana@example.com", **fields: Any) -> User:
    values: dict[str, Any] = {
        "id": generate_account_id(),
        "email": email,
        "timezone": "America/Sao_Paulo",
        "locale": "pt",
        "terms_version": "2026-01-01",
        "terms_accepted_at": TERMS_ACCEPTED_AT,
    }
    return User(**(values | fields))


def save(session: Session, *objects: Any) -> None:
    with write_transaction(session):
        session.add_all(objects)


def count(session: Session, model: Any, *where: Any) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where))
