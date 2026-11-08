import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.exc import OperationalError

from app.db import create_db_engine
from app.models import Base

APP_TABLES = {"app_tasks", "audit_log", "login_codes", "mail_log", "sessions", "users"}


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "migrations.db"


def table_names(path: Path) -> set[str]:
    engine = create_db_engine(path)
    try:
        return set(inspect(engine).get_table_names()) - {"sqlite_sequence"}
    finally:
        engine.dispose()


def current_revision(path: Path) -> str | None:
    engine = create_db_engine(path)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def script_directory() -> ScriptDirectory:
    return ScriptDirectory(str(Path(__file__).resolve().parents[1] / "migrations"))


def head_revision() -> str | None:
    return script_directory().get_current_head()


def _normalize(sql: str | None) -> str:
    return re.sub(r"\s+", " ", sql or "").strip()


def schema_snapshot(path: Path) -> dict[str, Any]:
    """Tudo o que define o schema, em formato comparável e sem depender da ordem do DDL."""
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        inspector = inspect(engine)
        tables: dict[str, Any] = {}
        for table in sorted(set(inspector.get_table_names()) & APP_TABLES):
            tables[table] = {
                "columns": [
                    (
                        column["name"],
                        str(column["type"]),
                        column["nullable"],
                        _normalize(column["default"]),
                    )
                    for column in inspector.get_columns(table)
                ],
                "primary_key": inspector.get_pk_constraint(table)["constrained_columns"],
                "foreign_keys": sorted(
                    (
                        fk["name"],
                        tuple(fk["constrained_columns"]),
                        fk["referred_table"],
                        tuple(fk["referred_columns"]),
                        fk["options"].get("ondelete"),
                    )
                    for fk in inspector.get_foreign_keys(table)
                ),
                "unique": sorted(
                    (uq["name"], tuple(uq["column_names"]))
                    for uq in inspector.get_unique_constraints(table)
                ),
                "checks": sorted(
                    (ck["name"], _normalize(ck["sqltext"]))
                    for ck in inspector.get_check_constraints(table)
                ),
            }
        with engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' AND tbl_name != 'alembic_version'"
            ).all()
        # O CREATE INDEX (com o UNIQUE e o WHERE do índice parcial) sai igual nos dois caminhos
        indexes = sorted(
            (name, _normalize(sql)) for kind, name, _table, sql in rows if kind == "index"
        )
        autoincrement = sorted(
            name for kind, name, _table, sql in rows if kind == "table" and "AUTOINCREMENT" in sql
        )
        return {"tables": tables, "indexes": indexes, "autoincrement": autoincrement}
    finally:
        engine.dispose()


def test_upgrade_head_on_empty_database(db_path, make_alembic_config):
    command.upgrade(make_alembic_config(db_path), "head")

    assert table_names(db_path) == APP_TABLES | {"alembic_version"}
    assert current_revision(db_path) == head_revision()


def test_downgrade_base_and_upgrade_again(db_path, make_alembic_config):
    config = make_alembic_config(db_path)
    command.upgrade(config, "head")
    first = schema_snapshot(db_path)

    command.downgrade(config, "base")
    assert table_names(db_path) == {"alembic_version"}
    assert current_revision(db_path) is None

    command.upgrade(config, "head")
    assert schema_snapshot(db_path) == first
    assert current_revision(db_path) == head_revision()


def test_models_match_migrations_for_alembic(migrated_template):
    """Drift: o autogenerate não acha nada a fazer entre os modelos e o banco migrado."""
    engine = create_db_engine(migrated_template)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_models_match_migrations_in_full(migrated_template, tmp_path):
    """Drift completo: o compare_metadata não olha CHECK, ON DELETE, índice parcial nem
    AUTOINCREMENT. Aqui o banco migrado e o criado pelos modelos têm que ser iguais em tudo."""
    from_models = tmp_path / "models.db"
    engine = create_engine(f"sqlite:///{from_models.as_posix()}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    migrated = schema_snapshot(migrated_template)
    assert migrated == schema_snapshot(from_models)
    # O snapshot enxerga o que importa (senão a igualdade acima não provaria nada)
    tables = migrated["tables"]
    assert set(tables) == APP_TABLES
    assert ("ck_users_status", "status IN ('active', 'deleting')") in tables["users"]["checks"]
    assert ("ck_login_codes_purpose", "purpose IN ('login', 'delete_account')") in tables[
        "login_codes"
    ]["checks"]
    assert ("ck_mail_log_kind", "kind IN ('code', 'account', 'notification')") in tables[
        "mail_log"
    ]["checks"]
    assert ("ck_app_tasks_action", "action IN ('delete', 'refresh')") in tables["app_tasks"][
        "checks"
    ]
    assert ("uq_users_email", ("email",)) in tables["users"]["unique"]
    for table in ("sessions", "login_codes", "app_tasks"):
        [fk] = tables[table]["foreign_keys"]
        assert fk[2:] == ("users", ("id",), "CASCADE")
    [audit_fk] = tables["audit_log"]["foreign_keys"]
    assert audit_fk[2:] == ("users", ("id",), "SET NULL")
    assert any(
        name == "uq_app_tasks_pending"
        and sql.startswith("CREATE UNIQUE INDEX")
        and sql.endswith("WHERE done_at IS NULL")
        for name, sql in migrated["indexes"]
    )
    # users sem AUTOINCREMENT (id sorteado); as outras com
    assert migrated["autoincrement"] == ["app_tasks", "audit_log", "login_codes", "mail_log"]
    users_id = tables["users"]["columns"][0]
    assert users_id[:3] == ("id", "BIGINT", False)


def test_single_head():
    # Duas migrações com o mesmo pai (ex.: PRs em paralelo) deixariam o upgrade ambíguo
    assert len(script_directory().get_heads()) == 1


def test_upgrade_is_all_or_nothing(db_path, make_alembic_config):
    # A última tabela da migração já existe: o CREATE TABLE dela falha depois das outras
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("CREATE TABLE app_tasks (id INTEGER PRIMARY KEY)")

    with pytest.raises(OperationalError, match="already exists"):
        command.upgrade(make_alembic_config(db_path), "head")

    assert table_names(db_path) == {"app_tasks"}


def test_upgrade_uses_one_immediate_transaction(db_path, make_alembic_config):
    statements: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    # Escuta toda Engine: o env.py cria a dele
    event.listen(Engine, "before_cursor_execute", record)
    try:
        command.upgrade(make_alembic_config(db_path), "head")
    finally:
        event.remove(Engine, "before_cursor_execute", record)

    begins = [s for s in statements if s.startswith("BEGIN")]
    assert begins == ["BEGIN IMMEDIATE"]
    assert "PRAGMA foreign_key_check" in statements


def test_offline_mode_is_refused(db_path, make_alembic_config):
    with pytest.raises(RuntimeError, match="offline"):
        command.upgrade(make_alembic_config(db_path), "head", sql=True)


def test_database_path_comes_from_environment(db_path, make_alembic_config, monkeypatch):
    config = make_alembic_config(db_path)
    del config.attributes["database_path"]
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    command.upgrade(config, "head")

    assert current_revision(db_path) == head_revision()


@pytest.mark.parametrize("value", ["", "   ", ":memory:"])
def test_missing_or_memory_database_path_is_refused(
    db_path, make_alembic_config, monkeypatch, value
):
    config = make_alembic_config(db_path)
    del config.attributes["database_path"]
    monkeypatch.setenv("DATABASE_PATH", value)

    with pytest.raises(RuntimeError, match="DATABASE_PATH"):
        command.upgrade(config, "head")
