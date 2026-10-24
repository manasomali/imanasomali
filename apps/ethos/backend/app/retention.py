"""Retenção de dados do plano: o que o `python -m app.cli cleanup` apaga, de hora em hora.

- eventos de auth (`app.audit.AUTH_EVENTS`) com mais de 90 dias: apagados;
- IP no `audit_log` e em `sessions` com mais de 90 dias (pelo `created_at` da linha): vira NULL;
- `sessions` vencidas (`expires_at` no passado): apagadas;
- `login_codes` vencidos e criados há mais de 1 dia (`LOGIN_CODE_RETENTION`): apagados.

Os outros eventos da auditoria (marcações, configuração, compartilhamento, conta, admin) não são
apagados aqui: ficam enquanto o hábito existir (o ON DELETE CASCADE apaga junto com ele) ou até a
exclusão da conta. Só o IP deles some.

Um código de login vale 10 minutos, mas a linha fica 1 dia: os limites de envio (1 por minuto e 5
por hora por email, e o teto global por hora e por dia) são contados pelas linhas de
`login_codes`. Apagar o código logo que vence zeraria essas contagens. Quem limpa ao criar um
código novo (ETH-17) usa as mesmas funções daqui.

Todas as funções escrevem com `session.execute(delete/update)` e exigem estar dentro de
`write_transaction` (RuntimeError fora). Elas não fazem commit e não atualizam objetos já
carregados na sessão. `now` é sempre um datetime com fuso.
"""

from dataclasses import astuple, dataclass
from datetime import datetime, timedelta

from sqlalchemy import Delete, Update, delete, update
from sqlalchemy.orm import Session

from app.audit import AUTH_EVENT_RETENTION, AUTH_EVENTS, IP_RETENTION
from app.db import require_write_transaction
from app.models import AuditLog, LoginCode, UserSession

# Tempo que a linha de um código vencido fica, para as contagens dos limites de envio (a maior
# janela é o teto por dia)
LOGIN_CODE_RETENTION = timedelta(days=1)


@dataclass(frozen=True)
class CleanupResult:
    """Quantas linhas cada passo do cleanup mudou."""

    auth_events_deleted: int
    audit_ips_cleared: int
    sessions_deleted: int
    session_ips_cleared: int
    login_codes_deleted: int

    @property
    def total(self) -> int:
        return sum(astuple(self))


def run_cleanup(session: Session, now: datetime) -> CleanupResult:
    """Aplica toda a retenção do plano. Idempotente: com o mesmo `now`, a 2ª vez não muda nada."""
    require_write_transaction(session)
    _check_now(now)
    # Primeiro o que apaga, para não limpar o IP de linhas que vão sair de qualquer jeito
    auth_events = delete_old_auth_events(session, now)
    sessions = delete_expired_sessions(session, now)
    login_codes = delete_expired_login_codes(session, now)
    ip_cutoff = now - IP_RETENTION
    audit_ips = _execute(
        session,
        update(AuditLog)
        .where(AuditLog.created_at < ip_cutoff, AuditLog.ip.is_not(None))
        .values(ip=None),
    )
    session_ips = _execute(
        session,
        update(UserSession)
        .where(UserSession.created_at < ip_cutoff, UserSession.ip.is_not(None))
        .values(ip=None),
    )
    return CleanupResult(
        auth_events_deleted=auth_events,
        audit_ips_cleared=audit_ips,
        sessions_deleted=sessions,
        session_ips_cleared=session_ips,
        login_codes_deleted=login_codes,
    )


def delete_old_auth_events(session: Session, now: datetime) -> int:
    """Apaga os eventos de auth com mais de 90 dias. Devolve quantos apagou."""
    require_write_transaction(session)
    _check_now(now)
    events = sorted(event.value for event in AUTH_EVENTS)
    return _execute(
        session,
        delete(AuditLog).where(
            AuditLog.event.in_(events), AuditLog.created_at < now - AUTH_EVENT_RETENTION
        ),
    )


def delete_expired_sessions(session: Session, now: datetime) -> int:
    """Apaga as sessões vencidas. Devolve quantas apagou."""
    require_write_transaction(session)
    _check_now(now)
    return _execute(session, delete(UserSession).where(UserSession.expires_at < now))


def delete_expired_login_codes(session: Session, now: datetime) -> int:
    """Apaga os códigos vencidos criados há mais de `LOGIN_CODE_RETENTION`. Devolve quantos."""
    require_write_transaction(session)
    _check_now(now)
    return _execute(
        session,
        delete(LoginCode).where(
            LoginCode.expires_at < now, LoginCode.created_at < now - LOGIN_CODE_RETENTION
        ),
    )


def _check_now(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now sem fuso: use datetime com tzinfo (ex.: UTC)")


def _execute(session: Session, statement: Delete | Update) -> int:
    """Roda o UPDATE/DELETE e devolve quantas linhas mudaram."""
    # Sem sincronizar a sessão: o comando roda sobre o banco, não sobre objetos carregados
    result = session.execute(statement, execution_options={"synchronize_session": False})
    return result.rowcount
