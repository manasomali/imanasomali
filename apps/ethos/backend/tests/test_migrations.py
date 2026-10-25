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

APP_TABLES = {
    "alerts",
    "audit_log",
    "banners",
    "habit_invites",
    "habit_members",
    "habit_pauses",
    "habits",
    "login_codes",
    "marks",
    "sessions",
    "users",
}


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


def _computed(computed: dict[str, Any] | None) -> tuple[str, bool | None] | None:
    # Coluna gerada (ex.: audit_log.mark_id): a expressão e se é STORED
    if computed is None:
        return None
    return _normalize(computed["sqltext"]), computed.get("persisted")


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
                        _computed(column.get("computed")),
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
        # O CREATE INDEX (com o WHERE do índice parcial) sai igual nos dois caminhos
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
    assert set(migrated["tables"]) == APP_TABLES
    assert ("ck_habits_goal_type", "goal_type IN ('min', 'max', 'exact')") in migrated["tables"][
        "habits"
    ]["checks"]
    assert ("fk_marks_user_id_users", ("user_id",), "users", ("id",), "SET NULL") in migrated[
        "tables"
    ]["marks"]["foreign_keys"]
    assert any("WHERE ended_at IS NULL" in sql for _name, sql in migrated["indexes"])
    assert "users" in migrated["autoincrement"]
    audit_columns = {column[0]: column for column in migrated["tables"]["audit_log"]["columns"]}
    assert audit_columns["mark_id"][4] == (
        "CASE WHEN json_valid(details) THEN json_extract(details, '$.mark_id') END",
        False,
    )


def test_0002_mark_id_covers_existing_rows(db_path, make_alembic_config):
    # A coluna é calculada: as linhas de antes da migração entram no índice sem backfill
    config = make_alembic_config(db_path)
    command.upgrade(config, "0001")
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.executemany(
            "INSERT INTO audit_log (event, created_at, details) VALUES (?, ?, ?)",
            [
                ("mark_created", "2026-01-15 12:00:00.000000", '{"mark_id": 7}'),
                ("login", "2026-01-15 12:00:00.000000", "{}"),
            ],
        )

    command.upgrade(config, "head")
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute("SELECT event, mark_id FROM audit_log ORDER BY id").fetchall()
        indexed = connection.execute(
            "SELECT event FROM audit_log INDEXED BY ix_audit_log_mark_id WHERE mark_id = 7"
        ).fetchall()
    assert rows == [("mark_created", 7), ("login", None)]
    assert indexed == [("mark_created",)]

    command.downgrade(config, "0001")
    with closing(sqlite3.connect(db_path)) as connection:
        # table_xinfo: o table_info não lista colunas geradas
        columns = [row[1] for row in connection.execute("PRAGMA table_xinfo(audit_log)")]
        remaining = connection.execute("SELECT count(*) FROM audit_log").fetchone()
    assert "mark_id" not in columns
    assert remaining == (2,)


def test_single_head():
    # Duas migrações com o mesmo pai (ex.: PRs em paralelo) deixariam o upgrade ambíguo
    assert len(script_directory().get_heads()) == 1


def test_upgrade_is_all_or_nothing(db_path, make_alembic_config):
    # A última tabela da migração já existe: o CREATE TABLE dela falha depois das outras
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("CREATE TABLE banners (id INTEGER PRIMARY KEY)")

    with pytest.raises(OperationalError, match="already exists"):
        command.upgrade(make_alembic_config(db_path), "head")

    assert table_names(db_path) == {"banners"}


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


# --- 0004: cor própria do hábito ----------------------------------------------------------------

STAMP = "2026-01-15 12:00:00.000000"


def insert_user(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO users (id, email, timezone, locale, terms_version, terms_accepted_at, "
        "created_at, updated_at) VALUES (1, 'ana@example.com', 'UTC', 'pt', 'v', ?, ?, ?)",
        (STAMP, STAMP, STAMP),
    )


def insert_habit(connection: sqlite3.Connection, color: str, habit_id: int | None = None) -> int:
    cursor = connection.execute(
        "INSERT INTO habits (id, owner_id, name, color, goal_type, goal_count, goal_period, "
        "created_at, updated_at) VALUES (?, 1, 'x', ?, 'min', 1, 'week', ?, ?)",
        (habit_id, color, STAMP, STAMP),
    )
    return cursor.lastrowid


def palette_database(db_path: Path, make_alembic_config) -> Any:
    """Banco na 0003 com uma conta, três hábitos (o último apagado), uma marcação e um evento."""
    config = make_alembic_config(db_path)
    command.upgrade(config, "0003")
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        insert_user(connection)
        first = insert_habit(connection, "teal")
        insert_habit(connection, "pink")
        last = insert_habit(connection, "red")
        connection.execute(
            "INSERT INTO marks (habit_id, user_id, marked_at, created_at, updated_at) "
            "VALUES (?, 1, ?, ?, ?)",
            (first, STAMP, STAMP, STAMP),
        )
        connection.execute(
            "INSERT INTO audit_log (user_id, habit_id, event, created_at) "
            "VALUES (1, ?, 'habit_created', ?)",
            (first, STAMP),
        )
        connection.execute("DELETE FROM habits WHERE id = ?", (last,))
    return config


def test_0004_keeps_rows_and_accepts_custom_color(db_path, make_alembic_config):
    config = palette_database(db_path, make_alembic_config)

    command.upgrade(config, "0004")

    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        # Recriar a tabela não dispara o CASCADE: marcações e auditoria continuam
        assert connection.execute("SELECT id, color FROM habits ORDER BY id").fetchall() == [
            (1, "teal"),
            (2, "pink"),
        ]
        assert connection.execute("SELECT count(*) FROM marks").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM audit_log").fetchone() == (1,)
        # O id 3 (apagado) não volta: o contador do AUTOINCREMENT sobreviveu à recriação
        assert insert_habit(connection, "#0a1b2c") == 4
        for color in ["#ABCDEF", "#fff", "#gggggg", "#0a1b2c0", " #0a1b2c", "magenta"]:
            with pytest.raises(sqlite3.IntegrityError, match="ck_habits_color"):
                insert_habit(connection, color)


def test_0004_keeps_the_counter_of_an_emptied_table(db_path, make_alembic_config):
    config = make_alembic_config(db_path)
    command.upgrade(config, "0003")
    with closing(sqlite3.connect(db_path)) as connection, connection:
        insert_user(connection)
        insert_habit(connection, "teal", habit_id=7)
        connection.execute("DELETE FROM habits")

    command.upgrade(config, "0004")

    with closing(sqlite3.connect(db_path)) as connection, connection:
        assert insert_habit(connection, "teal") == 8


def test_0004_on_a_database_without_habits(db_path, make_alembic_config):
    config = make_alembic_config(db_path)

    command.upgrade(config, "0004")
    command.downgrade(config, "0003")

    with closing(sqlite3.connect(db_path)) as connection, connection:
        insert_user(connection)
        assert insert_habit(connection, "teal") == 1


def test_0004_downgrade_is_refused_with_custom_colors(db_path, make_alembic_config):
    config = palette_database(db_path, make_alembic_config)
    command.upgrade(config, "0004")
    with closing(sqlite3.connect(db_path)) as connection, connection:
        insert_habit(connection, "#0a1b2c")

    with pytest.raises(RuntimeError, match=r"1 hábito\(s\) com cor própria"):
        command.downgrade(config, "0003")

    # Nada mudou: a execução inteira é uma transação
    assert current_revision(db_path) == "0004"
    with closing(sqlite3.connect(db_path)) as connection:
        colors = connection.execute("SELECT color FROM habits ORDER BY id").fetchall()
    assert colors == [("teal",), ("pink",), ("#0a1b2c",)]


def test_0004_downgrade_restores_the_palette_check(db_path, make_alembic_config):
    config = palette_database(db_path, make_alembic_config)
    command.upgrade(config, "0004")
    with closing(sqlite3.connect(db_path)) as connection, connection:
        insert_habit(connection, "#0a1b2c")
        # O que a mensagem do downgrade recusado manda fazer
        connection.execute("UPDATE habits SET color = 'teal' WHERE color GLOB '#*'")

    command.downgrade(config, "0003")

    assert current_revision(db_path) == "0003"
    with closing(sqlite3.connect(db_path)) as connection, connection:
        assert connection.execute("SELECT count(*) FROM marks").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError, match="ck_habits_color"):
            insert_habit(connection, "#0a1b2c")
        # O contador continua depois do maior id já usado (o 4, da cor própria)
        assert insert_habit(connection, "teal") == 5
