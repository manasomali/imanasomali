"""Fábricas e atalhos de banco compartilhados pelos testes.

- `new_user(email, **campos)` / `new_habit(dono, **campos)`: objetos válidos, ainda não salvos;
- `save(session, *objetos)`: grava num `write_transaction` próprio;
- `count(session, Modelo, *where)`: quantas linhas batem.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import write_transaction
from app.models import Habit, User

TERMS_ACCEPTED_AT = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def new_user(email: str = "ana@example.com", **fields: Any) -> User:
    values: dict[str, Any] = {
        "email": email,
        "timezone": "America/Sao_Paulo",
        "locale": "pt",
        "terms_version": "2026-01",
        "terms_accepted_at": TERMS_ACCEPTED_AT,
    }
    return User(**(values | fields))


def new_habit(owner: User, **fields: Any) -> Habit:
    values: dict[str, Any] = {
        "owner_id": owner.id,
        "name": "Exercício",
        "color": "teal",
        "goal_type": "min",
        "goal_count": 3,
        "goal_period": "week",
    }
    return Habit(**(values | fields))


def save(session: Session, *objects: Any) -> None:
    with write_transaction(session):
        session.add_all(objects)


def count(session: Session, model: Any, *where: Any) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where))
