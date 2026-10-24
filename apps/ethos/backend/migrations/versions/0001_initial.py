"""Tabelas iniciais do ethos.

Revision ID: 0001
Revises:
Create Date: 2026-10-24

Escrita e revisada à mão: o autogenerate erra em SQLite. Não importe app.models aqui, porque a
migração tem que continuar igual quando os modelos mudarem. Constraints e índices com o nome
completo, em op.f("..."), seguindo a NAMING_CONVENTION de app/models.py.

- Ids inteiros com AUTOINCREMENT (sqlite_autoincrement): um id apagado nunca é reusado.
- ON DELETE CASCADE no que é do usuário e do hábito; SET NULL em marks.user_id,
  audit_log.user_id e banners.created_by.
- Datas: DATETIME do SQLAlchemy, sempre em UTC (app.models.UTCDateTime). Dinheiro: centavos
  inteiros.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLORS = (
    "'red', 'orange', 'amber', 'yellow', 'lime', 'green', "
    "'teal', 'cyan', 'blue', 'indigo', 'violet', 'pink'"
)
PERIODS = "'week', 'month', 'year'"
ROLES = "'viewer', 'editor'"
AUTOINCREMENT = {"sqlite_autoincrement": True}


def check(sqltext: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sqltext, name=op.f(name))


def fk(column: str, target: str, ondelete: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], ondelete=ondelete, name=op.f(name))


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(2), nullable=False),
        sa.Column("terms_version", sa.String(32), nullable=False),
        sa.Column("terms_accepted_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        check("email = lower(trim(email))", "ck_users_email_normalized"),
        check("length(email) BETWEEN 3 AND 254", "ck_users_email_length"),
        check("length(timezone) BETWEEN 1 AND 64", "ck_users_timezone_length"),
        check("locale IN ('pt', 'en')", "ck_users_locale"),
        check("length(terms_version) BETWEEN 1 AND 32", "ck_users_terms_version_length"),
        **AUTOINCREMENT,
    )

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
        sa.Column("user_id", sa.Integer(), nullable=True),
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
    op.create_index(op.f("ix_login_codes_expires_at"), "login_codes", ["expires_at"])
    op.create_index(op.f("ix_login_codes_user_id"), "login_codes", ["user_id"])

    op.create_table(
        "habits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("code", sa.String(4), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("color", sa.String(16), nullable=False),
        sa.Column("goal_type", sa.String(8), nullable=False),
        sa.Column("goal_count", sa.Integer(), nullable=False),
        sa.Column("goal_period", sa.String(8), nullable=False),
        sa.Column("multi_mark", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("duration_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("notes_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("score_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("score_threshold", sa.Integer(), server_default=sa.text("70"), nullable=False),
        sa.Column("reward", sa.String(140), nullable=True),
        sa.Column("punishment", sa.String(140), nullable=True),
        sa.Column("cost_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_level", sa.String(8), server_default=sa.text("'habit'"), nullable=False),
        sa.Column("cost_cents", sa.Integer(), nullable=True),
        sa.Column("cost_limit_cents", sa.Integer(), nullable=True),
        sa.Column("cost_limit_period", sa.String(8), nullable=True),
        sa.Column("status", sa.String(8), server_default=sa.text("'active'"), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_habits")),
        fk("owner_id", "users.id", "CASCADE", "fk_habits_owner_id_users"),
        check("length(name) BETWEEN 1 AND 60", "ck_habits_name_length"),
        check("length(code) BETWEEN 1 AND 4 AND code = upper(code)", "ck_habits_code"),
        check("length(description) BETWEEN 0 AND 500", "ck_habits_description_length"),
        check(f"color IN ({COLORS})", "ck_habits_color"),
        check("goal_type IN ('min', 'max', 'exact')", "ck_habits_goal_type"),
        check("goal_count >= 1 OR (goal_type = 'max' AND goal_count = 0)", "ck_habits_goal_count"),
        check(f"goal_period IN ({PERIODS})", "ck_habits_goal_period"),
        check("duration_minutes > 0", "ck_habits_duration_minutes_positive"),
        check("score_threshold BETWEEN 1 AND 100", "ck_habits_score_threshold"),
        check("length(reward) BETWEEN 0 AND 140", "ck_habits_reward_length"),
        check("length(punishment) BETWEEN 0 AND 140", "ck_habits_punishment_length"),
        check("cost_level IN ('habit', 'mark')", "ck_habits_cost_level"),
        check("cost_cents >= 0", "ck_habits_cost_cents_not_negative"),
        check("cost_limit_cents >= 0", "ck_habits_cost_limit_cents_not_negative"),
        check(f"cost_limit_period IN ({PERIODS})", "ck_habits_cost_limit_period"),
        check(
            "(cost_limit_cents IS NULL) = (cost_limit_period IS NULL)", "ck_habits_cost_limit_pair"
        ),
        check("status IN ('active', 'paused', 'archived')", "ck_habits_status"),
        check("(status = 'archived') = (archived_at IS NOT NULL)", "ck_habits_archived_at_status"),
        **AUTOINCREMENT,
    )
    op.create_index(op.f("ix_habits_owner_id_status"), "habits", ["owner_id", "status"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("habit_id", sa.Integer(), nullable=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        fk("user_id", "users.id", "SET NULL", "fk_audit_log_user_id_users"),
        fk("habit_id", "habits.id", "CASCADE", "fk_audit_log_habit_id_habits"),
        check("length(event) BETWEEN 1 AND 64", "ck_audit_log_event_length"),
        check("length(ip) BETWEEN 1 AND 45", "ck_audit_log_ip_length"),
        check("json_valid(details)", "ck_audit_log_details_json"),
        **AUTOINCREMENT,
    )
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])
    op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"])
    op.create_index(
        op.f("ix_audit_log_habit_id_created_at"), "audit_log", ["habit_id", "created_at"]
    )

    op.create_table(
        "habit_pauses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_habit_pauses")),
        fk("habit_id", "habits.id", "CASCADE", "fk_habit_pauses_habit_id_habits"),
        check("ended_at >= started_at", "ck_habit_pauses_ended_after_started"),
        **AUTOINCREMENT,
    )
    op.create_index(
        op.f("ix_habit_pauses_habit_id_started_at"), "habit_pauses", ["habit_id", "started_at"]
    )
    # No máximo uma pausa em andamento por hábito
    op.create_index(
        op.f("uq_habit_pauses_open"),
        "habit_pauses",
        ["habit_id"],
        unique=True,
        sqlite_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "habit_members",
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(8), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("habit_id", "user_id", name=op.f("pk_habit_members")),
        fk("habit_id", "habits.id", "CASCADE", "fk_habit_members_habit_id_habits"),
        fk("user_id", "users.id", "CASCADE", "fk_habit_members_user_id_users"),
        check(f"role IN ({ROLES})", "ck_habit_members_role"),
    )
    op.create_index(op.f("ix_habit_members_user_id"), "habit_members", ["user_id"])

    op.create_table(
        "habit_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("invited_user_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_habit_invites")),
        sa.UniqueConstraint("habit_id", "email", name=op.f("uq_habit_invites_habit_id_email")),
        fk("habit_id", "habits.id", "CASCADE", "fk_habit_invites_habit_id_habits"),
        fk("invited_user_id", "users.id", "CASCADE", "fk_habit_invites_invited_user_id_users"),
        check("email = lower(trim(email))", "ck_habit_invites_email_normalized"),
        check("length(email) BETWEEN 3 AND 254", "ck_habit_invites_email_length"),
        check(f"role IN ({ROLES})", "ck_habit_invites_role"),
        **AUTOINCREMENT,
    )
    op.create_index(op.f("ix_habit_invites_invited_user_id"), "habit_invites", ["invited_user_id"])

    op.create_table(
        "marks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("marked_at", sa.DateTime(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("cost_cents", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marks")),
        fk("habit_id", "habits.id", "CASCADE", "fk_marks_habit_id_habits"),
        fk("user_id", "users.id", "SET NULL", "fk_marks_user_id_users"),
        check("duration_minutes > 0", "ck_marks_duration_minutes_positive"),
        check("cost_cents >= 0", "ck_marks_cost_cents_not_negative"),
        **AUTOINCREMENT,
    )
    op.create_index(op.f("ix_marks_habit_id_marked_at"), "marks", ["habit_id", "marked_at"])
    op.create_index(op.f("ix_marks_user_id"), "marks", ["user_id"])

    op.create_table(
        "alerts",
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("habit_id", "user_id", name=op.f("pk_alerts")),
        fk("habit_id", "habits.id", "CASCADE", "fk_alerts_habit_id_habits"),
        fk("user_id", "users.id", "CASCADE", "fk_alerts_user_id_users"),
        check("hour BETWEEN 0 AND 23", "ck_alerts_hour"),
        check("frequency IN ('daily', 'weekly')", "ck_alerts_frequency"),
        check("weekday BETWEEN 0 AND 6", "ck_alerts_weekday"),
        check("frequency = 'daily' OR weekday IS NOT NULL", "ck_alerts_weekly_weekday"),
    )
    op.create_index(op.f("ix_alerts_user_id"), "alerts", ["user_id"])

    op.create_table(
        "banners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("text_pt", sa.String(280), nullable=False),
        sa.Column("text_en", sa.String(280), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_banners")),
        fk("created_by", "users.id", "SET NULL", "fk_banners_created_by_users"),
        check("length(text_pt) BETWEEN 1 AND 280", "ck_banners_text_pt_length"),
        check("length(text_en) BETWEEN 1 AND 280", "ck_banners_text_en_length"),
        check("ends_at > starts_at", "ck_banners_ends_after_starts"),
        **AUTOINCREMENT,
    )


def downgrade() -> None:
    # Filhas antes das mães; os índices saem junto com a tabela
    for table in (
        "banners",
        "alerts",
        "marks",
        "habit_invites",
        "habit_members",
        "habit_pauses",
        "audit_log",
        "habits",
        "login_codes",
        "sessions",
        "users",
    ):
        op.drop_table(table)
