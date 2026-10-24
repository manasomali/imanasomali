"""Limite de convites por dono (`MAX_INVITES_PER_DAY`), contado pelo `audit_log`.

O convite pendente é uma linha de `habit_invites` que sai ao ser aceito, recusado ou cancelado
(ETH-12): contar essas linhas deixaria o dono convidar de novo a cada recusa ou cancelamento. Por
isso o limite conta os eventos `invite_created` do dono, somando todos os hábitos, nas últimas
24 h (`INVITE_WINDOW`, janela móvel: não depende do fuso de ninguém nem libera 20 convites de uma
vez à meia-noite). A retenção (`app/retention.py`) só apaga eventos de auth, então esses ficam.

O `ON DELETE CASCADE` de `audit_log.habit_id` apaga esses eventos junto com o hábito. Para que
criar, convidar e apagar hábitos em sequência não fure o limite, o `habit_deleted` (que sobrevive
ao hábito, com `habit_id=None`) leva em `details` quantos convites do hábito entraram na janela
(`RECENT_INVITES_KEY`), e a conta soma esse número enquanto o `habit_deleted` estiver na janela.
É conservador: esses convites contam até 24 h depois da exclusão, não 24 h depois de cada um.

As duas funções leem dentro do `write_transaction` de quem decide (convidar ou apagar o hábito),
para que a conta e a escrita fiquem na mesma trava.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import AuditEvent
from app.models import AuditLog

INVITE_WINDOW = timedelta(days=1)
# Chave do `details` do `habit_deleted` com os convites do hábito apagado ainda na janela
RECENT_INVITES_KEY = "recent_invites"


def habit_recent_invites(session: Session, habit_id: int, *, now: datetime) -> int:
    """Convites criados no hábito na janela que termina em `now`."""
    return session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.habit_id == habit_id,
            AuditLog.event == AuditEvent.INVITE_CREATED.value,
            AuditLog.created_at >= now - INVITE_WINDOW,
        )
    )


def count_recent_invites(session: Session, owner_id: int, *, now: datetime) -> int:
    """Convites do dono na janela que termina em `now`, inclusive os de hábitos já apagados."""
    since = now - INVITE_WINDOW
    created = session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.user_id == owner_id,
            AuditLog.event == AuditEvent.INVITE_CREATED.value,
            AuditLog.created_at >= since,
        )
    )
    deleted = session.scalar(
        select(func.coalesce(func.sum(AuditLog.details[RECENT_INVITES_KEY].as_integer()), 0)).where(
            AuditLog.user_id == owner_id,
            AuditLog.event == AuditEvent.HABIT_DELETED.value,
            AuditLog.created_at >= since,
        )
    )
    return created + deleted
