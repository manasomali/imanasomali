"""Tabelas iniciais do imago.

Revision ID: 0001
Revises:
Create Date: 2026-11-08

Escrita e revisada à mão: o autogenerate erra em SQLite. Não importe app.models aqui, porque a
migração tem que continuar igual quando os modelos mudarem. Constraints e índices com o nome
completo, em op.f("..."), seguindo a NAMING_CONVENTION de app/models.py.

- users.id: BIGINT sem AUTOINCREMENT (não vira o rowid do SQLite): o id é sorteado pelo app, de 1
  a 2^53 - 1, e uma conta sem id é recusada pelo NOT NULL. As outras tabelas têm AUTOINCREMENT.
- ON DELETE CASCADE de users para sessions, login_codes e app_tasks; SET NULL em
  audit_log.user_id.
- Datas: DATETIME do SQLAlchemy, sempre em UTC (app.models.UTCDateTime).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTOINCREMENT = {"sqlite_autoincrement": True}
MAX_ACCOUNT_ID = 9007199254740991


def check(sqltext: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sqltext, name=op.f(name))


def fk(column: str, target: str, ondelete: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], ondelete=ondelete, name=op.f(name))


def app_name(column: str) -> str:
    return (
        f"length({column}) BETWEEN 2 AND 27 AND {column} GLOB '[a-z]*' "
        f"AND {column} NOT GLOB '*[^a-z0-9-]*'"
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("status", sa.String(16), server_default=sa.text("'active'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(2), nullable=False),
        sa.Column("terms_version", sa.String(32), nullable=True),
        sa.Column("terms_accepted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        check(f"id BETWEEN 1 AND {MAX_ACCOUNT_ID}", "ck_users_id_range"),
        check("email = lower(trim(email))", "ck_users_email_normalized"),
        check("email NOT GLOB '*[^ -~]*'", "ck_users_email_ascii"),
        check("length(email) BETWEEN 3 AND 254", "ck_users_email_length"),
        check("status IN ('active', 'deleting')", "ck_users_status"),
        check("length(timezone) BETWEEN 1 AND 64", "ck_users_timezone_length"),
        check("locale IN ('pt', 'en')", "ck_users_locale"),
        check("length(terms_version) BETWEEN 1 AND 32", "ck_users_terms_version_length"),
        check("(terms_version IS NULL) = (terms_accepted_at IS NULL)", "ck_users_terms_accepted"),
    )

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sessions")),
        fk("user_id", "users.id", "CASCADE", "fk_sessions_user_id_users"),
        check("length(token_hash) = 64", "ck_sessions_token_hash_length"),
        check("length(ip) BETWEEN 1 AND 45", "ck_sessions_ip_length"),
        check("length(user_agent) BETWEEN 0 AND 512", "ck_sessions_user_agent_length"),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"])

    op.create_table(
        "login_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_codes")),
        fk("user_id", "users.id", "CASCADE", "fk_login_codes_user_id_users"),
        check("purpose IN ('login', 'delete_account')", "ck_login_codes_purpose"),
        check("length(code_hash) = 64", "ck_login_codes_code_hash_length"),
        check("attempts >= 0", "ck_login_codes_attempts_not_negative"),
        **AUTOINCREMENT,
    )
    op.create_index(op.f("ix_login_codes_email_created_at"), "login_codes", ["email", "created_at"])
    op.create_index(op.f("ix_login_codes_created_at"), "login_codes", ["created_at"])
    op.create_index(op.f("ix_login_codes_user_id"), "login_codes", ["user_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        fk("user_id", "users.id", "SET NULL", "fk_audit_log_user_id_users"),
        check("length(event) BETWEEN 1 AND 64", "ck_audit_log_event_length"),
        check("length(ip) BETWEEN 1 AND 45", "ck_audit_log_ip_length"),
        check("json_valid(details)", "ck_audit_log_details_json"),
        **AUTOINCREMENT,
    )
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])
    op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"])
    op.create_index(op.f("ix_audit_log_event_created_at"), "audit_log", ["event", "created_at"])

    op.create_table(
        "mail_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("app", sa.String(27), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_log")),
        check(app_name("app"), "ck_mail_log_app"),
        check("kind IN ('code', 'account', 'notification')", "ck_mail_log_kind"),
        **AUTOINCREMENT,
    )
    op.create_index(op.f("ix_mail_log_created_at"), "mail_log", ["created_at"])

    op.create_table(
        "app_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("app", sa.String(27), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_tasks")),
        fk("user_id", "users.id", "CASCADE", "fk_app_tasks_user_id_users"),
        check(app_name("app"), "ck_app_tasks_app"),
        check("action IN ('delete', 'refresh')", "ck_app_tasks_action"),
        check("attempts >= 0", "ck_app_tasks_attempts_not_negative"),
        **AUTOINCREMENT,
    )
    # No máximo uma tarefa pendente por (user_id, app, action)
    op.create_index(
        "uq_app_tasks_pending",
        "app_tasks",
        ["user_id", "app", "action"],
        unique=True,
        sqlite_where=sa.text("done_at IS NULL"),
    )
    op.create_index(op.f("ix_app_tasks_done_at"), "app_tasks", ["done_at"])


def downgrade() -> None:
    op.drop_table("app_tasks")
    op.drop_table("mail_log")
    op.drop_table("audit_log")
    op.drop_table("login_codes")
    op.drop_table("sessions")
    op.drop_table("users")
