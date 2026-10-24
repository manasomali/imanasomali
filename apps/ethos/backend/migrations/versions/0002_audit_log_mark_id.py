"""Coluna audit_log.mark_id (calculada) e o índice do histórico de uma marcação.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24

Escrita à mão, como a 0001 (sem importar app.models). `GET /history?mark_id=` (ETH-25) procura os
eventos de uma marcação pelo `details.mark_id`. Sem índice, o SQLite teria de rodar o
`json_extract` em cada evento dos hábitos do usuário. A coluna é gerada e VIRTUAL: o SQLite a
calcula do `details` na leitura, então ela não ocupa espaço na linha, não precisa de backfill (as
linhas antigas já entram no índice) e acompanha qualquer mudança no `details`. O índice é parcial:
só as linhas com `mark_id` (os eventos de marcação) entram nele. O `json_valid` antes do
`json_extract` deixa o CHECK `ck_audit_log_details_json` recusar JSON inválido (IntegrityError),
em vez de o cálculo do índice falhar antes com "malformed JSON".

O SQLite aceita `ADD COLUMN` de coluna gerada VIRTUAL (STORED, não) e `DROP COLUMN` (3.35+),
então nada de recriar a tabela.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column(
            "mark_id",
            sa.Integer(),
            sa.Computed(
                "CASE WHEN json_valid(details) THEN json_extract(details, '$.mark_id') END",
                persisted=False,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_audit_log_mark_id"),
        "audit_log",
        ["mark_id"],
        sqlite_where=sa.text("mark_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_log_mark_id"), table_name="audit_log")
    op.drop_column("audit_log", "mark_id")
