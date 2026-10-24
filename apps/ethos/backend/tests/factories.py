"""Fábricas e atalhos de banco compartilhados pelos testes.

- `new_user(email, **campos)` / `new_habit(dono, **campos)`: objetos válidos, ainda não salvos;
- `new_member(hábito, usuário, papel)`, `new_mark(hábito, marked_at, **campos)` e
  `new_pause(hábito, started_at, ended_at=None)`: idem, para compartilhamento, marcações e pausas
  enquanto a API delas não existe (ou para montar cenários direto no banco);
- `save(session, *objetos)`: grava num `write_transaction` próprio;
- `count(session, Modelo, *where)`: quantas linhas batem.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import write_transaction
from app.models import Habit, HabitMember, HabitPause, Mark, User

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


def new_member(habit: Habit, user: User, role: str = "editor", **fields: Any) -> HabitMember:
    return HabitMember(**({"habit_id": habit.id, "user_id": user.id, "role": role} | fields))


def new_mark(habit: Habit, marked_at: datetime, **fields: Any) -> Mark:
    return Mark(**({"habit_id": habit.id, "marked_at": marked_at} | fields))


def new_pause(habit: Habit, started_at: datetime, ended_at: datetime | None = None) -> HabitPause:
    return HabitPause(habit_id=habit.id, started_at=started_at, ended_at=ended_at)


def save(session: Session, *objects: Any) -> None:
    with write_transaction(session):
        session.add_all(objects)


def count(session: Session, model: Any, *where: Any) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where))
