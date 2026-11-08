"""Modelos do banco (SQLAlchemy 2), espelho da migração em migrations/versions.

Convenções:

- Datas e horas: sempre em UTC. A coluna `UTCDateTime` só aceita datetime com fuso (converte
  para UTC antes de gravar) e devolve datetime com `tzinfo=UTC`. No arquivo, ficam no formato
  de largura fixa do SQLAlchemy ("2026-01-31 12:00:00.000000", sem fuso), então comparar como
  texto é o mesmo que comparar as datas. Compare sempre com parâmetros (datetime com fuso), nunca
  com `datetime('now')` do SQLite, que tem outro formato.
- Enums: texto, com `CHECK` no banco. Os valores válidos são os das classes `StrEnum`.
- Tamanhos fixos do plano: `CHECK` no banco, além da validação da API.
- `users.id`: inteiro aleatório de 1 a 2^53 - 1 (`app/auth/security.py`), sorteado ao criar a
  conta, nunca sequencial (ver "id da conta" no imago-plan.md). A coluna é `BIGINT` de propósito:
  no SQLite, só `INTEGER PRIMARY KEY` vira o rowid, que se preenche sozinho com o maior id + 1.
  Com `BIGINT`, inserir uma conta sem id é recusado (NOT NULL) em vez de ganhar um id sequencial.
- As outras tabelas têm ids inteiros com AUTOINCREMENT: um id apagado nunca volta.
- Exclusão: `ON DELETE CASCADE` de `users` para `sessions`, `login_codes` e `app_tasks`;
  `SET NULL` em `audit_log.user_id`. Depende do `PRAGMA foreign_keys=ON` que o `app/db.py` liga
  em toda conexão.
- Nome de aplicação (`mail_log.app`, `app_tasks.app`): a regra do `infra/databases.txt`
  (`^[a-z][a-z0-9-]{1,26}$`), também no `CHECK`.

Qualquer mudança aqui vai junto com uma migração nova, escrita e revisada à mão; o teste de
drift (tests/test_migrations.py) compara os dois.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    MetaData,
    String,
    TypeDecorator,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.mail.kinds import MailKind

# Mesmos idiomas do front e dos emails (users.locale)
from app.mail.language import Locale

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Maior id de conta: o maior inteiro que cabe num Number do javascript sem perder precisão
MAX_ACCOUNT_ID = 2**53 - 1

# Tamanhos fixos do plano ("tamanhos e formatos")
EMAIL_MAX_LENGTH = 254
# Nomes de fuso IANA têm até ~32 caracteres; a validação de verdade é do zoneinfo, na API
TIMEZONE_MAX_LENGTH = 64
# sha256 em hexadecimal (app/auth/security.py: hash_secret)
SECRET_HASH_LENGTH = 64
# IPv6 por extenso com IPv4 no fim
IP_MAX_LENGTH = 45
USER_AGENT_MAX_LENGTH = 512
TERMS_VERSION_MAX_LENGTH = 32
EVENT_MAX_LENGTH = 64
# Nome de aplicação: ^[a-z][a-z0-9-]{1,26}$
APP_NAME_MAX_LENGTH = 27


class UserStatus(StrEnum):
    ACTIVE = "active"
    # Exclusão em andamento: a conta não entra nem recebe código, e o email não cria conta nova,
    # até as aplicações apagarem os dados dela e a linha sair (ETH-61)
    DELETING = "deleting"


class CodePurpose(StrEnum):
    LOGIN = "login"
    DELETE_ACCOUNT = "delete_account"


class TaskAction(StrEnum):
    """Tarefa do imago para uma aplicação (`app_tasks`, ETH-59)."""

    # POST /internal/users/{id}/delete na aplicação
    DELETE = "delete"
    # POST /internal/users/{id}/refresh na aplicação, com email, idioma e fuso atuais
    REFRESH = "refresh"


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Data e hora em UTC: recusa datetime sem fuso e devolve sempre com `tzinfo=UTC`."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            # date ou texto gravariam outro formato e quebrariam a comparação como texto
            raise TypeError(f"esperava datetime, recebeu {type(value).__name__}")
        if value.tzinfo is None or value.utcoffset() is None:
            # Sem fuso não dá para saber que instante é; gravar assim seria um erro silencioso
            raise ValueError("datetime sem fuso: use datetime com tzinfo (ex.: UTC)")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def _in(column: str, enum: type[StrEnum]) -> str:
    """Condição de CHECK que aceita só os valores do enum."""
    values = ", ".join(f"'{member.value}'" for member in enum)
    return f"{column} IN ({values})"


def _max_length(column: str, maximum: int, minimum: int = 1) -> str:
    # length() conta caracteres (não bytes) em texto, como o len() do Python. Coluna NULL passa
    return f"length({column}) BETWEEN {minimum} AND {maximum}"


def _app_name(column: str) -> str:
    # GLOB diferencia maiúsculas e minúsculas: começa com letra e só tem [a-z0-9-]
    return (
        f"{_max_length(column, APP_NAME_MAX_LENGTH, minimum=2)} AND {column} GLOB '[a-z]*' "
        f"AND {column} NOT GLOB '*[^a-z0-9-]*'"
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: UTCDateTime}  # noqa: RUF012 (atributo de classe do SQLAlchemy)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"id BETWEEN 1 AND {MAX_ACCOUNT_ID}", name="id_range"),
        # Salvo com strip + lower pela API; aqui só a rede de segurança. Só ASCII imprimível
        # (vai no header X-User-Email), então o lower() do SQLite, que só mexe em ASCII, basta
        CheckConstraint("email = lower(trim(email))", name="email_normalized"),
        CheckConstraint("email NOT GLOB '*[^ -~]*'", name="email_ascii"),
        CheckConstraint(_max_length("email", EMAIL_MAX_LENGTH, minimum=3), name="email_length"),
        CheckConstraint(_in("status", UserStatus), name="status"),
        CheckConstraint(_max_length("timezone", TIMEZONE_MAX_LENGTH), name="timezone_length"),
        CheckConstraint(_in("locale", Locale), name="locale"),
        CheckConstraint(
            _max_length("terms_version", TERMS_VERSION_MAX_LENGTH), name="terms_version_length"
        ),
        # Os dois vazios só numa conta que ainda não aceitou nenhuma versão (importada do ethos)
        CheckConstraint(
            "(terms_version IS NULL) = (terms_accepted_at IS NULL)", name="terms_accepted"
        ),
    )

    # Aleatório, sorteado pelo app (ver o docstring do módulo)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    status: Mapped[str] = mapped_column(
        String(16), default=UserStatus.ACTIVE.value, server_default=text("'active'")
    )
    # false: conta bloqueada pelo admin (não recebe código nem entra; os dados ficam)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("1"))
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    # Fuso IANA: nasce com o do navegador no primeiro login e só muda pelo PATCH /me
    timezone: Mapped[str] = mapped_column(String(TIMEZONE_MAX_LENGTH))
    locale: Mapped[str] = mapped_column(String(2))
    # Versão dos termos aceita (app/terms.py). Conta nova já nasce com o aceite da versão atual
    terms_version: Mapped[str | None] = mapped_column(String(TERMS_VERSION_MAX_LENGTH))
    terms_accepted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None]


class UserSession(Base):
    """Sessão de login. O token fica só no cookie; aqui, o sha256 dele."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(f"length(token_hash) = {SECRET_HASH_LENGTH}", name="token_hash_length"),
        CheckConstraint(_max_length("ip", IP_MAX_LENGTH), name="ip_length"),
        CheckConstraint(
            _max_length("user_agent", USER_AGENT_MAX_LENGTH, minimum=0), name="user_agent_length"
        ),
        Index(None, "user_id"),
        # Limpeza das vencidas
        Index(None, "expires_at"),
    )

    token_hash: Mapped[str] = mapped_column(String(SECRET_HASH_LENGTH), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Apagado (NULL) depois de 90 dias pelo cleanup
    ip: Mapped[str | None] = mapped_column(String(IP_MAX_LENGTH))
    user_agent: Mapped[str | None] = mapped_column(String(USER_AGENT_MAX_LENGTH))


class LoginCode(Base):
    """Código de 6 dígitos mandado por email (login ou confirmação da exclusão da conta)."""

    __tablename__ = "login_codes"
    __table_args__ = (
        CheckConstraint(_in("purpose", CodePurpose), name="purpose"),
        CheckConstraint(f"length(code_hash) = {SECRET_HASH_LENGTH}", name="code_hash_length"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        # Limite por email (1 por minuto, 5 por hora) e invalidação dos anteriores
        Index(None, "email", "created_at"),
        # Limpeza
        Index(None, "created_at"),
        Index(None, "user_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Destino do código, já normalizado (strip + lower)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH))
    # Vazio no login; preenchido nas ações de uma conta existente (exclusão)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    purpose: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(SECRET_HASH_LENGTH))
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    """Eventos de auth, da conta e do admin. A lista de eventos fica em app/audit.py."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(_max_length("event", EVENT_MAX_LENGTH), name="event_length"),
        CheckConstraint(_max_length("ip", IP_MAX_LENGTH), name="ip_length"),
        CheckConstraint("json_valid(details)", name="details_json"),
        # Limpeza por data (retenção de 90 dias)
        Index(None, "created_at"),
        # Exclusão da conta (apaga os eventos dela)
        Index(None, "user_id"),
        # Último aviso de teto (send_cap_reached) e limpeza dos eventos de auth
        Index(None, "event", "created_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Quem fez; NULL quando a conta foi apagada ou em evento do sistema
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    event: Mapped[str] = mapped_column(String(EVENT_MAX_LENGTH))
    ip: Mapped[str | None] = mapped_column(String(IP_MAX_LENGTH))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))


class MailLog(Base):
    """Um email que saiu (ou ia sair) pelo teto compartilhado. Nunca o destinatário."""

    __tablename__ = "mail_log"
    __table_args__ = (
        CheckConstraint(_app_name("app"), name="app"),
        CheckConstraint(_in("kind", MailKind), name="kind"),
        # Janelas móveis de 24 h e 1 h, e a limpeza de 48 h
        Index(None, "created_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Quem mandou: "imago" ou o nome da aplicação do token
    app: Mapped[str] = mapped_column(String(APP_NAME_MAX_LENGTH))
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AppTask(Base):
    """Tarefa do imago para uma aplicação: apagar ou atualizar a cópia da conta (ETH-59)."""

    __tablename__ = "app_tasks"
    __table_args__ = (
        CheckConstraint(_app_name("app"), name="app"),
        CheckConstraint(_in("action", TaskAction), name="action"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        # No máximo uma tarefa pendente por (user_id, app, action): pedir outra com uma pendente
        # não cria linha nova. Serve também para achar as pendentes (done_at IS NULL)
        Index(
            "uq_app_tasks_pending",
            "user_id",
            "app",
            "action",
            unique=True,
            sqlite_where=text("done_at IS NULL"),
        ),
        # Limpeza das concluídas há mais de 7 dias
        Index(None, "done_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    app: Mapped[str] = mapped_column(String(APP_NAME_MAX_LENGTH))
    action: Mapped[str] = mapped_column(String(16))
    # Tentativas que falharam seguidas; a partir da 5ª, cada falha vira uma linha de erro no log
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None]
    done_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
