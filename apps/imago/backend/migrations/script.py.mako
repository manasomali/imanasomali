"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Escrita e revisada à mão: o autogenerate erra em SQLite. Não importe app.models aqui, porque a
migração tem que continuar igual quando os modelos mudarem. Alteração de tabela vai em
op.batch_alter_table (o SQLite recria a tabela); constraints e índices com o nome completo, em
op.f("..."), seguindo a NAMING_CONVENTION de app/models.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}
revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
