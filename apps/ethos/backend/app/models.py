"""Modelos do banco (SQLAlchemy 2), espelho da migração em migrations/versions.

Convenções:

- Datas e horas: sempre em UTC. A coluna `UTCDateTime` só aceita datetime com fuso (converte
  para UTC antes de gravar) e devolve datetime com `tzinfo=UTC`. No arquivo, ficam no formato
  de largura fixa do SQLAlchemy ("2026-01-31 12:00:00.000000", sem fuso), então comparar como
  texto é o mesmo que comparar as datas. Compare sempre com parâmetros (datetime com fuso), nunca
  com `datetime('now')` do SQLite, que tem outro formato.
- Dinheiro: centavos em inteiros (`*_cents`), nunca float.
- Enums: texto, com `CHECK` no banco. Os valores válidos são os das classes `StrEnum` abaixo.
- Tamanhos fixos do plano: `CHECK` no banco, além da validação da API. Os limites que vêm do
  ambiente (ex.: `MAX_NOTE_LENGTH`) ficam só na API, porque o banco não muda com a config.
- Ids inteiros com AUTOINCREMENT: um id apagado nunca volta para outra linha. A auditoria e o
  log de exclusões guardam ids numéricos, que não podem passar a apontar para outra conta.
- Exclusão: `ON DELETE CASCADE` no que é do usuário e do hábito; `SET NULL` na autoria em dados
  de outras pessoas (`marks.user_id`, `audit_log.user_id`) e em `banners.created_by`. Depende do
  `PRAGMA foreign_keys=ON` que o `app/db.py` liga em toda conexão.

Qualquer mudança aqui vai junto com uma migração nova, escrita e revisada à mão; o teste de
drift (tests/test_migrations.py) compara os dois.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Mesmos idiomas do front e dos emails (users.locale)
from app.mail.language import Locale

# Nomes previsíveis para toda constraint e índice: o modo batch do Alembic no SQLite recria a
# tabela e só consegue apagar ou alterar uma constraint pelo nome
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Tamanhos fixos do plano ("tamanhos e formatos")
EMAIL_MAX_LENGTH = 254
HABIT_NAME_MAX_LENGTH = 60
HABIT_DESCRIPTION_MAX_LENGTH = 500
HABIT_REWARD_MAX_LENGTH = 140
HABIT_PUNISHMENT_MAX_LENGTH = 140
HABIT_CODE_MAX_LENGTH = 4
BANNER_TEXT_MAX_LENGTH = 280
DEFAULT_SCORE_THRESHOLD = 70
# Nomes de fuso IANA têm até ~32 caracteres; a validação de verdade é do zoneinfo, na API
TIMEZONE_MAX_LENGTH = 64
# sha256 em hexadecimal (app/auth/security.py: hash_secret)
SECRET_HASH_LENGTH = 64
# IPv6 por extenso com IPv4 no fim
IP_MAX_LENGTH = 45
USER_AGENT_MAX_LENGTH = 512
TERMS_VERSION_MAX_LENGTH = 32
EVENT_MAX_LENGTH = 64


class CodePurpose(StrEnum):
    LOGIN = "login"
    DELETE_ACCOUNT = "delete_account"


class HabitColor(StrEnum):
    """Paleta fixa de 12 cores. No banco fica o nome; o hex de cada tema fica no front."""

    RED = "red"
    ORANGE = "orange"
    AMBER = "amber"
    YELLOW = "yellow"
    LIME = "lime"
    GREEN = "green"
    TEAL = "teal"
    CYAN = "cyan"
    BLUE = "blue"
    INDIGO = "indigo"
    VIOLET = "violet"
    PINK = "pink"


class GoalType(StrEnum):
    MIN = "min"
    MAX = "max"
    EXACT = "exact"


class Period(StrEnum):
    """Período da meta (`goal_period`) e do limite de custo (`cost_limit_period`)."""

    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class CostLevel(StrEnum):
    HABIT = "habit"
    MARK = "mark"


class HabitStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class MemberRole(StrEnum):
    """Papel de um convidado. O dono não tem linha em habit_members: é `habits.owner_id`."""

    VIEWER = "viewer"
    EDITOR = "editor"


class AlertFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


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


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: UTCDateTime}  # noqa: RUF012 (atributo de classe do SQLAlchemy)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Salvo com strip + lower pela API; aqui só a rede de segurança. O lower() do SQLite só
        # mexe em ASCII, então um email já passado pelo str.lower() do Python sempre passa
        CheckConstraint("email = lower(trim(email))", name="email_normalized"),
        CheckConstraint(_max_length("email", EMAIL_MAX_LENGTH, minimum=3), name="email_length"),
        CheckConstraint(_max_length("timezone", TIMEZONE_MAX_LENGTH), name="timezone_length"),
        CheckConstraint(_in("locale", Locale), name="locale"),
        CheckConstraint(
            _max_length("terms_version", TERMS_VERSION_MAX_LENGTH), name="terms_version_length"
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    # false: conta bloqueada pelo admin (não recebe código nem entra; os dados ficam)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("1"))
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    # Fuso IANA, só preferência: usado para pontuação e alertas
    timezone: Mapped[str] = mapped_column(String(TIMEZONE_MAX_LENGTH))
    locale: Mapped[str] = mapped_column(String(2))
    # Versão dos termos aceita. A conta já nasce com o aceite da versão atual
    terms_version: Mapped[str] = mapped_column(String(TERMS_VERSION_MAX_LENGTH))
    terms_accepted_at: Mapped[datetime]
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
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Apagado (NULL) depois de 90 dias pelo cleanup
    ip: Mapped[str | None] = mapped_column(String(IP_MAX_LENGTH))
    user_agent: Mapped[str | None] = mapped_column(String(USER_AGENT_MAX_LENGTH))


class LoginCode(Base):
    """Código de 6 dígitos mandado por email (login ou confirmação de ação da conta)."""

    __tablename__ = "login_codes"
    __table_args__ = (
        CheckConstraint(_in("purpose", CodePurpose), name="purpose"),
        CheckConstraint(f"length(code_hash) = {SECRET_HASH_LENGTH}", name="code_hash_length"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        # Limite por email (1 por minuto, 5 por hora) e invalidação dos anteriores
        Index(None, "email", "created_at"),
        # Teto global por hora e por dia
        Index(None, "created_at"),
        # Limpeza dos vencidos
        Index(None, "expires_at"),
        Index(None, "user_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Destino do código, já normalizado (strip + lower)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH))
    # Vazio no login; preenchido nas ações de uma conta existente (ex.: exclusão)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(SECRET_HASH_LENGTH))
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    """Eventos de auth, de configuração e de marcações. A lista de eventos fica em app/audit.py."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(_max_length("event", EVENT_MAX_LENGTH), name="event_length"),
        CheckConstraint(_max_length("ip", IP_MAX_LENGTH), name="ip_length"),
        CheckConstraint("json_valid(details)", name="details_json"),
        # Limpeza por data (retenção de 90 dias)
        Index(None, "created_at"),
        # Anonimização na exclusão da conta
        Index(None, "user_id"),
        # Histórico do hábito
        Index(None, "habit_id", "created_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Quem fez; NULL quando a conta foi apagada ("usuário removido") ou em evento do sistema
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Hábito a que o evento se refere: apagar o hábito apaga a auditoria dele junto
    habit_id: Mapped[int | None] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(EVENT_MAX_LENGTH))
    ip: Mapped[str | None] = mapped_column(String(IP_MAX_LENGTH))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))


class Habit(Base):
    __tablename__ = "habits"
    __table_args__ = (
        CheckConstraint(_max_length("name", HABIT_NAME_MAX_LENGTH), name="name_length"),
        # Sigla salva em maiúsculas (o upper() do SQLite só mexe em ASCII, como no email)
        CheckConstraint(
            f"{_max_length('code', HABIT_CODE_MAX_LENGTH)} AND code = upper(code)", name="code"
        ),
        CheckConstraint(
            _max_length("description", HABIT_DESCRIPTION_MAX_LENGTH, minimum=0),
            name="description_length",
        ),
        CheckConstraint(_in("color", HabitColor), name="color"),
        CheckConstraint(_in("goal_type", GoalType), name="goal_type"),
        # N ≥ 1 em min e exact; N = 0 só em max. O teto depende do período e da config (API)
        CheckConstraint(
            "goal_count >= 1 OR (goal_type = 'max' AND goal_count = 0)", name="goal_count"
        ),
        CheckConstraint(_in("goal_period", Period), name="goal_period"),
        CheckConstraint("duration_minutes > 0", name="duration_minutes_positive"),
        CheckConstraint("score_threshold BETWEEN 1 AND 100", name="score_threshold"),
        CheckConstraint(
            _max_length("reward", HABIT_REWARD_MAX_LENGTH, minimum=0), name="reward_length"
        ),
        CheckConstraint(
            _max_length("punishment", HABIT_PUNISHMENT_MAX_LENGTH, minimum=0),
            name="punishment_length",
        ),
        CheckConstraint(_in("cost_level", CostLevel), name="cost_level"),
        CheckConstraint("cost_cents >= 0", name="cost_cents_not_negative"),
        CheckConstraint("cost_limit_cents >= 0", name="cost_limit_cents_not_negative"),
        CheckConstraint(_in("cost_limit_period", Period), name="cost_limit_period"),
        # O limite de custo e o período dele vêm juntos ou não vêm
        CheckConstraint(
            "(cost_limit_cents IS NULL) = (cost_limit_period IS NULL)", name="cost_limit_pair"
        ),
        CheckConstraint(_in("status", HabitStatus), name="status"),
        CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)", name="archived_at_status"
        ),
        # Listagem e limite de hábitos por dono (ativos + pausados)
        Index(None, "owner_id", "status"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(HABIT_NAME_MAX_LENGTH))
    # Sigla opcional; quando definida, aparece no lugar do nome
    code: Mapped[str | None] = mapped_column(String(HABIT_CODE_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(String(HABIT_DESCRIPTION_MAX_LENGTH))
    color: Mapped[str] = mapped_column(String(16))
    goal_type: Mapped[str] = mapped_column(String(8))
    goal_count: Mapped[int]
    goal_period: Mapped[str] = mapped_column(String(8))
    # false: toggle (uma marcação por dia); true: várias marcações por dia
    multi_mark: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    # Recursos opcionais, desligados por padrão. Desligar não apaga os valores: voltam ao religar
    duration_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    duration_minutes: Mapped[int | None]
    notes_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    score_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    score_threshold: Mapped[int] = mapped_column(
        default=DEFAULT_SCORE_THRESHOLD, server_default=text(str(DEFAULT_SCORE_THRESHOLD))
    )
    reward: Mapped[str | None] = mapped_column(String(HABIT_REWARD_MAX_LENGTH))
    punishment: Mapped[str | None] = mapped_column(String(HABIT_PUNISHMENT_MAX_LENGTH))
    cost_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    cost_level: Mapped[str] = mapped_column(
        String(8), default=CostLevel.HABIT.value, server_default=text("'habit'")
    )
    # Valor fixo (nível hábito) ou padrão sugerido (nível marcação)
    cost_cents: Mapped[int | None]
    cost_limit_cents: Mapped[int | None]
    cost_limit_period: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(
        String(8), default=HabitStatus.ACTIVE.value, server_default=text("'active'")
    )
    # Preenchido só com status archived: a pontuação congela nessa data
    archived_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class HabitPause(Base):
    """Intervalo de pausa. `ended_at` vazio: pausa em andamento (no máximo uma por hábito)."""

    __tablename__ = "habit_pauses"
    __table_args__ = (
        CheckConstraint("ended_at >= started_at", name="ended_after_started"),
        Index(None, "habit_id", "started_at"),
        Index(
            "uq_habit_pauses_open",
            "habit_id",
            unique=True,
            sqlite_where=text("ended_at IS NULL"),
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]


class HabitMember(Base):
    """Convidado que aceitou o convite. O dono não entra aqui."""

    __tablename__ = "habit_members"
    __table_args__ = (
        CheckConstraint(_in("role", MemberRole), name="role"),
        # Hábitos compartilhados com o usuário (a chave primária já cobre a busca por hábito)
        Index(None, "user_id"),
    )

    habit_id: Mapped[int] = mapped_column(
        ForeignKey("habits.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(8))
    joined_at: Mapped[datetime] = mapped_column(default=utcnow)


class HabitInvite(Base):
    """Convite pendente. Aceito, recusado ou cancelado, a linha sai."""

    __tablename__ = "habit_invites"
    __table_args__ = (
        CheckConstraint("email = lower(trim(email))", name="email_normalized"),
        CheckConstraint(_max_length("email", EMAIL_MAX_LENGTH, minimum=3), name="email_length"),
        CheckConstraint(_in("role", MemberRole), name="role"),
        # Um convite pendente por email em cada hábito (também cobre a busca por hábito)
        UniqueConstraint("habit_id", "email"),
        # Convites recebidos
        Index(None, "invited_user_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH))
    # Vazio se o email não tinha conta no convite: esse convite nunca é entregue
    invited_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Mark(Base):
    __tablename__ = "marks"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="duration_minutes_positive"),
        CheckConstraint("cost_cents >= 0", name="cost_cents_not_negative"),
        # Calendário, toggle, limite diário e pontuação: marcações do hábito num intervalo
        Index(None, "habit_id", "marked_at"),
        # Anonimização na exclusão da conta (SET NULL)
        Index(None, "user_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    # Autor; NULL depois que a conta dele é apagada ("usuário removido")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    marked_at: Mapped[datetime]
    duration_minutes: Mapped[int | None]
    # Custo gravado na criação: mudar o custo do hábito não reescreve o passado
    cost_cents: Mapped[int | None]
    # Tamanho máximo vem de MAX_NOTE_LENGTH (config), validado na API
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Alert(Base):
    """Configuração de alerta de um membro (dono ou editor) num hábito."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("hour BETWEEN 0 AND 23", name="hour"),
        CheckConstraint(_in("frequency", AlertFrequency), name="frequency"),
        # 0 = segunda ... 6 = domingo (datetime.weekday(); semana ISO)
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),
        # O semanal precisa do dia; o diário pode guardar o último escolhido
        CheckConstraint("frequency = 'daily' OR weekday IS NOT NULL", name="weekly_weekday"),
        Index(None, "user_id"),
    )

    habit_id: Mapped[int] = mapped_column(
        ForeignKey("habits.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    goal_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    cost_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    # Hora cheia no fuso do usuário (users.timezone)
    hour: Mapped[int]
    frequency: Mapped[str] = mapped_column(String(8))
    weekday: Mapped[int | None]
    last_sent_at: Mapped[datetime | None]


class Banner(Base):
    """Aviso global. Se houver mais de um na janela de datas, vale o mais recente."""

    __tablename__ = "banners"
    __table_args__ = (
        CheckConstraint(_max_length("text_pt", BANNER_TEXT_MAX_LENGTH), name="text_pt_length"),
        CheckConstraint(_max_length("text_en", BANNER_TEXT_MAX_LENGTH), name="text_en_length"),
        CheckConstraint("ends_at > starts_at", name="ends_after_starts"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    text_pt: Mapped[str] = mapped_column(String(BANNER_TEXT_MAX_LENGTH))
    text_en: Mapped[str] = mapped_column(String(BANNER_TEXT_MAX_LENGTH))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    # Admin que criou; o banner fica se a conta dele for apagada
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
