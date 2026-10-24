"""Endpoints da configuração de alerta do usuário logado num hábito (ETH-26).

Ambos exigem `CurrentUser`; sem acesso ao hábito, 404 `not_found`; viewer, 403 `forbidden`.

- `GET /habits/{id}/alerts`: a configuração (`AlertOut`); sem nada salvo, a padrão (desligada).
- `PUT /habits/{id}/alerts`: troca a configuração inteira (`AlertConfig`) e devolve a nova.
  Arquivado: 409 `habit_archived`. Campo inválido: 422 com o `field`.

As regras ficam em `service.py`.
"""

from fastapi import APIRouter, Request

from app.alerts import service
from app.alerts.schemas import AlertConfig, AlertOut
from app.alerts.service import AlertSettings
from app.auth.deps import CurrentUser
from app.db import SessionDep
from app.habits.access import HabitId
from app.models import utcnow
from app.request_info import client_ip

router = APIRouter(prefix="/habits", tags=["alerts"])


def alert_out(settings: AlertSettings) -> AlertOut:
    return AlertOut(
        goal_enabled=settings.goal_enabled,
        cost_enabled=settings.cost_enabled,
        hour=settings.hour,
        frequency=settings.frequency,
        weekday=settings.weekday,
        last_sent_at=settings.last_sent_at,
    )


@router.get("/{habit_id}/alerts")
def get_alert(habit_id: HabitId, user: CurrentUser, session: SessionDep) -> AlertOut:
    return alert_out(service.get_alert(session, user_id=user.id, habit_id=habit_id))


@router.put("/{habit_id}/alerts")
def save_alert(
    habit_id: HabitId,
    body: AlertConfig,
    user: CurrentUser,
    request: Request,
    session: SessionDep,
) -> AlertOut:
    settings = service.save_alert(
        session,
        user_id=user.id,
        habit_id=habit_id,
        values=body.model_dump(),
        ip=client_ip(request),
        now=utcnow(),
    )
    return alert_out(settings)
