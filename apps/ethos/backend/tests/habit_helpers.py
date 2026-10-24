"""Atalhos dos testes da API de hábitos (ETH-20 em diante).

- `Account(user, headers)`: usuário com sessão aberta; `headers` leva o cookie dela. A fixture
  `make_account(email, **campos)` do `conftest.py` cria uma, já com os termos atuais aceitos;
- `VALID`: corpo mínimo válido de `POST /habits`; `create(client, conta, **campos)` faz o POST e
  `created(...)` confere o 201 e devolve o JSON;
- `stored(session, id)`: o hábito relido do banco (None se não existe);
- `events(session, AuditEvent.X)`: linhas do `audit_log` desse evento, em ordem;
- `share(session, id, conta, papel)`: torna a conta membro do hábito;
- `NOT_FOUND`, `FORBIDDEN` e `invalid(campo)`: corpos de erro esperados.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import AuditEvent
from app.models import AuditLog, Habit, User
from tests.factories import new_member, save

VALID = {
    "name": "Exercício",
    "color": "teal",
    "goal_type": "min",
    "goal_count": 3,
    "goal_period": "week",
}
NOT_FOUND = {"error": "not_found", "field": None}
FORBIDDEN = {"error": "forbidden", "field": None}


def invalid(field: str) -> dict:
    return {"error": "validation_error", "field": field}


@dataclass
class Account:
    user: User
    headers: dict[str, str]


def create(client, account: Account, **fields):
    return client.post("/habits", json=VALID | fields, headers=account.headers)


def created(client, account: Account, **fields) -> dict:
    response = create(client, account, **fields)
    assert response.status_code == 201, response.json()
    return response.json()


def stored(db_session: Session, habit_id: int) -> Habit | None:
    db_session.rollback()
    query = select(Habit).where(Habit.id == habit_id).execution_options(populate_existing=True)
    return db_session.scalar(query)


def events(db_session: Session, name: AuditEvent) -> list[AuditLog]:
    db_session.rollback()
    query = select(AuditLog).where(AuditLog.event == name.value).order_by(AuditLog.id)
    return list(db_session.scalars(query.execution_options(populate_existing=True)))


def share(db_session: Session, habit_id: int, account: Account, role: str) -> None:
    habit = stored(db_session, habit_id)
    save(db_session, new_member(habit, account.user, role))
