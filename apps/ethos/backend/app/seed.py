"""Dados de exemplo para desenvolver: `python -m app.cli seed` (só com `APP_ENV=dev`).

Cria, numa transação só, três contas (`SEED_EMAILS`, com os termos atuais aceitos), hábitos que
cobrem os tipos de configuração (toggle e várias por dia; meta mínima, máxima; duração,
observação, pontuação, custo nos dois níveis; ativo, pausado e arquivado; compartilhado com
editor e viewer) e marcações nos últimos `SEED_DAYS` dias. As marcações seguem as regras da API
(`app/marks/service.py`: duração e custo resolvidos como na criação, auditoria `mark_created`),
cada uma às 12:00 (ou 08:00, 13:00 e 20:00 nos hábitos com várias por dia) do fuso do autor.

Não é idempotente por cópia: se alguma das contas de exemplo já existe, não grava nada e devolve
None (o CLI avisa). Para recriar, apague o banco de dev e rode as migrações de novo.

Para entrar como uma das contas, use o email dela no login; com `EMAIL_BACKEND=console`, o código
sai no terminal do servidor.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.config import Settings
from app.db import require_write_transaction
from app.habits.schemas import HabitCreate
from app.habits.service import check_config
from app.marks.service import insert_mark, mark_cost, mark_duration
from app.models import Habit, HabitMember, HabitPause, HabitStatus, MemberRole, User
from app.terms import TERMS_VERSION

ANA = "ana@example.com"
BIA = "bia@example.com"
CAIO = "caio@example.com"
SEED_EMAILS = (ANA, BIA, CAIO)
# Fuso e idioma de cada conta: o Caio fica em outro fuso, para ver o "dia vizinho"
_PROFILES = {
    ANA: ("America/Sao_Paulo", "pt"),
    BIA: ("America/Sao_Paulo", "pt"),
    CAIO: ("Europe/Lisbon", "en"),
}
# Dias com marcações, contando de ontem para trás
SEED_DAYS = 60
# Idade dos hábitos: criados antes das marcações, para a pontuação ter períodos
HABIT_AGE = timedelta(days=90)
PAUSED_FOR = timedelta(days=10)
ARCHIVED_FOR = timedelta(days=20)
_NOON = time(12)
_MULTI_HOURS = (time(8), time(13), time(20))


@dataclass(frozen=True, slots=True)
class SeedResult:
    users: int
    habits: int
    marks: int


@dataclass(frozen=True, slots=True)
class _Mark:
    author: str
    hour: time
    note: str | None = None
    cost_cents: int | None = None


# Marcações de um hábito no dia `day` (1 = ontem), num padrão fixo e variado
type _Pattern = Callable[[int], list[_Mark]]


@dataclass(frozen=True, slots=True)
class _SeedHabit:
    owner: str
    config: dict[str, Any]
    marks: _Pattern
    status: HabitStatus = HabitStatus.ACTIVE
    members: tuple[tuple[str, MemberRole], ...] = ()


def _every(step: int, author: str = ANA, *, after: int = 0) -> _Pattern:
    """Uma marcação ao meio-dia a cada `step` dias, só nos dias mais antigos que `after`."""
    return lambda day: [_Mark(author, _NOON)] if day % step == 0 and day > after else []


def _reading(day: int) -> list[_Mark]:
    # 0 a 2 por dia; a primeira do dia com observação
    return [
        _Mark(ANA, hour, note=f"Capítulo {day + index}" if index == 0 else None)
        for index, hour in enumerate(_MULTI_HOURS[: day % 3])
    ]


def _meditation(day: int) -> list[_Mark]:
    # Dono e editora se revezam; um dia em cada cinco fica sem
    if day % 5 == 0:
        return []
    return [_Mark(ANA if day % 2 else BIA, _NOON, note="Sessão guiada" if day % 6 else None)]


def _habits() -> tuple[_SeedHabit, ...]:
    return (
        _SeedHabit(
            ANA,
            {
                "name": "Exercício físico",
                "code": "EX",
                "color": "teal",
                "goal_type": "min",
                "goal_count": 3,
                "goal_period": "week",
                "duration_enabled": True,
                "duration_minutes": 30,
                "score_enabled": True,
                "reward": "Sobremesa no domingo",
            },
            lambda day: [_Mark(ANA, _NOON)] if day % 7 in (0, 2, 4, 5) else [],
        ),
        _SeedHabit(
            ANA,
            {
                "name": "Leitura",
                "color": "indigo",
                "goal_type": "min",
                "goal_count": 20,
                "goal_period": "month",
                "multi_mark": True,
                "notes_enabled": True,
            },
            _reading,
        ),
        _SeedHabit(
            ANA,
            {
                "name": "Não apostar",
                "color": "red",
                "goal_type": "max",
                "goal_count": 2,
                "goal_period": "month",
                "cost_enabled": True,
                "cost_level": "mark",
                "cost_cents": 2000,
                "cost_limit_cents": 5000,
                "cost_limit_period": "month",
                "score_enabled": True,
                "punishment": "Lavar a louça por uma semana",
            },
            # Custo próprio de cada aposta
            lambda day: (
                [_Mark(ANA, _NOON, cost_cents=1000 + day % 4 * 500)] if day % 9 == 0 else []
            ),
        ),
        _SeedHabit(
            ANA,
            {
                "name": "Coca-cola",
                "code": "COCA",
                "color": "amber",
                "goal_type": "max",
                "goal_count": 3,
                "goal_period": "week",
                "multi_mark": True,
                "cost_enabled": True,
                "cost_level": "habit",
                "cost_cents": 800,
                "cost_limit_cents": 3000,
                "cost_limit_period": "week",
            },
            # 0 a 2 por dia, fora de fase com a leitura
            lambda day: [_Mark(ANA, hour) for hour in _MULTI_HOURS[: (day + 1) % 3]],
        ),
        _SeedHabit(
            ANA,
            {
                "name": "Meditar",
                "color": "violet",
                "goal_type": "exact",
                "goal_count": 5,
                "goal_period": "week",
                "duration_enabled": True,
                "duration_minutes": 20,
                "notes_enabled": True,
                "score_enabled": True,
            },
            _meditation,
            members=((BIA, MemberRole.EDITOR), (CAIO, MemberRole.VIEWER)),
        ),
        _SeedHabit(
            ANA,
            {
                "name": "Inglês",
                "color": "blue",
                "goal_type": "min",
                "goal_count": 2,
                "goal_period": "week",
            },
            # Marcado até a pausa
            _every(3, after=PAUSED_FOR.days),
            status=HabitStatus.PAUSED,
        ),
        _SeedHabit(
            ANA,
            {
                "name": "Violão",
                "color": "orange",
                "goal_type": "min",
                "goal_count": 1,
                "goal_period": "week",
            },
            # Marcado até o arquivamento
            _every(4, after=ARCHIVED_FOR.days),
            status=HabitStatus.ARCHIVED,
        ),
        _SeedHabit(
            BIA,
            {
                "name": "Correr",
                "color": "green",
                "goal_type": "min",
                "goal_count": 2,
                "goal_period": "week",
            },
            _every(4, BIA),
            members=((ANA, MemberRole.VIEWER),),
        ),
    )


def seed(session: Session, settings: Settings, *, now: datetime) -> SeedResult | None:
    """Grava os dados de exemplo; None (sem gravar nada) se alguma conta de exemplo já existe.

    Exige `write_transaction` e `now` com fuso. Quem chama confere `settings.is_dev` antes.
    """
    require_write_transaction(session)
    if session.scalar(select(User.id).where(User.email.in_(SEED_EMAILS)).limit(1)) is not None:
        return None

    users: dict[str, User] = {}
    for email, (timezone, locale) in _PROFILES.items():
        users[email] = User(
            email=email,
            timezone=timezone,
            locale=locale,
            terms_version=TERMS_VERSION,
            terms_accepted_at=now,
        )
    session.add_all(users.values())
    session.flush()

    marks = 0
    seeds = _habits()
    for item in seeds:
        habit = _add_habit(session, settings, item, users, now=now)
        for day in range(1, SEED_DAYS + 1):
            for mark in item.marks(day):
                author = users[mark.author]
                tz = ZoneInfo(author.timezone)
                local_day = now.astimezone(tz).date() - timedelta(days=day)
                marked_at = datetime.combine(local_day, mark.hour, tzinfo=tz).astimezone(UTC)
                insert_mark(
                    session,
                    habit.id,
                    user_id=author.id,
                    marked_at=marked_at,
                    note=mark.note,
                    duration_minutes=mark_duration(habit, None),
                    cost_cents=mark_cost(habit, mark.cost_cents),
                    ip=None,
                )
                marks += 1
    return SeedResult(users=len(users), habits=len(seeds), marks=marks)


def _add_habit(
    session: Session,
    settings: Settings,
    item: _SeedHabit,
    users: dict[str, User],
    *,
    now: datetime,
) -> Habit:
    # Mesma validação da API: campo a campo (HabitCreate) e a configuração inteira
    config = HabitCreate.model_validate(item.config).model_dump(mode="json")
    check_config(config, set(config), settings)
    owner = users[item.owner]
    habit = Habit(owner_id=owner.id, created_at=now - HABIT_AGE, status=item.status.value, **config)
    if item.status is HabitStatus.ARCHIVED:
        habit.archived_at = now - ARCHIVED_FOR
    session.add(habit)
    session.flush()
    if item.status is HabitStatus.PAUSED:
        # Pausado tem exatamente uma pausa aberta
        session.add(HabitPause(habit_id=habit.id, started_at=now - PAUSED_FOR))
    for email, role in item.members:
        session.add(HabitMember(habit_id=habit.id, user_id=users[email].id, role=role.value))
    audit.record(
        session,
        AuditEvent.HABIT_CREATED,
        user_id=owner.id,
        habit_id=habit.id,
        details={"via": "seed"},
    )
    return habit
