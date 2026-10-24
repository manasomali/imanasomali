"""Regras do login por código: pedir o código, verificar, criar o usuário e a sessão.

Cadastro e login são o mesmo fluxo. O usuário só é criado quando confirma o código, já com a
versão atual dos termos aceita (`app/terms.py`) e com o fuso e o idioma do navegador.

Cada função abre o próprio `write_transaction` (BEGIN IMMEDIATE) e devolve o resultado, em vez de
levantar exceção, para o que precisa ficar gravado ficar gravado também quando a resposta é de
erro: a tentativa contada num código errado e o aviso do teto global. A hora (`utcnow()`) é lida
já dentro da transação, depois de pegar a trava de escrita. Quem chama (`app/auth/routes.py`)
transforma o resultado em resposta HTTP e agenda os emails depois do commit.

Pedir código (`request_login_code`):

- limite por email: 1 código por minuto e 5 por hora (`EMAIL_SEND_LIMITS`), contados pelas linhas
  de `login_codes` do email, de qualquer propósito;
- teto global: `MAX_CODE_EMAILS_PER_HOUR` e `MAX_CODE_EMAILS_PER_DAY`, contados por todas as
  linhas de `login_codes`. Ao bater, o aviso ao `SUPPORT_EMAIL` sai no máximo 1 vez por hora
  (`SUPPORT_ALERT_INTERVAL`). O "último aviso" é a linha mais recente do evento
  `send_cap_reached` no `audit_log`: fica no banco (vale com mais de um processo e sobrevive a um
  restart) e é lida e gravada dentro do BEGIN IMMEDIATE, então dois requests ao mesmo tempo não
  mandam dois avisos;
- os dois limites dão a mesma resposta (429) para qualquer email, com ou sem conta;
- conta inativa (bloqueada pelo admin) ganha a linha em `login_codes` como as outras, mas nenhum
  email: assim os limites, e a resposta, são iguais aos de uma conta ativa. O código dela nunca é
  mandado e o `verify` recusa conta inativa de qualquer jeito;
- o código novo invalida os anteriores do mesmo email e propósito (vencem na hora), e antes dele
  saem os códigos e as sessões vencidos (`app/retention.py`).

Verificar (`verify_login_code`): numa transação só, conta a tentativa (antes de comparar),
compara, marca `used_at`, cria o usuário se for o primeiro acesso e cria a sessão. O código vale
10 minutos (`CODE_LIFETIME`), uma vez só e por no máximo 5 tentativas (`MAX_CODE_ATTEMPTS`): a
6ª é recusada mesmo com o código certo, sem passar o `attempts` de 5. Só o código mais recente do
email vale. Dois verify do mesmo primeiro acesso ao mesmo tempo esperam um pelo outro no BEGIN
IMMEDIATE: o segundo encontra o código já usado (e o `email` único em `users` segura o resto).

Código e token nunca vão para log nem para o `audit_log`; no banco ficam só os sha256.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from functools import cache
from zoneinfo import available_timezones

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.auth.security import generate_code, generate_token, hash_secret, verify_secret
from app.config import Settings, is_email
from app.db import require_write_transaction, write_transaction
from app.mail.catalog import CapWindow, Email, SendCapReached
from app.mail.catalog import LoginCode as LoginCodeEmail
from app.mail.language import Locale, pick_locale
from app.models import (
    TIMEZONE_MAX_LENGTH,
    USER_AGENT_MAX_LENGTH,
    AuditLog,
    CodePurpose,
    LoginCode,
    User,
    UserSession,
    utcnow,
)
from app.retention import delete_expired_login_codes, delete_expired_sessions
from app.terms import TERMS_VERSION

logger = logging.getLogger(__name__)

# Validade e tentativas de um código
CODE_LIFETIME_MINUTES = 10
CODE_LIFETIME = timedelta(minutes=CODE_LIFETIME_MINUTES)
MAX_CODE_ATTEMPTS = 5
# Limites de envio por email: (janela, máximo de códigos criados na janela)
EMAIL_SEND_LIMITS = ((timedelta(minutes=1), 1), (timedelta(hours=1), 5))
# Intervalo mínimo entre dois avisos de teto global ao suporte
SUPPORT_ALERT_INTERVAL = timedelta(hours=1)
# Idioma do aviso ao suporte (quem opera o serviço)
SUPPORT_LOCALE = Locale.PT
# Duração da sessão desde o último uso (o cookie tem o mesmo Max-Age); renovação em app/auth/deps.py
SESSION_LIFETIME = timedelta(days=60)


def normalize_email(value: str) -> str | None:
    """Email com strip + lower, ou None se não parece um endereço (ou passa de 254 caracteres)."""
    email = value.strip().lower()
    # isprintable barra caracteres de controle, que a forma simples do is_email deixaria passar
    if not email.isprintable() or not is_email(email):
        return None
    return email


@cache
def _timezones() -> frozenset[str]:
    # Lê a base de fusos uma vez por processo (a do sistema e a do pacote tzdata)
    return frozenset(available_timezones())


def is_valid_timezone(name: str) -> bool:
    """Diz se `name` é um fuso IANA conhecido, escrito como na base (ex.: America/Sao_Paulo).

    Consulta a lista de fusos em vez de tentar `ZoneInfo(name)`, que aceitaria nomes de arquivos
    da base que não são fusos.
    """
    return len(name) <= TIMEZONE_MAX_LENGTH and name in _timezones()


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """Email a agendar depois do commit."""

    to: str = field(repr=False)
    locale: Locale
    email: Email


class CodeRequestOutcome(StrEnum):
    # Código criado; o email vai para quem pediu
    SENT = "sent"
    # Código criado (conta nos limites), mas a conta está inativa: nenhum email
    INACTIVE_ACCOUNT = "inactive_account"
    # Limite por email (1 por minuto ou 5 por hora): nada criado
    RATE_LIMITED = "rate_limited"
    # Teto global por hora ou por dia: nada criado; talvez um aviso ao suporte
    CAP_REACHED = "cap_reached"


@dataclass(frozen=True, slots=True)
class CodeRequestResult:
    outcome: CodeRequestOutcome
    # Emails a agendar: o código, ou o aviso ao suporte quando o teto bateu
    emails: tuple[OutgoingEmail, ...] = ()

    @property
    def accepted(self) -> bool:
        """True quando a resposta é 202 (com ou sem email); False quando é 429."""
        return self.outcome in (CodeRequestOutcome.SENT, CodeRequestOutcome.INACTIVE_ACCOUNT)


def request_login_code(
    session: Session,
    settings: Settings,
    *,
    email: str,
    ip: str | None,
    accept_language: str | None,
) -> CodeRequestResult:
    """Cria um código de login para `email` (já normalizado) e diz o que responder.

    `ip` é o do cliente, já validado (`app/request_info.py`); `accept_language` escolhe o idioma
    do email no primeiro acesso.
    """
    with write_transaction(session):
        now = utcnow()
        if _email_limit_reached(session, email, now):
            return CodeRequestResult(CodeRequestOutcome.RATE_LIMITED)
        cap = _send_cap_reached(session, settings, now)
        if cap is not None:
            window, limit = cap
            alert = _support_alert(session, settings, window, limit, now)
            return CodeRequestResult(CodeRequestOutcome.CAP_REACHED, alert)

        delete_expired_login_codes(session, now)
        delete_expired_sessions(session, now)
        user = _find_user(session, email)
        code = _issue_code(session, email, CodePurpose.LOGIN, now)
        if user is None:
            locale = pick_locale(None, accept_language)
        else:
            audit.record(session, AuditEvent.CODE_REQUESTED, user_id=user.id, ip=ip)
            if not user.is_active:
                return CodeRequestResult(CodeRequestOutcome.INACTIVE_ACCOUNT)
            locale = pick_locale(user.locale, accept_language)
        message = LoginCodeEmail(code=code, valid_minutes=CODE_LIFETIME_MINUTES)
        return CodeRequestResult(CodeRequestOutcome.SENT, (OutgoingEmail(email, locale, message),))


def _count_codes(session: Session, *where: object) -> int:
    return session.scalar(select(func.count()).select_from(LoginCode).where(*where))


def _email_limit_reached(session: Session, email: str, now: datetime) -> bool:
    return any(
        _count_codes(session, LoginCode.email == email, LoginCode.created_at > now - window)
        >= maximum
        for window, maximum in EMAIL_SEND_LIMITS
    )


def _send_cap_reached(
    session: Session, settings: Settings, now: datetime
) -> tuple[CapWindow, int] | None:
    """A janela do teto global que bateu (e o limite dela), ou None."""
    caps: tuple[tuple[CapWindow, timedelta, int], ...] = (
        ("hour", timedelta(hours=1), settings.max_code_emails_per_hour),
        ("day", timedelta(days=1), settings.max_code_emails_per_day),
    )
    for window, length, limit in caps:
        if _count_codes(session, LoginCode.created_at > now - length) >= limit:
            return window, limit
    return None


def _support_alert(
    session: Session, settings: Settings, window: CapWindow, limit: int, now: datetime
) -> tuple[OutgoingEmail, ...]:
    """Grava e devolve o aviso ao suporte, se nenhum saiu na última hora."""
    recent = session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.event == AuditEvent.SEND_CAP_REACHED.value,
            AuditLog.created_at > now - SUPPORT_ALERT_INTERVAL,
        )
    )
    if recent:
        return ()
    audit.record(
        session,
        AuditEvent.SEND_CAP_REACHED,
        user_id=None,
        details={"window": window, "limit": limit},
    )
    logger.warning("teto global de envio de códigos atingido (%s, limite %d)", window, limit)
    alert = SendCapReached(window=window, limit=limit)
    return (OutgoingEmail(settings.support_email, SUPPORT_LOCALE, alert),)


def _find_user(session: Session, email: str) -> User | None:
    # populate_existing: relê a linha mesmo que a sessão já tenha o objeto de outra transação
    return session.scalar(
        select(User).where(User.email == email).execution_options(populate_existing=True)
    )


def _issue_code(session: Session, email: str, purpose: CodePurpose, now: datetime) -> str:
    """Invalida os códigos anteriores do email e propósito e cria um novo. Devolve o código."""
    session.execute(
        update(LoginCode)
        .where(
            LoginCode.email == email,
            LoginCode.purpose == purpose.value,
            LoginCode.used_at.is_(None),
            LoginCode.expires_at > now,
        )
        .values(expires_at=now),
        execution_options={"synchronize_session": False},
    )
    code = generate_code()
    session.add(
        LoginCode(
            email=email,
            purpose=purpose.value,
            code_hash=hash_secret(code),
            expires_at=now + CODE_LIFETIME,
            created_at=now,
        )
    )
    return code


class VerifyFailure(StrEnum):
    # Código errado, vencido, usado, esgotado, inexistente ou de conta inativa
    INVALID_CODE = "invalid_code"
    # Código certo, mas o fuso do primeiro acesso não existe (o código continua valendo)
    INVALID_TIMEZONE = "invalid_timezone"


@dataclass(frozen=True, slots=True)
class LoginResult:
    user_id: int
    # Valor do cookie de sessão; no banco fica só o sha256
    token: str = field(repr=False)
    new_account: bool


def verify_login_code(
    session: Session,
    *,
    email: str,
    code: str,
    timezone: str,
    locale: Locale,
    ip: str | None,
    user_agent: str | None,
) -> LoginResult | VerifyFailure:
    """Confere o código de login de `email` (já normalizado) e, se certo, cria a sessão.

    `timezone` e `locale` só valem no primeiro acesso (conta nova); para conta existente são
    ignorados. A tentativa fica gravada mesmo quando o resultado é uma falha.
    """
    with write_transaction(session):
        now = utcnow()
        user = _find_user(session, email)
        login_code = _attempt(session, email, CodePurpose.LOGIN, code, now)
        if login_code is None or (user is not None and not user.is_active):
            if user is not None:
                audit.record(session, AuditEvent.LOGIN_FAILED, user_id=user.id, ip=ip)
            return VerifyFailure.INVALID_CODE
        if user is None and not is_valid_timezone(timezone):
            return VerifyFailure.INVALID_TIMEZONE

        login_code.used_at = now
        new_account = user is None
        if user is None:
            user = User(
                email=email,
                timezone=timezone,
                locale=locale.value,
                terms_version=TERMS_VERSION,
                terms_accepted_at=now,
                created_at=now,
                updated_at=now,
                last_login_at=now,
            )
            session.add(user)
            # Para ter o user.id
            session.flush()
        else:
            user.last_login_at = now
        token = create_session(session, user.id, now=now, ip=ip, user_agent=user_agent)
        audit.record(
            session, AuditEvent.LOGIN, user_id=user.id, ip=ip, details={"new_account": new_account}
        )
        return LoginResult(user_id=user.id, token=token, new_account=new_account)


def _attempt(
    session: Session, email: str, purpose: CodePurpose, code: str, now: datetime
) -> LoginCode | None:
    """Conta uma tentativa no código mais recente e o devolve se `code` bate; senão None.

    Código usado, vencido ou com as tentativas esgotadas é recusado sem contar outra tentativa,
    então `attempts` nunca passa de `MAX_CODE_ATTEMPTS`.
    """
    login_code = session.scalar(
        select(LoginCode)
        .where(LoginCode.email == email, LoginCode.purpose == purpose.value)
        .order_by(LoginCode.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if (
        login_code is None
        or login_code.used_at is not None
        or login_code.expires_at <= now
        or login_code.attempts >= MAX_CODE_ATTEMPTS
    ):
        return None
    # Conta antes de comparar, na mesma transação BEGIN IMMEDIATE: requests em paralelo esperam
    # a vez e cada um vê o attempts do anterior
    login_code.attempts += 1
    return login_code if verify_secret(code, login_code.code_hash) else None


def create_session(
    session: Session,
    user_id: int,
    *,
    now: datetime,
    ip: str | None,
    user_agent: str | None,
) -> str:
    """Cria uma sessão de `SESSION_LIFETIME` para o usuário e devolve o token (para o cookie).

    No banco fica só `hash_secret(token)`; a sessão é achada pelo hash do cookie. Exige estar
    dentro de `write_transaction`. O `user_agent` é cortado em 512 caracteres.
    """
    require_write_transaction(session)
    token = generate_token()
    session.add(
        UserSession(
            token_hash=hash_secret(token),
            user_id=user_id,
            created_at=now,
            expires_at=now + SESSION_LIFETIME,
            last_seen_at=now,
            ip=ip,
            user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
        )
    )
    return token
