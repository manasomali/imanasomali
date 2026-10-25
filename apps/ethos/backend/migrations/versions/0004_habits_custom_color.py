"""CHECK de habits.color: além da paleta, aceita uma cor própria `#rrggbb` (ETH-49).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25

Escrita à mão, como as anteriores (sem importar app.models). Só relaxa o CHECK
`ck_habits_color`: toda linha que já existe (um nome da paleta) continua válida, e nenhum dado
muda. O SQLite não altera um CHECK no lugar, então o modo batch recria a tabela `habits` (copia
as linhas para uma tabela nova, apaga a antiga e renomeia). O `env.py` desliga as chaves
estrangeiras durante a migração, então apagar a tabela antiga não dispara os ON DELETE CASCADE de
marcações, pausas, membros, convites, alertas e auditoria.

Recriar a tabela tem dois cuidados:

- O AUTOINCREMENT (`table_kwargs`): a reflexão do SQLAlchemy não o enxerga.
- O contador do AUTOINCREMENT (`sqlite_sequence`): a tabela nova recomeça do maior id que
  sobrou, e os ids de hábitos apagados por último voltariam a ser usados (a auditoria guarda ids
  numéricos; ver app/models.py). O valor de antes é guardado e devolvido.

Downgrade: o CHECK antigo só aceita a paleta. Se algum hábito tem cor própria, o downgrade é
RECUSADO com um erro que diz quantos são e como trocá-los, e nada muda (a execução inteira é uma
transação). Trocar a cor sozinho por uma da paleta perderia a escolha do usuário sem ninguém
decidir isso; e o código de antes desta migração não sabe mostrar um hábito com cor própria, então
voltar o schema sem trocar as cores não serviria de qualquer jeito.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLORS = (
    "'red', 'orange', 'amber', 'yellow', 'lime', 'green', "
    "'teal', 'cyan', 'blue', 'indigo', 'violet', 'pink'"
)
PALETTE_CHECK = f"color IN ({COLORS})"
# "#" e 6 dígitos hexadecimais em minúsculas (app.models.CUSTOM_COLOR_GLOB)
CUSTOM_COLOR_CHECK = f"{PALETTE_CHECK} OR color GLOB '#{'[0-9a-f]' * 6}'"
CONSTRAINT = "ck_habits_color"
# O que o erro do downgrade recusado sugere rodar (troca toda cor própria pela cor padrão do front)
FIX_CUSTOM_COLORS = "UPDATE habits SET color = 'teal' WHERE color GLOB '#*';"


def _replace_color_check(condition: str) -> None:
    connection = op.get_bind()
    sequence = connection.execute(
        sa.text("SELECT seq FROM sqlite_sequence WHERE name = 'habits'")
    ).scalar_one_or_none()
    with op.batch_alter_table(
        "habits", recreate="always", table_kwargs={"sqlite_autoincrement": True}
    ) as batch:
        batch.drop_constraint(op.f(CONSTRAINT), type_="check")
        batch.create_check_constraint(op.f(CONSTRAINT), sa.text(condition))
    if sequence is None:
        return
    # A cópia das linhas deixa o contador no maior id que sobrou (ou sem linha, sem hábitos)
    connection.execute(sa.text("DELETE FROM sqlite_sequence WHERE name = 'habits'"))
    connection.execute(
        sa.text(
            "INSERT INTO sqlite_sequence (name, seq) "
            "SELECT 'habits', max(:seq, coalesce((SELECT max(id) FROM habits), 0))"
        ),
        {"seq": sequence},
    )


def upgrade() -> None:
    _replace_color_check(CUSTOM_COLOR_CHECK)


def downgrade() -> None:
    # Com o CHECK da 0004, o que não é da paleta começa com "#"
    custom = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM habits WHERE color GLOB '#*'"))
        .scalar_one()
    )
    if custom:
        raise RuntimeError(
            f"downgrade recusado: {custom} hábito(s) com cor própria (#rrggbb), que o CHECK "
            f"antigo não aceita. Troque a cor deles por uma da paleta antes: {FIX_CUSTOM_COLORS}"
        )
    _replace_color_check(PALETTE_CHECK)
