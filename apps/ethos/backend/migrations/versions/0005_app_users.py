"""Login pelo imago (ETH-64): `users` vira `app_users`, com os mesmos ids.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-08

Escrita à mão, como as anteriores (sem importar app.models). As contas foram copiadas para o imago
com os mesmos ids (`export-users` daqui, `import-users` de lá) antes deste deploy, então hábitos,
marcações, membros, convites e alertas continuam ligados às mesmas pessoas. Passos, numa transação
só (o `env.py` desliga as chaves estrangeiras durante a migração e as confere no fim):

1. `ALTER TABLE users RENAME TO app_users` e `RENAME COLUMN id TO user_id`: o SQLite (3.26+)
   reescreve as chaves estrangeiras das outras tabelas junto (`REFERENCES "app_users" (user_id)`).
   Os nomes das constraints (`fk_<tabela>_<coluna>_users`) ficam: renomear uma constraint exige
   recriar a tabela (app/models.py, `user_fk`).
2. `habit_invites` perde a chave estrangeira de `invited_user_id`: o convidado é um usuário do
   imago que pode nunca ter aberto o ethos. A tabela é recriada no modo batch, guardando o
   AUTOINCREMENT e o contador do `sqlite_sequence`, como na 0004.
3. `app_users` é recriada com as colunas do ethos-plan (`user_id`, `email`, `locale`, `timezone`,
   `first_seen_at` = o `created_at` de antes, `updated_at`): sem AUTOINCREMENT (o id vem do
   imago) e sem o `UNIQUE` do email (a cópia de uma conta pode estar velha quando outra conta
   passa a usar o email que ela tinha). Saem `is_active`, `is_admin`, `terms_version`,
   `terms_accepted_at` e `last_login_at`, que agora são do imago. A tabela nova é criada à parte,
   recebe as linhas e troca de nome com a antiga (o procedimento de ALTER TABLE do SQLite): as
   chaves das outras tabelas continuam apontando para `app_users`.
4. `audit_log`: saem os eventos de login e de conta (`REMOVED_EVENTS`, agora do imago) e todos os
   IPs (a coluna `ip` fica, vazia, até o deploy seguinte).
5. `sessions` e `login_codes` ficam vazias (sessões com IP e navegador, hashes de códigos). As
   tabelas saem na migração do deploy seguinte, como a coluna `audit_log.ip`.

É a exceção à regra das migrações só aditivas: o código de antes não roda com o banco novo, e os
dados que saem (admin, bloqueio, termos, sessões, eventos de login) não voltam. Voltar deste deploy
exige restaurar o `pre-deploy-<sha>.db` (apps/ethos/README.md, "Migrações").

Downgrade: só num banco sem contas em `app_users`, onde ele refaz o schema da 0004 (é o que o teste
de ida e volta das migrações usa). Com contas, é RECUSADO e nada muda: recriar `users` sem saber
quem era admin, quem estava bloqueado e que termos cada um aceitou deixaria o código de antes sem
admin e com dados inventados.
"""

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from alembic.operations import BatchOperations

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Eventos de login e de conta do login próprio: no imago a partir de agora
REMOVED_EVENTS = (
    "code_requested",
    "login",
    "login_failed",
    "logout",
    "logout_all",
    "delete_code_requested",
    "send_cap_reached",
    "terms_accepted",
    "profile_updated",
    "account_deleted",
    "admin_created",
    "user_blocked",
    "user_unblocked",
    "email_changed",
)
INVITED_USER_FK = "fk_habit_invites_invited_user_id_users"
NEW_TABLE = "_app_users_new"


def check(sqltext: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sqltext, name=op.f(name))


def _recreate_habit_invites(change: Callable[[BatchOperations], None]) -> None:
    """Recria `habit_invites` com `change`, guardando o AUTOINCREMENT e o contador (ver a 0004)."""
    connection = op.get_bind()
    sequence = connection.execute(
        sa.text("SELECT seq FROM sqlite_sequence WHERE name = 'habit_invites'")
    ).scalar_one_or_none()
    with op.batch_alter_table(
        "habit_invites", recreate="always", table_kwargs={"sqlite_autoincrement": True}
    ) as batch:
        change(batch)
    if sequence is None:
        return
    connection.execute(sa.text("DELETE FROM sqlite_sequence WHERE name = 'habit_invites'"))
    connection.execute(
        sa.text(
            "INSERT INTO sqlite_sequence (name, seq) "
            "SELECT 'habit_invites', max(:seq, coalesce((SELECT max(id) FROM habit_invites), 0))"
        ),
        {"seq": sequence},
    )


def upgrade() -> None:
    # 1. As chaves das outras tabelas acompanham os dois renames
    op.execute("ALTER TABLE users RENAME TO app_users")
    op.execute("ALTER TABLE app_users RENAME COLUMN id TO user_id")

    # 2. O convidado não precisa ter linha em app_users
    _recreate_habit_invites(
        lambda batch: batch.drop_constraint(op.f(INVITED_USER_FK), type_="foreignkey")
    )

    # 3. app_users no formato do ethos-plan
    op.create_table(
        NEW_TABLE,
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("locale", sa.String(2), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_app_users")),
        check("email = lower(trim(email))", "ck_app_users_email_normalized"),
        check("length(email) BETWEEN 3 AND 254", "ck_app_users_email_length"),
        check("length(timezone) BETWEEN 1 AND 64", "ck_app_users_timezone_length"),
        check("locale IN ('pt', 'en')", "ck_app_users_locale"),
    )
    op.execute(
        "INSERT INTO _app_users_new (user_id, email, locale, timezone, first_seen_at, updated_at) "
        "SELECT user_id, email, locale, timezone, created_at, updated_at FROM app_users"
    )
    op.drop_table("app_users")
    op.rename_table(NEW_TABLE, "app_users")
    # O contador do AUTOINCREMENT de users (renomeado junto) não serve mais
    op.execute("DELETE FROM sqlite_sequence WHERE name IN ('users', 'app_users')")

    # 4. Auditoria: sem login, sem conta e sem IP
    events = ", ".join(f"'{event}'" for event in REMOVED_EVENTS)
    op.execute(f"DELETE FROM audit_log WHERE event IN ({events})")  # noqa: S608 (constantes)
    op.execute("UPDATE audit_log SET ip = NULL WHERE ip IS NOT NULL")

    # 5. Sessões e códigos do login próprio
    op.execute("DELETE FROM sessions")
    op.execute("DELETE FROM login_codes")


def downgrade() -> None:
    accounts = op.get_bind().execute(sa.text("SELECT count(*) FROM app_users")).scalar_one()
    if accounts:
        raise RuntimeError(
            f"downgrade recusado: {accounts} conta(s) em app_users. Admin, bloqueio, termos e "
            "sessões já não estão neste banco (passaram para o imago); para voltar ao login "
            "próprio, restaure o pre-deploy-<sha>.db deste deploy (infra/RESTORE.md)"
        )

    # A chave de volta, apontando para app_users(user_id): os renames abaixo a convertem
    _recreate_habit_invites(
        lambda batch: batch.create_foreign_key(
            op.f(INVITED_USER_FK),
            "app_users",
            ["invited_user_id"],
            ["user_id"],
            ondelete="CASCADE",
        )
    )

    # users da 0001, criada com o nome e a chave de agora para as chaves das outras tabelas
    # continuarem valendo; os renames as levam de volta para users(id)
    op.drop_table("app_users")
    op.create_table(
        "app_users",
        sa.Column("user_id", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        check("email = lower(trim(email))", "ck_users_email_normalized"),
        check("length(email) BETWEEN 3 AND 254", "ck_users_email_length"),
        check("length(timezone) BETWEEN 1 AND 64", "ck_users_timezone_length"),
        check("locale IN ('pt', 'en')", "ck_users_locale"),
        check("length(terms_version) BETWEEN 1 AND 32", "ck_users_terms_version_length"),
        sqlite_autoincrement=True,
    )
    op.execute("ALTER TABLE app_users RENAME COLUMN user_id TO id")
    op.execute("ALTER TABLE app_users RENAME TO users")
