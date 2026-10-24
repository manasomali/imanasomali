"""Regras de criar, editar, apagar e listar hábitos (ETH-20).

Cada função de escrita abre o próprio `write_transaction` (BEGIN IMMEDIATE) e faz dentro dele as
leituras que decidem a escrita: acesso, limite de hábitos e a configuração atual. Erros de regra
saem como `ApiError` e desfazem a transação.

- Criar: `MAX_HABITS_PER_USER` conta os hábitos ativos e pausados do dono (arquivados não
  contam; hábitos dos outros, compartilhados com ele, também não), na mesma transação do INSERT.
  Duas criações em paralelo no limite não passam dele: a segunda espera a trava da primeira e
  conta de novo. Acima do limite: 409 `habit_limit_reached`.
- Editar: só o dono. A configuração inteira depois da mudança passa por `check_config`. Desligar
  um recurso não apaga nada (nem no hábito nem nas marcações): o valor fica guardado, é ignorado
  pela pontuação e volta ao religar. Cada campo que mudou vai para o `audit_log`
  (`habit_updated`, `{"changes": [{"field", "old", "new"}]}`; a descrição, longa, vai só com
  `{"field": "description"}`); sem mudança, nada é gravado.
- Apagar: só o dono. O banco apaga em cascata marcações, pausas, membros, convites, alertas e a
  auditoria do hábito. O evento `habit_deleted` vai com `habit_id=None` e o id em `details`,
  para sobreviver ao CASCADE. Devolve os membros, que recebem o email depois do commit.
- Listar: os hábitos do usuário e os compartilhados com ele, com o papel, numa consulta só.
"""

from collections.abc import Mapping, Set
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.config import Settings
from app.db import write_transaction
from app.errors import ApiError, ErrorCode
from app.habits.access import HabitAccess, HabitRole, get_habit_access, require_owner
from app.habits.schemas import CONFIG_FIELDS
from app.mail.language import Locale, pick_locale
from app.models import CostLevel, GoalType, Habit, HabitMember, HabitStatus, Period, User

# Dias do período usados no teto de N: o menor mês (28) para a meta ser sempre possível
PERIOD_DAYS = {Period.WEEK: 7, Period.MONTH: 28, Period.YEAR: 365}
# Status que contam no limite de hábitos por usuário
COUNTED_STATUSES = (HabitStatus.ACTIVE.value, HabitStatus.PAUSED.value)
# Recursos que só valem com a pontuação ligada
SCORE_ONLY_FIELDS = ("reward", "punishment")
# Campos que vão para a auditoria sem o valor antigo e o novo (ver _change)
VALUELESS_CHANGES = frozenset({"description"})


def _invalid(field: str) -> ApiError:
    return ApiError(422, ErrorCode.VALIDATION_ERROR, field=field)


def max_goal_count(goal_period: str, multi_mark: bool, settings: Settings) -> int:
    """Teto de N: dias do período no toggle; `MAX_MARKS_PER_DAY` x dias com várias por dia."""
    days = PERIOD_DAYS[Period(goal_period)]
    return days * settings.max_marks_per_day if multi_mark else days


def check_config(values: Mapping[str, Any], changed: Set[str], settings: Settings) -> None:
    """Regras entre campos da configuração inteira `values` (422 `validation_error` com o campo).

    `changed`: campos que a request mudou. Recompensa e punição só podem ganhar valor com a
    pontuação ligada; um valor já guardado fica (desligar a pontuação não o apaga).
    """
    goal_count = values["goal_count"]
    minimum = 0 if values["goal_type"] == GoalType.MAX else 1
    maximum = max_goal_count(values["goal_period"], values["multi_mark"], settings)
    if not minimum <= goal_count <= maximum:
        raise _invalid("goal_count")
    if values["duration_enabled"] and values["duration_minutes"] is None:
        raise _invalid("duration_minutes")
    if not values["score_enabled"]:
        for name in SCORE_ONLY_FIELDS:
            if name in changed and values[name] is not None:
                raise _invalid(name)
    # Nível hábito: todo mundo que marca gera o custo fixo, então ele precisa existir
    if (
        values["cost_enabled"]
        and values["cost_level"] == CostLevel.HABIT
        and values["cost_cents"] is None
    ):
        raise _invalid("cost_cents")
    # Limite e período do limite vêm juntos ou não vêm
    if values["cost_limit_cents"] is None and values["cost_limit_period"] is not None:
        raise _invalid("cost_limit_cents")
    if values["cost_limit_cents"] is not None and values["cost_limit_period"] is None:
        raise _invalid("cost_limit_period")


def _change(name: str, old: Any, new: Any) -> dict[str, Any]:
    """Item de `{"changes": [...]}` do `habit_updated`.

    A descrição (até 500 caracteres) entra só pelo nome: com os valores, uma edição de todos os
    textos cheios de emoji (12 caracteres cada no JSON) passaria do tamanho máximo do `details`.
    """
    if name in VALUELESS_CHANGES:
        return {"field": name}
    return {"field": name, "old": old, "new": new}


def _config(habit: Habit) -> dict[str, Any]:
    return {name: getattr(habit, name) for name in CONFIG_FIELDS}


def count_owned_habits(session: Session, owner_id: int) -> int:
    """Hábitos do dono que contam no `MAX_HABITS_PER_USER`: ativos e pausados."""
    return session.scalar(
        select(func.count())
        .select_from(Habit)
        .where(Habit.owner_id == owner_id, Habit.status.in_(COUNTED_STATUSES))
    )


def create_habit(
    session: Session,
    settings: Settings,
    *,
    owner_id: int,
    values: Mapping[str, Any],
    ip: str | None,
) -> Habit:
    """Cria o hábito com a configuração `values` (todos os `CONFIG_FIELDS`, em valores simples).

    Levanta 422 (`check_config`) ou 409 `habit_limit_reached`.
    """
    config = {name: values[name] for name in CONFIG_FIELDS}
    check_config(config, set(CONFIG_FIELDS), settings)
    with write_transaction(session):
        if count_owned_habits(session, owner_id) >= settings.max_habits_per_user:
            raise ApiError(409, ErrorCode.HABIT_LIMIT_REACHED)
        habit = Habit(owner_id=owner_id, **config)
        session.add(habit)
        session.flush()
        audit.record(session, AuditEvent.HABIT_CREATED, user_id=owner_id, ip=ip, habit_id=habit.id)
    return habit


def update_habit(
    session: Session,
    settings: Settings,
    *,
    user_id: int,
    habit_id: int,
    values: Mapping[str, Any],
    ip: str | None,
) -> HabitAccess:
    """Aplica a mudança parcial `values` (só os campos enviados, em valores simples).

    Levanta 404 (sem acesso), 403 (não é o dono) ou 422 (`check_config`).
    """
    with write_transaction(session):
        access = get_habit_access(session, habit_id, user_id)
        habit = require_owner(access)
        current = _config(habit)
        changed = {name for name, value in values.items() if current[name] != value}
        check_config(current | dict(values), changed, settings)
        changes = []
        for name in CONFIG_FIELDS:
            if name in changed:
                changes.append(_change(name, current[name], values[name]))
                setattr(habit, name, values[name])
        if changes:
            audit.record(
                session,
                AuditEvent.HABIT_UPDATED,
                user_id=user_id,
                ip=ip,
                habit_id=habit_id,
                details={"changes": changes},
            )
    return access


@dataclass(frozen=True, slots=True)
class Recipient:
    """Destino de um email, já com o idioma escolhido."""

    email: str
    locale: Locale


@dataclass(frozen=True, slots=True)
class DeletedHabit:
    name: str
    # Membros (editores e viewers) que perderam o hábito: cada um recebe o email
    members: tuple[Recipient, ...]


def delete_habit(session: Session, *, user_id: int, habit_id: int, ip: str | None) -> DeletedHabit:
    """Apaga o hábito e tudo o que é dele. Levanta 404 (sem acesso) ou 403 (não é o dono)."""
    with write_transaction(session):
        habit = require_owner(get_habit_access(session, habit_id, user_id))
        name = habit.name
        rows = session.execute(
            select(User.email, User.locale)
            .join(HabitMember, HabitMember.user_id == User.id)
            .where(HabitMember.habit_id == habit_id)
            .order_by(User.id)
        ).all()
        session.execute(
            delete(Habit).where(Habit.id == habit_id),
            execution_options={"synchronize_session": False},
        )
        session.expunge(habit)
        audit.record(
            session,
            AuditEvent.HABIT_DELETED,
            user_id=user_id,
            ip=ip,
            details={"habit_id": habit_id},
        )
    members = tuple(Recipient(email, pick_locale(locale)) for email, locale in rows)
    return DeletedHabit(name=name, members=members)


def list_habits(session: Session, user_id: int) -> list[HabitAccess]:
    """Hábitos do usuário e os compartilhados com ele, com o papel, em ordem de criação."""
    shared = select(HabitMember.habit_id).where(HabitMember.user_id == user_id)
    rows = session.execute(
        select(Habit, HabitMember.role)
        .outerjoin(
            HabitMember,
            and_(HabitMember.habit_id == Habit.id, HabitMember.user_id == user_id),
        )
        .where(or_(Habit.owner_id == user_id, Habit.id.in_(shared)))
        .order_by(Habit.id)
        .execution_options(populate_existing=True)
    ).all()
    # A consulta só traz hábitos do usuário ou em que ele é membro (member_role preenchido)
    return [
        HabitAccess(habit, HabitRole.OWNER if habit.owner_id == user_id else HabitRole(member_role))
        for habit, member_role in rows
    ]
