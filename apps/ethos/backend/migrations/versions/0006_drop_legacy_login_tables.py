"""Saem as tabelas do login próprio de antes do imago: `sessions` e `login_codes`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09

Escrita à mão, como as anteriores (sem importar app.models). A 0005 esvaziou as duas tabelas, e
nenhum código no ar depois dela as lê ou grava: um rollback deste deploy volta para um código que
só as declara nos modelos, sem nunca consultá-las. O `DROP TABLE` leva junto os índices e a linha
de `login_codes` no `sqlite_sequence`.

A coluna `audit_log.ip`, o outro legado da 0005, fica para a 0007, num deploy seguinte: o código
de antes deste deploy ainda a mapeia, e o ORM a cita em todo INSERT no `audit_log`; o deste a
deixa fora do mapeamento (`Unmapped` em app/models.py), e é para ele que o rollback da 0007 volta.

Downgrade: recria as duas tabelas vazias, como estavam depois da 0005 (as chaves estrangeiras já
apontando para `app_users(user_id)`, com o nome de antes do rename de `users`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def check(sqltext: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sqltext, name=op.f(name))


def user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"],
        ["app_users.user_id"],
        ondelete="CASCADE",
        name=op.f(f"fk_{table}_user_id_users"),
    )


def upgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("login_codes")


def downgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sessions")),
        user_fk("sessions"),
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
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_codes")),
        user_fk("login_codes"),
        check("purpose IN ('login', 'delete_account')", "ck_login_codes_purpose"),
        check("length(code_hash) = 64", "ck_login_codes_code_hash_length"),
        check("attempts >= 0", "ck_login_codes_attempts_not_negative"),
        sqlite_autoincrement=True,
    )
    op.create_index(op.f("ix_login_codes_email_created_at"), "login_codes", ["email", "created_at"])
    op.create_index(op.f("ix_login_codes_created_at"), "login_codes", ["created_at"])
    op.create_index(op.f("ix_login_codes_expires_at"), "login_codes", ["expires_at"])
    op.create_index(op.f("ix_login_codes_user_id"), "login_codes", ["user_id"])
