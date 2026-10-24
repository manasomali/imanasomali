import threading

import pytest
from sqlalchemy import Engine, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.db import (
    check_foreign_keys,
    create_db_engine,
    create_session_factory,
    migration_connection,
    write_transaction,
)

WRITERS = 4
WRITES_PER_THREAD = 25


class Base(DeclarativeBase):
    pass


class Item(Base):
    """Tabela só destes testes, fora dos modelos do app (app/models.py)."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


@pytest.fixture
def tables(engine) -> Engine:
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE counter (id INTEGER PRIMARY KEY, value INTEGER)")
        connection.exec_driver_sql("INSERT INTO counter VALUES (1, 0)")
    return engine


@pytest.fixture
def statements(engine) -> list[str]:
    """SQL emitido pela engine, na ordem."""
    seen: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    return seen


def pragmas(connection) -> dict[str, int]:
    return {
        name: connection.exec_driver_sql(f"PRAGMA {name}").scalar_one()
        for name in ("busy_timeout", "synchronous", "foreign_keys", "secure_delete")
    }


EXPECTED_PRAGMAS = {"busy_timeout": 5000, "synchronous": 1, "foreign_keys": 1, "secure_delete": 1}


def test_pragmas_on_every_new_connection(engine):
    # Duas conexões abertas ao mesmo tempo são duas conexões do driver, cada uma com o seu connect
    with engine.connect() as first, engine.connect() as second:
        assert first.connection.dbapi_connection is not second.connection.dbapi_connection
        assert pragmas(first) == EXPECTED_PRAGMAS
        assert pragmas(second) == EXPECTED_PRAGMAS
        assert first.connection.dbapi_connection.isolation_level is None

    engine.dispose()
    with engine.connect() as fresh:
        assert pragmas(fresh) == EXPECTED_PRAGMAS


def test_database_path_is_not_parsed_as_url(tmp_path):
    path = tmp_path / "app.db?mode=ro&uri=true"
    engine = create_db_engine(path)

    # O "?" seria parte do nome do arquivo, não parâmetro do driver
    assert engine.url.database == str(path)
    assert not engine.url.query


def test_read_uses_deferred_begin(db_session, statements):
    db_session.execute(text("SELECT 1"))

    assert statements[0] == "BEGIN DEFERRED"


def test_write_transaction_uses_begin_immediate_and_commits(tables, db_session, statements):
    with write_transaction(db_session):
        db_session.add(Item(name="a"))

    assert statements[0] == "BEGIN IMMEDIATE"
    assert not db_session.in_transaction()
    with tables.connect() as connection:
        assert connection.exec_driver_sql("SELECT name FROM items").scalars().all() == ["a"]


def test_write_transaction_rolls_back_on_error(tables, db_session):
    def write_and_fail():
        with write_transaction(db_session):
            db_session.add(Item(name="a"))
            db_session.flush()
            raise LookupError

    with pytest.raises(LookupError):
        write_and_fail()

    assert db_session.scalars(select(Item)).all() == []


def test_write_transaction_after_read_reopens_as_immediate(tables, db_session, statements):
    db_session.execute(text("SELECT 1"))

    with write_transaction(db_session):
        db_session.add(Item(name="a"))

    assert [s for s in statements if s.startswith("BEGIN")] == ["BEGIN DEFERRED", "BEGIN IMMEDIATE"]
    assert db_session.scalars(select(Item.name)).all() == ["a"]


def test_orm_write_outside_write_transaction_is_refused(tables, db_session):
    db_session.add(Item(name="a"))

    with pytest.raises(RuntimeError, match="fora de write_transaction"):
        db_session.flush()


def test_pending_changes_before_write_transaction_are_refused(tables, db_session):
    db_session.execute(text("SELECT 1"))
    db_session.add(Item(name="a"))

    with pytest.raises(RuntimeError, match="alterações pendentes"), write_transaction(db_session):
        pass  # pragma: no cover


def test_nested_write_transaction_is_refused(tables, db_session):
    with write_transaction(db_session):
        db_session.add(Item(name="a"))
        with pytest.raises(RuntimeError, match="aninhada"), write_transaction(db_session):
            pass  # pragma: no cover

    # A transação de fora continua valendo
    assert db_session.scalars(select(Item.name)).all() == ["a"]


def test_unknown_begin_mode_is_refused(engine):
    with (
        engine.connect().execution_options(ethos_begin="EXCLUSIVE; DROP") as connection,
        pytest.raises(ValueError, match="modo de BEGIN desconhecido"),
    ):
        connection.exec_driver_sql("SELECT 1")


def run_writers(target) -> list[Exception]:
    errors: list[Exception] = []

    def guarded():
        try:
            target()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=guarded) for _ in range(WRITERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def increment(session: Session) -> None:
    value = session.execute(text("SELECT value FROM counter WHERE id = 1")).scalar_one()
    session.execute(text("UPDATE counter SET value = :value WHERE id = 1"), {"value": value + 1})


def test_concurrent_write_transactions_do_not_lock(tables):
    factory = create_session_factory(tables)
    start = threading.Barrier(WRITERS)

    def write():
        start.wait()
        for _ in range(WRITES_PER_THREAD):
            with factory() as session, write_transaction(session):
                increment(session)

    assert run_writers(write) == []
    with tables.connect() as connection:
        total = connection.exec_driver_sql("SELECT value FROM counter").scalar_one()
    # Nenhum incremento perdido: a leitura e a escrita ficam na mesma trava
    assert total == WRITERS * WRITES_PER_THREAD


def test_deferred_read_then_write_gets_locked(tables):
    """Controle do teste acima: sem BEGIN IMMEDIATE, o mesmo padrão dá "database is locked"."""
    factory = create_session_factory(tables)
    both_read = threading.Barrier(WRITERS)

    def write():
        with factory() as session:
            value = session.execute(text("SELECT value FROM counter")).scalar_one()
            both_read.wait()
            session.execute(text("UPDATE counter SET value = :v"), {"v": value + 1})
            session.commit()

    errors = run_writers(write)

    assert errors
    assert all(isinstance(error, OperationalError) for error in errors)
    assert all("database is locked" in str(error) for error in errors)


def test_migration_connection_turns_foreign_keys_off_and_begins_immediate(engine, statements):
    with migration_connection(engine) as connection, connection.begin():
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 0
        driver_connection = connection.connection.dbapi_connection

    assert [s for s in statements if s.startswith("BEGIN")] == ["BEGIN IMMEDIATE"]
    # A conexão sem chaves estrangeiras não volta ao pool
    with engine.connect() as fresh:
        assert fresh.connection.dbapi_connection is not driver_connection
        assert fresh.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_migration_connection_is_discarded_after_an_error(engine):
    seen = []

    def fail() -> None:
        with migration_connection(engine) as connection:
            seen.append(connection.connection.dbapi_connection)
            raise LookupError

    with pytest.raises(LookupError):
        fail()

    [driver_connection] = seen
    with engine.connect() as fresh:
        assert fresh.connection.dbapi_connection is not driver_connection
        assert fresh.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_check_foreign_keys_reports_tables_without_values(engine):
    orphan = text(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at) "
        "VALUES (:hash, 4242, '2026-01-01', '2026-01-01', '2026-01-01')"
    )
    with migration_connection(engine) as connection, connection.begin() as transaction:
        check_foreign_keys(connection)
        # Com as chaves desligadas, a linha órfã entra; a conferência no fim acha
        connection.execute(orphan, {"hash": "a" * 64})

        with pytest.raises(RuntimeError, match=r"nas tabelas: sessions$") as error:
            check_foreign_keys(connection)
        assert "4242" not in str(error.value)
        transaction.rollback()
