"""Regras do login por código: pedir o código, verificar, criar a conta e a sessão.

Cadastro e login são o mesmo fluxo. A conta só é criada quando o código é confirmado, já com a
versão atual dos termos aceita (`app/terms.py`), com o fuso e o idioma do navegador e com um id
aleatório (`generate_account_id`; colisão sorteia outro).

Cada função abre o próprio `write_transaction` (BEGIN IMMEDIATE) e devolve o resultado, em vez de
levantar exceção, para o que precisa ficar gravado ficar gravado também quando a resposta é de
erro: a tentativa contada num código errado e o aviso do teto. A hora (`utcnow()`) é lida já
dentro da transação, depois de pegar a trava de escrita. Quem chama (`app/auth/router.py`)
transforma o resultado em resposta HTTP e agenda os emails depois do commit.

Pedir código (`request_login_code`), nesta ordem:

1. limite por email: 1 código por minuto e 5 por hora (`EMAIL_SEND_LIMITS`), contados pelas
   linhas de `login_codes` do email, de qualquer propósito (login e exclusão de conta);
2. teto de envio compartilhado (`app/mail/quota.py`, tipo `code`). Ao bater, o aviso ao
   `SUPPORT_EMAIL` sai no máximo 1 vez por hora;
3. os dois dão a mesma resposta (429) para qualquer email, com ou sem conta, e não gravam código;
4. conta bloqueada (`is_active=false`) ou em exclusão (`status=deleting`) ganha a linha em
   `login_codes` como as outras, mas nenhum email e nenhuma linha no `mail_log`: os limites e a
   resposta são iguais aos de uma conta ativa, e o `verify` recusa essas contas de qualquer jeito;
5. o código novo invalida os anteriores do mesmo email e propósito (vencem na hora), e antes dele
   saem os códigos e as sessões vencidos (`app/retention.py`).

Verificar (`verify_login_code`): numa transação só, conta a tentativa (antes de comparar),
compara, marca `used_at`, cria a conta se for o primeiro acesso e cria a sessão. O código vale 10
minutos (`CODE_LIFETIME`), uma vez só e por no máximo 5 tentativas (`MAX_CODE_ATTEMPTS`): a 6ª é
recusada mesmo com o código certo, sem passar o `attempts` de 5. Só o código mais recente do email
vale. Dois verify do mesmo primeiro acesso ao mesmo tempo esperam um pelo outro no BEGIN
IMMEDIATE: o segundo encontra o código já usado (e o `email` único em `users` segura o resto).
Conta bloqueada ou em exclusão: o mesmo 400 do código errado, e o email de uma conta em exclusão
não cria conta nova até a exclusão terminar.

Código de exclusão de conta (`request_delete_code` e `use_delete_code`, usados pela ETH-61): o
mesmo mecanismo, com `purpose=delete_account` e `user_id` preenchido. Os limites contam os códigos
de todos os propósitos do email; pedir um código de exclusão invalida só os de exclusão. As duas
rodam dentro do `write_transaction` de quem chama, que relê a conta e confere o último admin na
mesma transação.

Emails de conta (`account_emails`: conta excluída, troca de email): cada um reserva o seu lugar no
teto de envio (tipo `account`), na transação de quem chama. Recusado pelo teto, o email não sai e o
`SUPPORT_EMAIL` recebe o aviso, com a mesma regra dos códigos (no máximo um por hora).

Código e token nunca vão para log nem para o `audit_log`; no banco ficam só os sha256.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from functools import cache
from zoneinfo import available_timezones

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditEvent
from app.auth.security import (
    generate_account_id,
    generate_code,
    generate_token,
    hash_secret,
    verify_secret,
)
from app.config import IMAGO_APP_NAME, Settings, is_email
from app.db import require_write_transaction, write_transaction
from app.mail import quota
from app.mail.catalog import DeleteCode as DeleteCodeEmail
from app.mail.catalog import LoginCode as LoginCodeEmail
from app.mail.kinds import MailKind
from app.mail.language import Locale, pick_locale
from app.mail.sender import OutgoingEmail
from app.models import (
    TIMEZONE_MAX_LENGTH,
    USER_AGENT_MAX_LENGTH,
    CodePurpose,
    LoginCode,
    User,
    UserSession,
    UserStatus,
    utcnow,
)
from app.retention import delete_expired_login_codes, delete_expired_sessions
from app.terms import TERMS_VERSION

# Validade e tentativas de um código
CODE_LIFETIME_MINUTES = 10
CODE_LIFETIME = timedelta(minutes=CODE_LIFETIME_MINUTES)
MAX_CODE_ATTEMPTS = 5
# Limites de envio por email: (janela, máximo de códigos criados na janela)
EMAIL_SEND_LIMITS = ((timedelta(minutes=1), 1), (timedelta(hours=1), 5))
# Idioma do aviso ao suporte (quem opera o serviço)
SUPPORT_LOCALE = Locale.PT
# Duração da sessão desde o último uso; renovação em app/auth/deps.py
SESSION_LIFETIME = timedelta(days=60)
# Sorteios de id antes de desistir. Com 2^53 ids, uma colisão já é improvável; dez seguidas, só
# com o gerador quebrado
MAX_ACCOUNT_ID_DRAWS = 10


def normalize_email(value: str) -> str | None:
    """Email com strip + lower, ou None se não parece um endereço ASCII de até 254 caracteres."""
    email = value.strip().lower()
    # isprintable barra caracteres de controle, que a forma simples do is_email deixaria passar
    if not email.isprintable() or not is_email(email):
        return None
    return email


# Arquivos da base de fusos do sistema que o available_timezones() lista, mas não são fusos
NOT_TIMEZONES = frozenset({"localtime"})


@cache
def _timezones() -> frozenset[str]:
    # Lê a base de fusos uma vez por processo (a do sistema e a do pacote tzdata). No
    # Debian/Ubuntu, a do sistema tem o `localtime`, link para o /etc/localtime, que não é fuso
    # IANA (o navegador não conhece). As aplicações usam a mesma regra no X-User-Timezone
    return frozenset(available_timezones() - NOT_TIMEZONES)


def is_valid_timezone(name: str) -> bool:
    """Diz se `name` é um fuso IANA conhecido, escrito como na base (ex.: America/Sao_Paulo).

    Consulta a lista de fusos em vez de tentar `ZoneInfo(name)`, que aceitaria nomes de arquivos
    da base que não são fusos.
    """
    return len(name) <= TIMEZONE_MAX_LENGTH and name in _timezones()


def can_sign_in(user: User) -> bool:
    """Conta que entra e recebe código: não bloqueada pelo admin e fora de exclusão."""
    return user.is_active and user.status == UserStatus.ACTIVE.value


class CodeRequestOutcome(StrEnum):
    # Código criado; o email vai para quem pediu
    SENT = "sent"
    # Código criado (conta nos limites), mas a conta está bloqueada ou em exclusão: nenhum email
    INACTIVE_ACCOUNT = "inactive_account"
    # Limite por email (1 por minuto ou 5 por hora): nada criado
    RATE_LIMITED = "rate_limited"
    # Teto de envio compartilhado: nada criado; talvez um aviso ao suporte
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
        refused = _check_send_limits(session, settings, email, now)
        if refused is not None:
            return refused
        user = _find_user(session, email)
        code = _issue_code(session, email, CodePurpose.LOGIN, now)
        if user is None:
            locale = pick_locale(None, accept_language)
        else:
            audit.record(session, AuditEvent.CODE_REQUESTED, user_id=user.id, ip=ip)
            if not can_sign_in(user):
                return CodeRequestResult(CodeRequestOutcome.INACTIVE_ACCOUNT)
            locale = pick_locale(user.locale, accept_language)
        quota.record(session, app=IMAGO_APP_NAME, kind=MailKind.CODE, now=now)
        message = LoginCodeEmail(code=code, valid_minutes=CODE_LIFETIME_MINUTES)
        return CodeRequestResult(CodeRequestOutcome.SENT, (OutgoingEmail(email, locale, message),))


def request_delete_code(
    session: Session, settings: Settings, *, user: User, ip: str | None
) -> CodeRequestResult:
    """Cria um código de exclusão de conta para `user` e diz o que responder (202 ou 429).

    Mesmas regras do código de login: limites por email e teto de envio (contados junto com os
    códigos de login), invalidação dos anteriores do mesmo email e propósito, validade e
    tentativas. O código vai para o email atual da conta, no idioma dela, e fica ligado a ela
    (`login_codes.user_id`). Exige estar dentro de `write_transaction`, com `user` relido nela.
    """
    require_write_transaction(session)
    now = utcnow()
    refused = _check_send_limits(session, settings, user.email, now)
    if refused is not None:
        return refused
    code = _issue_code(session, user.email, CodePurpose.DELETE_ACCOUNT, now, user_id=user.id)
    audit.record(session, AuditEvent.DELETE_CODE_REQUESTED, user_id=user.id, ip=ip)
    quota.record(session, app=IMAGO_APP_NAME, kind=MailKind.CODE, now=now)
    message = DeleteCodeEmail(code=code, valid_minutes=CODE_LIFETIME_MINUTES)
    outgoing = OutgoingEmail(user.email, pick_locale(user.locale), message)
    return CodeRequestResult(CodeRequestOutcome.SENT, (outgoing,))


def use_delete_code(session: Session, *, user: User, code: str) -> bool:
    """Confere o código de exclusão de `user` e, se certo, o marca como usado.

    Mesmas regras do `verify_login_code`: a tentativa é contada antes de comparar, só o código
    mais recente do email vale, uma vez só, por `CODE_LIFETIME` e `MAX_CODE_ATTEMPTS`. Código de
    login (outro propósito) ou de outra conta é recusado. Exige `write_transaction`; quem chama
    faz o commit da tentativa também quando a resposta é False.
    """
    require_write_transaction(session)
    now = utcnow()
    login_code = _attempt(
        session, user.email, CodePurpose.DELETE_ACCOUNT, code, now, user_id=user.id
    )
    if login_code is None:
        return False
    login_code.used_at = now
    return True


def _check_send_limits(
    session: Session, settings: Settings, email: str, now: datetime
) -> CodeRequestResult | None:
    """O resultado de recusa (429) se um limite de envio bateu; senão None, já com a limpeza.

    Antes do código novo saem os códigos e as sessões vencidos (`app/retention.py`).
    """
    if _email_limit_reached(session, email, now):
        return CodeRequestResult(CodeRequestOutcome.RATE_LIMITED)
    refusal = quota.check(session, settings, MailKind.CODE, now)
    if refusal is not None:
        alert = quota.support_alert(session, refusal, MailKind.CODE, now)
        if alert is None:
            return CodeRequestResult(CodeRequestOutcome.CAP_REACHED)
        outgoing = OutgoingEmail(settings.support_email, SUPPORT_LOCALE, alert)
        return CodeRequestResult(CodeRequestOutcome.CAP_REACHED, (outgoing,))
    delete_expired_login_codes(session, now)
    delete_expired_sessions(session, now)
    return None


def account_emails(
    session: Session, settings: Settings, emails: Iterable[OutgoingEmail]
) -> tuple[OutgoingEmail, ...]:
    """Reserva cada email de conta no teto de envio e devolve os que podem sair.

    Cada email que coube no teto (tipo `account`) ganha a sua linha no `mail_log`. Se algum foi
    recusado, entra no lugar dele o aviso ao `SUPPORT_EMAIL`, no máximo um por hora
    (`quota.support_alert`). Exige `write_transaction`; quem chama agenda os emails depois do
    commit.
    """
    require_write_transaction(session)
    now = utcnow()
    allowed: list[OutgoingEmail] = []
    for outgoing in emails:
        refusal = quota.reserve(
            session, settings, app=IMAGO_APP_NAME, kind=MailKind.ACCOUNT, now=now
        )
        if refusal is None:
            allowed.append(outgoing)
            continue
        alert = quota.support_alert(session, refusal, MailKind.ACCOUNT, now)
        if alert is not None:
            allowed.append(OutgoingEmail(settings.support_email, SUPPORT_LOCALE, alert))
    return tuple(allowed)


def _email_limit_reached(session: Session, email: str, now: datetime) -> bool:
    return any(
        session.scalar(
            select(func.count())
            .select_from(LoginCode)
            .where(LoginCode.email == email, LoginCode.created_at > now - window)
        )
        >= maximum
        for window, maximum in EMAIL_SEND_LIMITS
    )


def _find_user(session: Session, email: str) -> User | None:
    # populate_existing: relê a linha mesmo que a sessão já tenha o objeto de outra transação
    return session.scalar(
        select(User).where(User.email == email).execution_options(populate_existing=True)
    )


def _issue_code(
    session: Session,
    email: str,
    purpose: CodePurpose,
    now: datetime,
    *,
    user_id: int | None = None,
) -> str:
    """Invalida os códigos anteriores do email e propósito e cria um novo. Devolve o código.

    `user_id`: vazio no login; a conta, nas ações de uma conta existente (exclusão).
    """
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
            user_id=user_id,
            purpose=purpose.value,
            code_hash=hash_secret(code),
            expires_at=now + CODE_LIFETIME,
            created_at=now,
        )
    )
    return code


class VerifyFailure(StrEnum):
    # Código errado, vencido, usado, esgotado, inexistente ou de conta bloqueada ou em exclusão
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
        if login_code is None or (user is not None and not can_sign_in(user)):
            if user is not None:
                audit.record(session, AuditEvent.LOGIN_FAILED, user_id=user.id, ip=ip)
            return VerifyFailure.INVALID_CODE
        if user is None and not is_valid_timezone(timezone):
            return VerifyFailure.INVALID_TIMEZONE

        login_code.used_at = now
        new_account = user is None
        if user is None:
            user = User(
                id=_new_account_id(session),
                email=email,
                status=UserStatus.ACTIVE.value,
                timezone=timezone,
                locale=locale.value,
                terms_version=TERMS_VERSION,
                terms_accepted_at=now,
                created_at=now,
                updated_at=now,
                last_login_at=now,
            )
            session.add(user)
            # A conta antes da sessão e do evento, que apontam para ela (chave estrangeira)
            session.flush()
        else:
            user.last_login_at = now
        token = create_session(session, user.id, now=now, ip=ip, user_agent=user_agent)
        audit.record(
            session, AuditEvent.LOGIN, user_id=user.id, ip=ip, details={"new_account": new_account}
        )
        return LoginResult(user_id=user.id, token=token, new_account=new_account)


def _new_account_id(session: Session) -> int:
    """Sorteia um id de conta que ainda não existe (ver "id da conta" no imago-plan.md)."""
    for _ in range(MAX_ACCOUNT_ID_DRAWS):
        candidate = generate_account_id()
        taken = session.scalar(select(func.count()).select_from(User).where(User.id == candidate))
        if not taken:
            return candidate
    raise RuntimeError("nenhum id de conta livre depois de vários sorteios")


def _attempt(
    session: Session,
    email: str,
    purpose: CodePurpose,
    code: str,
    now: datetime,
    *,
    user_id: int | None = None,
) -> LoginCode | None:
    """Conta uma tentativa no código mais recente e o devolve se `code` bate; senão None.

    Código usado, vencido ou com as tentativas esgotadas é recusado sem contar outra tentativa,
    então `attempts` nunca passa de `MAX_CODE_ATTEMPTS`. Com `user_id`, o código mais recente do
    email e propósito também precisa ser dessa conta (o email pode ter mudado de dono).
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
        or (user_id is not None and login_code.user_id != user_id)
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
