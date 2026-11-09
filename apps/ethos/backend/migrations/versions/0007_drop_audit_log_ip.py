"""Sai a coluna `audit_log.ip`, o último legado do login próprio de antes do imago.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09

Escrita à mão, como as anteriores (sem importar app.models). A coluna está vazia desde a 0005
(que apagou os IPs), e o código da 0006 a deixou fora do mapeamento (`Unmapped`): nenhum INSERT ou
SELECT dele a cita, então o rollback deste deploy volta para ele sem a coluna. Por isso a 0007 só
pode ir para produção num deploy depois do da 0006: o código de antes da 0006 manda `ip` em todo
INSERT no `audit_log`.

O `DROP COLUMN` do SQLite recusa uma coluna citada num CHECK de tabela (`ck_audit_log_ip_length`),
então a tabela é recriada, como o `app_users` na 0005: a nova recebe as linhas, a antiga sai (com os
índices) e a nova troca de nome. Nenhuma tabela aponta para o `audit_log`, então nenhuma chave
estrangeira muda. O que precisa de cuidado:

- `mark_id` é uma coluna gerada (VIRTUAL, 0002): fica fora do INSERT, e o SQLite a calcula de novo
  do `details`;
- o índice parcial de `mark_id` e os outros três são recriados com os mesmos nomes;
- o contador do AUTOINCREMENT continua de onde estava (um id apagado no fim não volta), como na
  0004.

Downgrade: recria a tabela com a coluna `ip` (vazia) e o CHECK dela, no mesmo lugar de antes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLE = "_audit_log_new"
# As colunas copiadas: sem `ip` (que sai ou volta vazia) e sem `mark_id` (calculada pelo SQLite)
COPY_ROWS = (
    "INSERT INTO _audit_log_new (id, user_id, habit_id, event, created_at, details) "
    "SELECT id, user_id, habit_id, event, created_at, details FROM audit_log"
)
# Igual na 0002 e em app/models.py (AUDIT_MARK_ID)
MARK_ID = "CASE WHEN json_valid(details) THEN json_extract(details, '$.mark_id') END"


def check(sqltext: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sqltext, name=op.f(name))


def _create_audit_log(name: str, *, with_ip: bool) -> None:
    """O `audit_log` da 0006 (`with_ip`) ou o da 0007, com o nome `name`."""
    ip = [sa.Column("ip", sa.String(45), nullable=True)] if with_ip else []
    ip_check = [check("length(ip) BETWEEN 1 AND 45", "ck_audit_log_ip_length")] if with_ip else []
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("habit_id", sa.Integer(), nullable=True),
        sa.Column("event", sa.String(64), nullable=False),
        *ip,
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("mark_id", sa.Integer(), sa.Computed(MARK_ID, persisted=False), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        # O nome da chave de user_id é o de antes do rename de users (0005)
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.user_id"],
            ondelete="SET NULL",
            name=op.f("fk_audit_log_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["habit_id"],
            ["habits.id"],
            ondelete="CASCADE",
            name=op.f("fk_audit_log_habit_id_habits"),
        ),
        check("length(event) BETWEEN 1 AND 64", "ck_audit_log_event_length"),
        *ip_check,
        check("json_valid(details)", "ck_audit_log_details_json"),
        sqlite_autoincrement=True,
    )


def _recreate_audit_log(*, with_ip: bool) -> None:
    connection = op.get_bind()
    sequence = connection.execute(
        sa.text("SELECT seq FROM sqlite_sequence WHERE name = 'audit_log'")
    ).scalar_one_or_none()

    _create_audit_log(NEW_TABLE, with_ip=with_ip)
    op.execute(COPY_ROWS)
    op.drop_table("audit_log")
    op.rename_table(NEW_TABLE, "audit_log")

    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])
    op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"])
    op.create_index(
        op.f("ix_audit_log_habit_id_created_at"), "audit_log", ["habit_id", "created_at"]
    )
    op.create_index(
        op.f("ix_audit_log_mark_id"),
        "audit_log",
        ["mark_id"],
        sqlite_where=sa.text("mark_id IS NOT NULL"),
    )

    # O INSERT com os ids deixou o contador no maior id copiado (e o rename o levou para
    # audit_log); um id apagado no fim, acima dele, não pode voltar
    connection.execute(
        sa.text("DELETE FROM sqlite_sequence WHERE name IN ('audit_log', :new)"), {"new": NEW_TABLE}
    )
    if sequence is None:
        return
    connection.execute(
        sa.text(
            "INSERT INTO sqlite_sequence (name, seq) "
            "SELECT 'audit_log', max(:seq, coalesce((SELECT max(id) FROM audit_log), 0))"
        ),
        {"seq": sequence},
    )


def upgrade() -> None:
    _recreate_audit_log(with_ip=False)


def downgrade() -> None:
    _recreate_audit_log(with_ip=True)
