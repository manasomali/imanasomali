"""Contas de exemplo para desenvolvimento (`python -m app.cli seed`, só com `APP_ENV=dev`).

Os ids são fixos e fazem parte do contrato com as aplicações: o seed de cada uma (o do ethos, por
exemplo) cria os dados dela para estes mesmos ids, sem ler o banco do imago. Para entrar, peça um
código com o email (com `EMAIL_BACKEND=console`, ele sai no terminal do backend).

Todas nascem com a versão atual dos termos aceita. Ana é admin (com o evento `admin_created`,
como o `create-admin` faria).
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.db import require_write_transaction
from app.models import User, UserStatus
from app.terms import TERMS_VERSION


@dataclass(frozen=True, slots=True)
class SeedAccount:
    id: int
    email: str
    timezone: str
    locale: str
    is_admin: bool


# Ids e emails fixos, usados também pelos seeds das aplicações
SEED_ACCOUNTS: tuple[SeedAccount, ...] = (
    SeedAccount(101, "ana@example.com", "America/Sao_Paulo", "pt", is_admin=True),
    SeedAccount(102, "bia@example.com", "America/Sao_Paulo", "pt", is_admin=False),
    SeedAccount(103, "caio@example.com", "Europe/Lisbon", "en", is_admin=False),
)


def seed(session: Session, *, now: datetime) -> int | None:
    """Cria as contas de `SEED_ACCOUNTS` e devolve quantas. None (sem gravar nada) se alguma
    delas, pelo id ou pelo email, já existe. Exige `write_transaction`."""
    require_write_transaction(session)
    existing = session.scalar(
        select(func.count())
        .select_from(User)
        .where(
            or_(
                User.id.in_([account.id for account in SEED_ACCOUNTS]),
                User.email.in_([account.email for account in SEED_ACCOUNTS]),
            )
        )
    )
    if existing:
        return None
    for account in SEED_ACCOUNTS:
        session.add(
            User(
                id=account.id,
                email=account.email,
                status=UserStatus.ACTIVE.value,
                is_active=True,
                is_admin=account.is_admin,
                timezone=account.timezone,
                locale=account.locale,
                terms_version=TERMS_VERSION,
                terms_accepted_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    # As contas antes dos eventos, que apontam para elas (chave estrangeira)
    session.flush()
    for account in SEED_ACCOUNTS:
        if account.is_admin:
            audit.record(
                session, AuditEvent.ADMIN_CREATED, user_id=account.id, details={"via": "seed"}
            )
    return len(SEED_ACCOUNTS)
