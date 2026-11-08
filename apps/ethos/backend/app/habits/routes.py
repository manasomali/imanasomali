"""Endpoints de `/habits`: criar, listar, ver, editar, apagar, pausar e arquivar (ETH-20 e 21).

Todos exigem `CurrentUser`. As regras ficam em `app/habits/service.py` e o acesso em
`app/habits/access.py`; aqui só a entrada, a pontuação da resposta e os emails depois do commit.

- `GET /habits`: `{"habits": [...]}`, os hábitos do usuário e os compartilhados com ele, cada um
  com o `role` dele (`owner`, `editor`, `viewer`). Por padrão, os ativos e pausados; com
  `?archived=true`, só os arquivados.
- `POST /habits`: 201 com o hábito. Limite de hábitos: 409 `habit_limit_reached`.
- `GET /habits/{id}`: o hábito. Sem acesso (ou id que não existe): 404 `not_found`.
- `PATCH /habits/{id}`: mudança parcial, só o dono (editor e viewer: 403 `forbidden`). Arquivado
  é só leitura: 409 `habit_archived`.
- `DELETE /habits/{id}`: 204, só o dono, inclusive arquivado. Os membros recebem o email "hábito
  apagado".
- `POST /habits/{id}/pause`, `/resume`, `/archive`, `/unarchive`: só o dono, sem corpo; devolvem o
  hábito. Pedir o estado atual não muda nada. Pausar e retomar um arquivado: 409
  `habit_archived`. Desarquivar acima do limite de hábitos: 409 `habit_limit_reached`. Regras em
  `service.py`.

Campo inválido: 422 `validation_error` com o `field`. Pontuação (`score`: `value` e `success`)
só com `score_enabled`, calculada pelo `score.py` no fuso de quem pede; desligada, a chave nem
aparece.
"""

from functools import partial
from typing import Annotated, Protocol
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Query
from sqlalchemy.orm import Session

from app.config import SettingsDep
from app.db import SessionDep
from app.habits import service
from app.habits.access import HabitAccess, HabitId, HabitRole, get_habit_access
from app.habits.schemas import (
    CONFIG_FIELDS,
    HabitCreate,
    HabitList,
    HabitOut,
    HabitScore,
    HabitUpdate,
)
from app.habits.scoring import evaluate_habits
from app.identity import CurrentUser, Identity
from app.mail.catalog import HabitDeleted
from app.mail.sender import MailerDep, schedule_email
from app.models import utcnow

router = APIRouter(prefix="/habits", tags=["habits"])


def habit_out(access: HabitAccess, score: HabitScore | None) -> HabitOut:
    habit = access.habit
    return HabitOut.model_validate(
        {
            "id": habit.id,
            "role": access.role,
            "label": habit.code or habit.name,
            "status": habit.status,
            "archived_at": habit.archived_at,
            "created_at": habit.created_at,
            "updated_at": habit.updated_at,
            "score": score,
            **{name: getattr(habit, name) for name in CONFIG_FIELDS},
        }
    )


def present(session: Session, accesses: list[HabitAccess], timezone: str) -> list[HabitOut]:
    """As respostas, com a pontuação dos hábitos que a têm ligada (2 consultas no total)."""
    scored = [access.habit for access in accesses if access.habit.score_enabled]
    evaluations = evaluate_habits(session, scored, ZoneInfo(timezone), now=utcnow())
    result = []
    for access in accesses:
        evaluation = evaluations.get(access.habit.id)
        score = None
        if evaluation is not None:
            score = HabitScore(value=evaluation.score, success=evaluation.success)
        result.append(habit_out(access, score))
    return result


@router.get("")
def list_habits(
    user: CurrentUser, session: SessionDep, archived: Annotated[bool, Query()] = False
) -> HabitList:
    accesses = service.list_habits(session, user.id, archived=archived)
    return HabitList(habits=present(session, accesses, user.timezone))


@router.post("", status_code=201)
def create_habit(
    body: HabitCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> HabitOut:
    habit = service.create_habit(
        session,
        settings,
        owner_id=user.id,
        values=body.model_dump(mode="json"),
    )
    access = HabitAccess(habit, HabitRole.OWNER)
    [out] = present(session, [access], user.timezone)
    return out


@router.get("/{habit_id}")
def get_habit(habit_id: HabitId, user: CurrentUser, session: SessionDep) -> HabitOut:
    access = get_habit_access(session, habit_id, user.id)
    [out] = present(session, [access], user.timezone)
    return out


@router.patch("/{habit_id}")
def update_habit(
    habit_id: HabitId,
    body: HabitUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> HabitOut:
    access = service.update_habit(
        session,
        settings,
        user_id=user.id,
        habit_id=habit_id,
        values=body.model_dump(mode="json", exclude_unset=True),
    )
    [out] = present(session, [access], user.timezone)
    return out


@router.delete("/{habit_id}", status_code=204)
def delete_habit(
    habit_id: HabitId,
    user: CurrentUser,
    session: SessionDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> None:
    deleted = service.delete_habit(session, user_id=user.id, habit_id=habit_id)
    # A transação já fechou: os emails saem depois da resposta
    for member in deleted.members:
        schedule_email(
            background_tasks,
            mailer,
            member.user_id,
            member.locale,
            HabitDeleted(habit_name=deleted.name),
        )


class StatusAction(Protocol):
    """Regra do `service` que muda o status: pausar, retomar, arquivar ou desarquivar."""

    def __call__(self, session: Session, *, user_id: int, habit_id: int) -> HabitAccess: ...


def _change_status(
    action: StatusAction, habit_id: int, user: Identity, session: Session
) -> HabitOut:
    access = action(session, user_id=user.id, habit_id=habit_id)
    [out] = present(session, [access], user.timezone)
    return out


@router.post("/{habit_id}/pause")
def pause_habit(habit_id: HabitId, user: CurrentUser, session: SessionDep) -> HabitOut:
    return _change_status(service.pause_habit, habit_id, user, session)


@router.post("/{habit_id}/resume")
def resume_habit(habit_id: HabitId, user: CurrentUser, session: SessionDep) -> HabitOut:
    return _change_status(service.resume_habit, habit_id, user, session)


@router.post("/{habit_id}/archive")
def archive_habit(habit_id: HabitId, user: CurrentUser, session: SessionDep) -> HabitOut:
    return _change_status(service.archive_habit, habit_id, user, session)


@router.post("/{habit_id}/unarchive")
def unarchive_habit(
    habit_id: HabitId,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> HabitOut:
    action = partial(service.unarchive_habit, settings=settings)
    return _change_status(action, habit_id, user, session)
