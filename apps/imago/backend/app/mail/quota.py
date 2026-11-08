"""Teto de envio de email, um só para o imago e todas as aplicações (ETH-58).

Contado pelas linhas de `mail_log` (aplicação, tipo e instante, nunca o destinatário) em duas
janelas móveis: as últimas 24 h e a última 1 h. Janela móvel, e não "o dia de hoje": assim o envio
nunca passa da cota diária do provedor, seja qual for a hora em que ela zera.

- `code` (códigos de login e de exclusão) e `account` (conta excluída, troca de email): recusados
  quando a janela de 24 h chega a `MAX_EMAILS_PER_DAY` ou a de 1 h chega a `MAX_EMAILS_PER_HOUR`;
- `notification` (emails das aplicações): recusados antes, quando a janela de 24 h chega a
  `MAX_EMAILS_PER_DAY - MAIL_RESERVED_FOR_CODES_PER_DAY` ou a de 1 h chega a
  `MAX_EMAILS_PER_HOUR - MAIL_RESERVED_FOR_CODES_PER_HOUR`. O fim de cada janela fica para os
  códigos: notificações num horário cheio não deixam ninguém sem código de login.

As contagens somam todos os tipos e todas as aplicações. Tudo roda dentro do `write_transaction`
(BEGIN IMMEDIATE) de quem chama: `reserve` confere o teto e grava a linha na mesma transação,
antes do SMTP, então envios em paralelo esperam a vez e nunca passam do teto. Se o SMTP falhar
depois, a linha fica: conta a mais, nunca a menos.

Aviso ao suporte (`support_alert`): quando um código ou email de conta é recusado, o
`SUPPORT_EMAIL` recebe um aviso, no máximo um por hora (`SUPPORT_ALERT_INTERVAL`). O último aviso
é o evento `send_cap_reached` do `audit_log`, lido e gravado na mesma transação: vale com mais de
um processo, sobrevive a um restart e dois requests ao mesmo tempo não mandam dois avisos. O aviso
fica fora da contagem (até 24 em 24 h, dentro da margem entre o `MAX_EMAILS_PER_DAY` e a cota do
provedor).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.config import APP_NAME_RE, IMAGO_APP_NAME, Settings
from app.db import require_write_transaction
from app.mail.catalog import CapWindow, SendCapReached
from app.mail.kinds import MailKind
from app.models import AuditLog, MailLog

logger = logging.getLogger(__name__)

DAY = timedelta(hours=24)
HOUR = timedelta(hours=1)
# Intervalo mínimo entre dois avisos de teto ao suporte
SUPPORT_ALERT_INTERVAL = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class QuotaRefusal:
    """A janela que bateu e o limite dela para o tipo do email."""

    window: CapWindow
    limit: int


def limits(settings: Settings, kind: MailKind) -> tuple[tuple[CapWindow, int], ...]:
    """Limite de cada janela (hora e dia) para o tipo `kind`."""
    if kind is MailKind.NOTIFICATION:
        return (
            ("hour", settings.max_emails_per_hour - settings.mail_reserved_for_codes_per_hour),
            ("day", settings.max_emails_per_day - settings.mail_reserved_for_codes_per_day),
        )
    return (("hour", settings.max_emails_per_hour), ("day", settings.max_emails_per_day))


def sent_in(session: Session, window: CapWindow, now: datetime) -> int:
    """Quantos envios (de qualquer tipo e aplicação) a janela que termina em `now` tem."""
    length = HOUR if window == "hour" else DAY
    return session.scalar(
        select(func.count()).select_from(MailLog).where(MailLog.created_at > now - length)
    )


def check(
    session: Session, settings: Settings, kind: MailKind, now: datetime
) -> QuotaRefusal | None:
    """A recusa, se o teto de `kind` bateu em alguma janela; senão None. Não grava nada."""
    require_write_transaction(session)
    for window, limit in limits(settings, kind):
        if sent_in(session, window, now) >= limit:
            return QuotaRefusal(window=window, limit=limit)
    return None


def record(session: Session, *, app: str, kind: MailKind, now: datetime) -> None:
    """Grava um envio no `mail_log` (sem destinatário). `app`: "imago" ou a aplicação do token."""
    require_write_transaction(session)
    if app != IMAGO_APP_NAME and APP_NAME_RE.fullmatch(app) is None:
        raise ValueError("nome de aplicação inválido")
    session.add(MailLog(app=app, kind=kind.value, created_at=now))


def reserve(
    session: Session, settings: Settings, *, app: str, kind: MailKind, now: datetime
) -> QuotaRefusal | None:
    """Confere o teto e, se couber, grava o envio. Devolve a recusa ou None (pode enviar)."""
    refusal = check(session, settings, kind, now)
    if refusal is None:
        record(session, app=app, kind=kind, now=now)
    return refusal


def support_alert(
    session: Session, refusal: QuotaRefusal, kind: MailKind, now: datetime
) -> SendCapReached | None:
    """Grava `send_cap_reached` e devolve o aviso ao suporte, se nenhum saiu na última hora.

    Para recusas de código e de email de conta: quem chama agenda o envio ao `SUPPORT_EMAIL`
    depois do commit, sem passar pelo `reserve` (o aviso fica fora da contagem).
    """
    require_write_transaction(session)
    recent = session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.event == AuditEvent.SEND_CAP_REACHED.value,
            AuditLog.created_at > now - SUPPORT_ALERT_INTERVAL,
        )
    )
    if recent:
        return None
    audit.record(
        session,
        AuditEvent.SEND_CAP_REACHED,
        user_id=None,
        details={"window": refusal.window, "limit": refusal.limit, "kind": kind.value},
    )
    logger.warning(
        "teto de envio de email atingido (%s, limite %d, tipo %s)",
        refusal.window,
        refusal.limit,
        kind.value,
    )
    return SendCapReached(window=refusal.window, limit=refusal.limit)
