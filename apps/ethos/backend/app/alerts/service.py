"""Alertas por email (ETH-26): a configuração de cada membro e a avaliação de hora em hora.

Configuração (`get_alert` / `save_alert`, endpoints `GET/PUT /habits/{id}/alerts`):

- Uma linha de `alerts` por membro e hábito, só do dono e dos editores. Viewer recebe 403
  `forbidden` ao ler e ao salvar (ele não liga alertas); sem acesso, 404 `not_found`. Quando o
  dono rebaixa um editor para viewer, ou quando o membro sai ou é removido, os alertas dele no
  hábito saem na mesma transação (`app/sharing/service.py`).
- Sem linha salva, a configuração é a padrão: as duas chaves desligadas, `DEFAULT_HOUR`, diário.
- Hábito arquivado é só leitura: ler funciona, salvar dá 409 `habit_archived`. Pausado salva.
- Salvar só grava o que mudou, com `alert_updated` (`{"changes": [{field, old, new}]}`) na
  auditoria. O evento fica fora do histórico (`GET /history`): a configuração é pessoal.

Avaliação (`run_alerts`, `python -m app.cli run-alerts`, de hora em hora pelo
`ethos-alerts.timer`):

- Quando: a hora cheia escolhida, no fuso do usuário (`users.timezone`), todo dia (diário) ou só
  no dia da semana escolhido (semanal). Cada ocorrência é avaliada uma vez, na primeira execução
  a partir da hora (`is_due`): uma execução atrasada (o timer das 09:00 rodou às 10:05, ou pulou
  horas porque a VM estava fora) ainda avalia o alerta das 09:00, desde que no mesmo dia local; a
  ocorrência de um dia que passou inteiro sem execução se perde. O `last_evaluated_at` guarda a
  avaliação, para uma avaliação sem email não se repetir de hora em hora até o fim do dia.
  Salvar a configuração também o grava: uma ocorrência que já tinha passado antes de salvar só
  vale a partir da próxima.
- Horário de verão: a hora que não existe no dia (o relógio pula de 02:00 para 03:00) dispara no
  primeiro instante depois do pulo (03:00); a hora que se repete (01:00 duas vezes) dispara só na
  primeira vez.
- No máximo um email por membro e hábito por dia local (`last_sent_at`), juntando meta e custo,
  mesmo que a hora mude depois do envio.
- O que dispara, olhando o período atual no fuso do usuário, só com a chave ligada: meta pelo
  `Pace.alert` do `score.evaluate` (`min` atrasado no ritmo; `max` atingiu ou passou; `exact`
  passou ou atrasado) e custo pelo `score.check_cost` (aviso em 80% do limite, alerta ao passar).
  O `score.py` devolve "não avaliar" no período da criação do hábito, com pausa no período e com
  o hábito arquivado. Hábito pausado ou arquivado, conta bloqueada (`is_active=false`) e quem não
  é mais dono nem editor não são avaliados.
- Envio sem email duplicado: dentro de um `write_transaction` (BEGIN IMMEDIATE), o alerta é relido
  e reavaliado, e o `last_evaluated_at` e o `last_sent_at` são gravados antes do envio. Duas
  execuções ao mesmo tempo não mandam dois emails: a segunda lê o alerta já marcado. O envio
  acontece depois do commit, fora da trava de escrita. Se ele falha, uma segunda transação
  desfaz a marcação (se ninguém mudou o alerta nesse meio-tempo), e a próxima execução tenta de
  novo. Se o processo morre entre o commit e o envio, o email daquela ocorrência se perde: melhor
  um alerta a menos que um repetido.
- Falha num alerta (SMTP, fuso inválido, banco ocupado, dado inconsistente) vira uma linha de log
  com os ids do hábito e do usuário e o tipo do erro, nunca email, nome do hábito nem mensagem da
  exceção, e não impede os outros. Ela entra na contagem `failed` do resultado, mas não muda o
  código de saída do comando: o `OnFailure=` do timer fica para erro geral (config, banco
  inacessível na leitura inicial), que levanta.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Row, and_, or_, select
from sqlalchemy.orm import Session

from app import audit, score
from app.audit import AuditEvent
from app.db import write_transaction
from app.errors import ApiError, ErrorCode
from app.habits.access import HabitAccess, HabitRole, get_habit_access, require_writable, role_of
from app.habits.scoring import load_marks, load_pauses, to_score_habit
from app.mail.catalog import Alert as AlertEmail
from app.mail.catalog import CostAlert, GoalAlert, GoalStatus
from app.mail.language import Locale, pick_locale
from app.mail.sender import Mailer
from app.models import (
    Alert,
    AlertFrequency,
    GoalType,
    Habit,
    HabitMember,
    HabitStatus,
    User,
)

logger = logging.getLogger(__name__)

# Hora padrão de quem ainda não salvou a configuração (à noite: ainda dá para cumprir o dia)
DEFAULT_HOUR = 20

# Campos da configuração, na ordem do `changes` da auditoria
CONFIG_FIELDS = ("goal_enabled", "cost_enabled", "hour", "frequency", "weekday")


@dataclass(frozen=True, slots=True)
class AlertSettings:
    """A configuração de alerta de um membro num hábito (a salva ou a padrão)."""

    goal_enabled: bool
    cost_enabled: bool
    hour: int
    frequency: AlertFrequency
    weekday: int | None
    last_sent_at: datetime | None


DEFAULT_SETTINGS = AlertSettings(
    goal_enabled=False,
    cost_enabled=False,
    hour=DEFAULT_HOUR,
    frequency=AlertFrequency.DAILY,
    weekday=None,
    last_sent_at=None,
)


def _require_alert_role(access: HabitAccess) -> None:
    # Dono e editor configuram; viewer não liga alertas
    if access.role is HabitRole.VIEWER:
        raise ApiError(403, ErrorCode.FORBIDDEN)


def _settings(alert: Alert | None) -> AlertSettings:
    if alert is None:
        return DEFAULT_SETTINGS
    frequency = AlertFrequency(alert.frequency)
    return AlertSettings(
        goal_enabled=alert.goal_enabled,
        cost_enabled=alert.cost_enabled,
        hour=alert.hour,
        frequency=frequency,
        # O banco aceita guardar o dia no diário; a API mostra só o que vale
        weekday=alert.weekday if frequency is AlertFrequency.WEEKLY else None,
        last_sent_at=alert.last_sent_at,
    )


def _load(session: Session, habit_id: int, user_id: int) -> Alert | None:
    return session.get(Alert, (habit_id, user_id), populate_existing=True)


def get_alert(session: Session, *, user_id: int, habit_id: int) -> AlertSettings:
    """A configuração do usuário no hábito. Levanta 404 (sem acesso) ou 403 (viewer)."""
    _require_alert_role(get_habit_access(session, habit_id, user_id))
    return _settings(_load(session, habit_id, user_id))


def save_alert(
    session: Session,
    *,
    user_id: int,
    habit_id: int,
    values: Mapping[str, Any],
    ip: str | None,
    now: datetime,
) -> AlertSettings:
    """Troca a configuração inteira por `values` (os `CONFIG_FIELDS`, já validados).

    Levanta 404 (sem acesso), 403 (viewer) ou 409 `habit_archived`. Nada mudou: não grava nada.
    """
    with write_transaction(session):
        access = get_habit_access(session, habit_id, user_id)
        _require_alert_role(access)
        require_writable(access)
        alert = _load(session, habit_id, user_id)
        current = _settings(alert)
        new = {name: values[name] for name in CONFIG_FIELDS}
        if new["frequency"] == AlertFrequency.DAILY:
            new["weekday"] = None
        changes = [
            {"field": name, "old": _plain(getattr(current, name)), "new": _plain(new[name])}
            for name in CONFIG_FIELDS
            if getattr(current, name) != new[name]
        ]
        if changes:
            if alert is None:
                alert = Alert(habit_id=habit_id, user_id=user_id)
                session.add(alert)
            for name in CONFIG_FIELDS:
                setattr(alert, name, _plain(new[name]))
            # Âncora da avaliação: a ocorrência de hoje que já passou não é avaliada atrasada
            alert.last_evaluated_at = now
            audit.record(
                session,
                AuditEvent.ALERT_UPDATED,
                user_id=user_id,
                ip=ip,
                habit_id=habit_id,
                details={"changes": changes},
            )
        result = _settings(alert)
    return result


def _plain(value: Any) -> Any:
    # Enum vira o texto dele (JSON da auditoria e coluna de texto)
    return value.value if isinstance(value, AlertFrequency) else value


# --- Avaliação e envio ---


class Outcome(StrEnum):
    """O que aconteceu com um alerta numa execução."""

    # Não estava na hora (ou outra execução avaliou antes)
    SKIPPED = "skipped"
    # Avaliado, sem nada a avisar
    EVALUATED = "evaluated"
    SENT = "sent"
    # Falhou (envio ou erro inesperado); o envio é tentado de novo na próxima execução
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RunResult:
    """Contagem de uma execução do `run_alerts`. `evaluated` inclui os enviados."""

    evaluated: int
    sent: int
    failed: int


@dataclass(frozen=True, slots=True)
class _Delivery:
    """Email a enviar depois do commit, com o que desfazer se o envio falhar."""

    to: str
    locale: Locale
    email: AlertEmail
    previous_sent_at: datetime | None
    previous_evaluated_at: datetime | None


def scheduled_at(day: date, hour: int, tz: ZoneInfo) -> datetime:
    """O instante (UTC) em que começa a hora `hour` no dia local `day`.

    Hora que não existe (início do horário de verão) vira, com `fold=0`, o instante do pulo, o
    primeiro instante depois dela. Hora que se repete (fim do horário de verão) é a primeira.
    """
    return datetime.combine(day, time(hour), tzinfo=tz).astimezone(UTC)


def is_due(
    *,
    hour: int,
    frequency: str,
    weekday: int | None,
    last_sent_at: datetime | None,
    last_evaluated_at: datetime | None,
    tz: ZoneInfo,
    now: datetime,
) -> bool:
    """Se o alerta deve ser avaliado agora: a ocorrência de hoje (no fuso `tz`) já começou e
    ainda não foi avaliada, e nenhum email desse alerta saiu hoje."""
    today = now.astimezone(tz).date()
    if frequency == AlertFrequency.WEEKLY and today.weekday() != weekday:
        return False
    start = scheduled_at(today, hour, tz)
    if now < start:
        return False
    if last_evaluated_at is not None and last_evaluated_at >= start:
        return False
    return last_sent_at is None or last_sent_at.astimezone(tz).date() != today


def _goal_status(goal_type: str, pace: score.Pace) -> GoalStatus:
    if pace.value > pace.target:
        return "exceeded"
    # max: atingiu N; min e exact: atrasado no ritmo
    return "reached" if goal_type == GoalType.MAX else "behind"


def _alert_email(
    session: Session, alert: Alert, habit: Habit, tz: ZoneInfo, now: datetime
) -> AlertEmail | None:
    """O email do que disparou agora (só as chaves ligadas), ou None se nada disparou."""
    config = to_score_habit(habit)
    marks = load_marks(session, [habit.id], since_creation=True)[habit.id]
    pauses = load_pauses(session, [habit.id])[habit.id]
    goal: GoalAlert | None = None
    cost: CostAlert | None = None
    if alert.goal_enabled:
        pace = score.evaluate(config, marks, pauses, tz, now).pace
        if pace is not None and pace.alert:
            goal = GoalAlert(
                status=_goal_status(habit.goal_type, pace),
                done=pace.value,
                target=pace.target,
                period=config.goal_period,
            )
    if alert.cost_enabled:
        check = score.check_cost(config, marks, pauses, tz, now)
        # check_cost só devolve um resultado com limite e período definidos
        if check is not None and check.level != "ok" and config.cost_limit_period is not None:
            cost = CostAlert(
                status=check.level,
                spent_cents=check.spend_cents,
                limit_cents=check.limit_cents,
                period=config.cost_limit_period,
            )
    if goal is None and cost is None:
        return None
    return AlertEmail(habit_id=habit.id, habit_name=habit.name, goal=goal, cost=cost)


def _claim(
    session: Session, habit_id: int, user_id: int, now: datetime
) -> tuple[bool, _Delivery | None]:
    """Dentro do `write_transaction`: relê, confere e avalia o alerta e marca a avaliação (e o
    envio, se houver email). Devolve (avaliou, email a enviar)."""
    row = session.execute(
        select(Alert, Habit, User, HabitMember.role)
        .join(Habit, Habit.id == Alert.habit_id)
        .join(User, User.id == Alert.user_id)
        .outerjoin(
            HabitMember,
            and_(HabitMember.habit_id == Alert.habit_id, HabitMember.user_id == Alert.user_id),
        )
        .where(Alert.habit_id == habit_id, Alert.user_id == user_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        return False, None
    alert, habit, user, member_role = row
    role = role_of(habit, user_id, member_role)
    if (
        habit.status != HabitStatus.ACTIVE
        or not user.is_active
        or role not in (HabitRole.OWNER, HabitRole.EDITOR)
        or not (alert.goal_enabled or alert.cost_enabled)
    ):
        return False, None
    tz = ZoneInfo(user.timezone)
    due = is_due(
        hour=alert.hour,
        frequency=alert.frequency,
        weekday=alert.weekday,
        last_sent_at=alert.last_sent_at,
        last_evaluated_at=alert.last_evaluated_at,
        tz=tz,
        now=now,
    )
    if not due:
        return False, None
    email = _alert_email(session, alert, habit, tz, now)
    previous_sent_at, previous_evaluated_at = alert.last_sent_at, alert.last_evaluated_at
    alert.last_evaluated_at = now
    if email is None:
        return True, None
    alert.last_sent_at = now
    delivery = _Delivery(
        to=user.email,
        locale=pick_locale(user.locale),
        email=email,
        previous_sent_at=previous_sent_at,
        previous_evaluated_at=previous_evaluated_at,
    )
    return True, delivery


def _release(
    session: Session, habit_id: int, user_id: int, now: datetime, delivery: _Delivery
) -> None:
    """Desfaz a marcação de um envio que falhou. Cada coluna só volta se ainda tem o valor do
    `_claim`: se o usuário salvou a configuração no meio do envio, a âncora nova fica."""
    alert = _load(session, habit_id, user_id)
    if alert is None:
        return
    if alert.last_sent_at == now:
        alert.last_sent_at = delivery.previous_sent_at
    if alert.last_evaluated_at == now:
        alert.last_evaluated_at = delivery.previous_evaluated_at


def _process(
    session_factory: Callable[[], Session],
    mailer: Mailer,
    habit_id: int,
    user_id: int,
    now: datetime,
) -> Outcome:
    with session_factory() as session:
        with write_transaction(session):
            evaluated, delivery = _claim(session, habit_id, user_id, now)
        if delivery is None:
            return Outcome.EVALUATED if evaluated else Outcome.SKIPPED
        # Fora da transação: o envio (até alguns segundos) não segura a trava de escrita
        if mailer.send(delivery.to, delivery.locale, delivery.email):
            return Outcome.SENT
        with write_transaction(session):
            _release(session, habit_id, user_id, now, delivery)
    # O Mailer já logou o tipo do erro; aqui, qual alerta
    logger.warning(
        "alerta do hábito %d (usuário %d) não enviado; nova tentativa na próxima execução",
        habit_id,
        user_id,
    )
    return Outcome.FAILED


def _candidates(session: Session) -> list[Row[Any]]:
    """Os alertas ligados de hábitos ativos de contas ativas, com o que decide a hora.

    Uma leitura só, sem trava: quem decide de verdade é o `_claim`, dentro da escrita.
    """
    query = (
        select(
            Alert.habit_id,
            Alert.user_id,
            Alert.hour,
            Alert.frequency,
            Alert.weekday,
            Alert.last_sent_at,
            Alert.last_evaluated_at,
            User.timezone,
        )
        .join(Habit, Habit.id == Alert.habit_id)
        .join(User, User.id == Alert.user_id)
        .where(
            or_(Alert.goal_enabled, Alert.cost_enabled),
            Habit.status == HabitStatus.ACTIVE,
            User.is_active,
        )
        .order_by(Alert.habit_id, Alert.user_id)
    )
    return list(session.execute(query).all())


def _run_one(
    session_factory: Callable[[], Session], mailer: Mailer, row: Row[Any], now: datetime
) -> Outcome:
    due = is_due(
        hour=row.hour,
        frequency=row.frequency,
        weekday=row.weekday,
        last_sent_at=row.last_sent_at,
        last_evaluated_at=row.last_evaluated_at,
        tz=ZoneInfo(row.timezone),
        now=now,
    )
    if not due:
        return Outcome.SKIPPED
    return _process(session_factory, mailer, row.habit_id, row.user_id, now)


def run_alerts(
    session_factory: Callable[[], Session], mailer: Mailer, *, now: datetime
) -> RunResult:
    """Avalia os alertas na hora e manda os emails. Erro na leitura inicial levanta (erro geral);
    erro num alerta é logado e contado em `failed`, sem parar os outros."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now precisa ter fuso")
    now = now.astimezone(UTC)
    with session_factory() as session:
        rows = _candidates(session)
    evaluated = sent = failed = 0
    for row in rows:
        try:
            outcome = _run_one(session_factory, mailer, row, now)
        except Exception as exc:
            # Só os ids e o tipo: a mensagem pode trazer email, SQL ou o caminho do banco
            logger.error(
                "alerta do hábito %d (usuário %d) falhou (%s)",
                row.habit_id,
                row.user_id,
                type(exc).__name__,
            )
            outcome = Outcome.FAILED
        evaluated += outcome in (Outcome.EVALUATED, Outcome.SENT)
        sent += outcome is Outcome.SENT
        failed += outcome is Outcome.FAILED
    return RunResult(evaluated=evaluated, sent=sent, failed=failed)
