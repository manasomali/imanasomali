"""Coluna alerts.last_evaluated_at: quando o alerta foi avaliado pela última vez.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24

Escrita à mão, como as anteriores (sem importar app.models). O `run-alerts` (ETH-26) avalia cada
alerta uma vez por ocorrência (a hora escolhida, no dia certo), na primeira execução do timer a
partir dela. Só o `last_sent_at` não basta: uma avaliação que não mandou email não deixaria
rastro, e o alerta seria reavaliado de hora em hora até o fim do dia, mandando o email numa hora
que o usuário não escolheu. Salvar a configuração também grava a coluna (âncora: uma ocorrência
que já passou antes de salvar não é avaliada atrasada).

Coluna nova, anulável e sem default: `ADD COLUMN` simples, sem recriar a tabela. As linhas
antigas ficam com NULL ("nunca avaliado").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("last_evaluated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "last_evaluated_at")
