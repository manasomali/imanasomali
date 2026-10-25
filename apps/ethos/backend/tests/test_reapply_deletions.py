"""Reaplicar exclusões depois de um restore (ETH-42): `app/auth/reapply.py`,
`deletion.reapply_deletion` e `python -m app.cli reapply-deletions`."""

import io
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app import logs
from app.audit import AuditEvent
from app.auth import deletion
from app.auth.deletion import Reapplied, delete_account, reapply_deletion
from app.auth.reapply import (
    MAX_ACCOUNT_ID,
    AccountIds,
    InputError,
    protect_account_ids,
    read_account_ids,
    reapply_deletions,
)
from app.cli import main
from app.config import ENV_VARS
from app.mail.sender import Mailer
from app.models import AuditLog, Habit, Mark, User
from tests.conftest import BACKEND_DIR
from tests.factories import count, new_habit, new_mark, new_member, new_user, save
from tests.test_cli import env_for

# Linhas de verdade do `journalctl -u app-ethos -o cat`, em volta das de exclusão
SYSTEMD_START = "Started app-ethos.service - ethos: API em /api/ethos/."
ALEMBIC = "INFO  [alembic.runtime.migration] Context impl SQLiteImpl."
UVICORN = "INFO:     Started server process [4242]"
REQUEST = "INFO app.request: DELETE /admin/users/{user_id} 204 12.3ms"
EMAIL = "INFO app.mail.sender: email account_deleted enviado"


MARKED_AT = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def deleted_line(account_id: int) -> str:
    return f"INFO app.auth.deletion: conta {account_id} excluída"


@pytest.fixture(autouse=True)
def no_email(monkeypatch):
    """Reaplicar nunca manda email: qualquer envio falha o teste."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("reapply-deletions mandou email")

    monkeypatch.setattr(Mailer, "send", refuse)


@pytest.fixture
def env(settings, database) -> dict[str, str]:
    return env_for(settings)


@pytest.fixture
def stdin(monkeypatch) -> Callable[[str], None]:
    """Troca o stdin por um pipe (não terminal) com o texto em UTF-8."""

    def feed(content: str) -> None:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(content.encode())))

    return feed


def users(db_session) -> list[int]:
    db_session.rollback()
    return list(db_session.scalars(select(User.id).order_by(User.id)))


def deleted_events(db_session, account_id: int) -> list[tuple]:
    db_session.rollback()
    rows = db_session.execute(
        select(AuditLog.user_id, AuditLog.ip, AuditLog.details).where(
            AuditLog.event == AuditEvent.ACCOUNT_DELETED,
            AuditLog.details["account_id"].as_integer() == account_id,
        )
    ).all()
    return [tuple(row) for row in rows]


def users_sequence(path: Path) -> int | None:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("SELECT seq FROM sqlite_sequence WHERE name = 'users'").fetchone()
    return None if row is None else row[0]


# --- Leitura dos ids -------------------------------------------------------------------------


def test_reads_the_line_the_app_writes(caplog):
    # A linha montada pelo próprio app: o logger e a mensagem de deletion.py com o formato de
    # app/logs.py. Se um dos dois mudar, a leitura das linhas antigas precisa mudar junto
    with caplog.at_level(logging.INFO, logger=deletion.logger.name):
        deletion._log_deleted(7)
    [record] = caplog.records
    line = logs._handler.format(record)

    assert line == deleted_line(7)
    assert read_account_ids([line]) == AccountIds(ids=(7,), lines=1, repeated=0)


def test_reads_the_journal_mixed_with_other_lines_and_loose_ids():
    lines = [
        f"{SYSTEMD_START}\n",
        f"{ALEMBIC}\n",
        f"{UVICORN}\n",
        f"{REQUEST}\n",
        f"{deleted_line(7)}\n",
        f"{EMAIL}\n",
        "\n",
        f"{deleted_line(3)}\r\n",
        "42\n",
        "  43  \n",
        f"{deleted_line(7)}\n",
        "42",
    ]

    assert read_account_ids(lines) == AccountIds(ids=(7, 3, 42, 43), lines=12, repeated=2)


def test_empty_input():
    assert read_account_ids([]) == AccountIds(ids=(), lines=0, repeated=0)


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        # journalctl sem -o cat: data, host e processo na frente
        (
            f"out 25 12:00:00 vm uvicorn[4242]: {deleted_line(7)}",
            "fora do formato do journalctl -o cat",
        ),
        ("WARNING app.auth.deletion: conta 7 excluída", "fora do formato"),
        ("INFO app.auth.deletion: conta 0 excluída", "fora do formato"),
        ("INFO app.auth.deletion: conta 7 excluída de novo", "fora do formato"),
        ("INFO app.auth.deletion: conta 12345678901234567890 excluída", "fora do formato"),
        ("0", "id inválido"),
        ("007", "id inválido"),
        ("-3", "id inválido"),
        ("+3", "id inválido"),
        ("12345678901234567890", "id inválido"),
        (str(MAX_ACCOUNT_ID + 1), "id grande demais"),
    ],
)
def test_refuses_lines_that_look_like_a_deletion_or_an_id(line, reason):
    with pytest.raises(InputError, match=reason) as caught:
        read_account_ids([REQUEST, line])
    assert str(caught.value).startswith("linha 2: ")


def test_largest_valid_id():
    assert read_account_ids([str(MAX_ACCOUNT_ID)]).ids == (MAX_ACCOUNT_ID,)


# --- deletion.reapply_deletion ---------------------------------------------------------------


def test_reapply_deletes_without_email_log_or_actor(db_session, make_account, caplog):
    ana = make_account("ana@example.com")
    bia = make_account("bia@example.com")
    habit = new_habit(ana.user)
    save(db_session, habit)
    save(db_session, new_member(habit, bia.user))

    with caplog.at_level(logging.DEBUG):
        assert reapply_deletion(db_session, account_id=ana.user.id) is Reapplied.DELETED

    # A exclusão original já deixou a linha no journald
    assert caplog.records == []
    assert users(db_session) == [bia.user.id]
    assert count(db_session, Habit) == 0
    assert deleted_events(db_session, ana.user.id) == [
        (None, None, {"account_id": ana.user.id, "reapplied": True})
    ]


def test_reapply_missing_account_changes_nothing(db_session, make_account):
    ana = make_account("ana@example.com")

    assert reapply_deletion(db_session, account_id=ana.user.id + 1) is Reapplied.MISSING

    assert users(db_session) == [ana.user.id]
    assert count(db_session, AuditLog) == 0


def test_reapply_skips_the_last_admin(db_session, make_account):
    ana = make_account("ana@example.com", is_admin=True)
    # Admin bloqueado não conta
    make_account("root@example.com", is_admin=True, is_active=False)

    assert reapply_deletion(db_session, account_id=ana.user.id) is Reapplied.LAST_ADMIN

    assert ana.user.id in users(db_session)
    assert count(db_session, AuditLog) == 0


def test_reapply_deletes_an_admin_when_another_is_active(db_session, make_account):
    ana = make_account("ana@example.com", is_admin=True)
    root = make_account("root@example.com", is_admin=True)

    assert reapply_deletion(db_session, account_id=ana.user.id) is Reapplied.DELETED
    assert users(db_session) == [root.user.id]


def test_reapply_deletes_a_blocked_account(db_session, make_account):
    ana = make_account("ana@example.com", is_active=False)

    assert reapply_deletion(db_session, account_id=ana.user.id) is Reapplied.DELETED
    assert users(db_session) == []


# --- reapply_deletions e o contador de ids ---------------------------------------------------


def test_existing_missing_and_last_admin(db_session, make_account, database):
    root = make_account("root@example.com", is_admin=True)
    ana = make_account("ana@example.com")
    bia = make_account("bia@example.com")
    missing = bia.user.id + 10

    result = reapply_deletions(db_session, [ana.user.id, missing, root.user.id, bia.user.id])

    assert result.deleted == (ana.user.id, bia.user.id)
    assert result.missing == (missing,)
    assert result.last_admin == (root.user.id,)
    assert users(db_session) == [root.user.id]
    assert users_sequence(database) == missing

    # De novo: nada muda
    events = count(db_session, AuditLog)
    again = reapply_deletions(db_session, [ana.user.id, missing, root.user.id, bia.user.id])
    assert (again.deleted, again.missing, again.last_admin) == (
        (),
        (ana.user.id, missing, bia.user.id),
        (root.user.id,),
    )
    assert count(db_session, AuditLog) == events


def test_no_ids_does_nothing(db_session, database):
    result = reapply_deletions(db_session, [])

    assert (result.deleted, result.missing, result.last_admin) == ((), (), ())
    assert users_sequence(database) is None


def test_sequence_is_created_raised_and_never_lowered(db_session, database):
    # Banco novo: users nunca recebeu linha, então não tem linha no sqlite_sequence
    assert users_sequence(database) is None
    protect_account_ids(db_session, 5)
    assert users_sequence(database) == 5
    protect_account_ids(db_session, 9)
    assert users_sequence(database) == 9
    protect_account_ids(db_session, 2)
    assert users_sequence(database) == 9

    user = new_user()
    save(db_session, user)
    assert user.id == 10


@pytest.mark.parametrize("highest", [0, -1, MAX_ACCOUNT_ID + 1])
def test_sequence_refuses_ids_out_of_range(db_session, highest):
    with pytest.raises(ValueError, match="fora do intervalo"):
        protect_account_ids(db_session, highest)


# --- CLI --------------------------------------------------------------------------------------


def test_cli_reads_the_journal_from_stdin(db_session, env, make_account, stdin, capsys):
    ana = make_account("ana@example.com")
    bia = make_account("bia@example.com")
    missing = bia.user.id + 1
    stdin(
        "\n".join(
            [
                SYSTEMD_START,
                REQUEST,
                deleted_line(ana.user.id),
                EMAIL,
                deleted_line(missing),
                deleted_line(ana.user.id),
                "",
            ]
        )
    )

    assert main(["reapply-deletions"], env) == 0

    assert capsys.readouterr() == (
        "reapply-deletions: 6 linhas lidas, 2 contas no log (1 repetições ignoradas)\n"
        "reapply-deletions: 1 contas apagadas, 1 ignoradas (não existem no banco), "
        "0 puladas (último admin)\n",
        "",
    )
    assert users(db_session) == [bia.user.id]


def test_cli_reads_a_file_with_loose_ids(db_session, env, make_account, tmp_path, capsys):
    ana = make_account("ana@example.com")
    path = tmp_path / "ids.txt"
    path.write_text(f"{ana.user.id}\n{ana.user.id}\n", encoding="utf-8")

    assert main(["reapply-deletions", str(path)], env) == 0

    assert capsys.readouterr().out.endswith(
        "1 contas apagadas, 0 ignoradas (não existem no banco), 0 puladas (último admin)\n"
    )
    assert users(db_session) == []


def test_cli_warns_about_the_last_admin(db_session, env, make_account, stdin, capsys):
    ana = make_account("ana@example.com", is_admin=True)
    stdin(f"{ana.user.id}\n")

    assert main(["reapply-deletions", "-"], env) == 0

    out, err = capsys.readouterr()
    assert out.endswith(
        "0 contas apagadas, 0 ignoradas (não existem no banco), 1 puladas (último admin)\n"
    )
    assert err == (
        f"aviso: a conta {ana.user.id} é o último admin ativo e não foi apagada. Torne outra "
        "conta admin (create-admin) e rode o reapply-deletions de novo\n"
    )
    assert users(db_session) == [ana.user.id]


def test_cli_refuses_a_terminal(env, monkeypatch, capsys):
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())

    assert main(["reapply-deletions"], env) == 1
    assert capsys.readouterr().err.startswith("erro: mande as linhas pelo stdin")


def test_cli_refuses_empty_input(env, stdin, capsys):
    stdin("")

    assert main(["reapply-deletions"], env) == 1
    assert capsys.readouterr() == (
        "",
        "erro: entrada vazia; confira o journalctl (precisa de sudo)\n",
    )


def test_cli_missing_file(env, tmp_path, capsys):
    assert main(["reapply-deletions", str(tmp_path / "nao-existe.txt")], env) == 1
    assert capsys.readouterr().err == "erro: não consegui ler a entrada (FileNotFoundError)\n"


def test_cli_bad_line_deletes_nothing(db_session, env, make_account, stdin, capsys):
    ana = make_account("ana@example.com")
    bia = make_account("bia@example.com")
    stdin(
        f"{deleted_line(ana.user.id)}\nout 25 12:00:00 vm uvicorn[1]: {deleted_line(bia.user.id)}\n"
    )

    assert main(["reapply-deletions"], env) == 1

    assert capsys.readouterr() == (
        "",
        "erro: linha 2: linha de exclusão fora do formato do journalctl -o cat; nada foi apagado\n",
    )
    assert users(db_session) == [ana.user.id, bia.user.id]


def test_cli_runs_as_a_module_with_a_pipe(db_session, env, make_account):
    ana = make_account("ana@example.com")
    environ = {key: value for key, value in os.environ.items() if key not in ENV_VARS}

    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "reapply-deletions"],
        cwd=BACKEND_DIR,
        env=environ | env | {"PYTHONIOENCODING": "utf-8"},
        input=f"{UVICORN}\n{deleted_line(ana.user.id)}\n".encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )

    # Bytes de UTF-8 no pipe, como o journalctl manda; a saída sai em UTF-8 (PYTHONIOENCODING)
    assert (result.returncode, result.stderr) == (0, b"")
    assert result.stdout.decode().splitlines()[-1] == (
        "reapply-deletions: 1 contas apagadas, 0 ignoradas (não existem no banco), "
        "0 puladas (último admin)"
    )
    assert users(db_session) == []


# --- Ensaio: backup, exclusão, restore e reapply-deletions ------------------------------------


def test_restore_rehearsal(db_session, engine, settings, env, make_account, stdin, capsys, caplog):
    """O roteiro do infra/RESTORE.md com um banco de verdade.

    O backup é tirado com a Ana, a Bia e o Caio. Depois dele: o Davi se cadastra e se exclui, a
    Bia é excluída pelo admin (com um hábito compartilhado com o Caio e marcações dele). O restore
    traz a Bia de volta, e o log do serviço manda apagar a Bia e o Davi.
    """
    root = make_account("root@example.com", is_admin=True)
    bia = make_account("bia@example.com")
    caio = make_account("caio@example.com")
    habit = new_habit(bia.user)
    save(db_session, habit)
    save(db_session, new_member(habit, caio.user), new_mark(habit, MARKED_AT, user_id=caio.user.id))
    database = settings.database_path
    backup = database.with_name("pre-deploy-teste.db")
    with closing(sqlite3.connect(database)) as live, closing(sqlite3.connect(backup)) as copy:
        live.backup(copy)

    davi = new_user("davi@example.com")
    save(db_session, davi)
    with caplog.at_level(logging.INFO, logger=deletion.logger.name):
        delete_account(db_session, account_id=davi.id, actor_id=davi.id, ip=None)
        delete_account(db_session, account_id=bia.user.id, actor_id=root.user.id, ip=None)
    journal = [
        SYSTEMD_START,
        UVICORN,
        REQUEST,
        *(logs._handler.format(record) for record in caplog.records),
        EMAIL,
    ]
    assert deleted_events(db_session, bia.user.id) == [
        (root.user.id, None, {"account_id": bia.user.id, "by_admin": True})
    ]

    # Restore, com tudo fechado (o serviço parado): o arquivo do backup no lugar do banco
    db_session.close()
    engine.dispose()
    shutil.copyfile(backup, database)
    for suffix in ("-wal", "-shm"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert users(db_session) == [root.user.id, bia.user.id, caio.user.id]
    assert deleted_events(db_session, bia.user.id) == []

    stdin("\n".join(journal) + "\n")
    assert main(["reapply-deletions"], env) == 0
    assert capsys.readouterr().out.endswith(
        "1 contas apagadas, 1 ignoradas (não existem no banco), 0 puladas (último admin)\n"
    )

    # A Bia continua apagada, com um account_deleted só e sem email (fixture no_email)
    assert users(db_session) == [root.user.id, caio.user.id]
    assert count(db_session, Habit) == 0
    assert count(db_session, Mark) == 0
    assert deleted_events(db_session, bia.user.id) == [
        (None, None, {"account_id": bia.user.id, "reapplied": True})
    ]
    # O Davi não existia no backup, e o id dele não volta para outra conta
    assert deleted_events(db_session, davi.id) == []
    new = new_user("eva@example.com")
    save(db_session, new)
    assert new.id > davi.id

    # De novo, com o mesmo log: nada muda
    before = db_session.execute(text("SELECT * FROM audit_log ORDER BY id")).all()
    stdin("\n".join(journal) + "\n")
    assert main(["reapply-deletions"], env) == 0
    assert capsys.readouterr().out.endswith(
        "0 contas apagadas, 2 ignoradas (não existem no banco), 0 puladas (último admin)\n"
    )
    db_session.rollback()
    assert db_session.execute(text("SELECT * FROM audit_log ORDER BY id")).all() == before
    assert users(db_session) == [root.user.id, caio.user.id, new.id]
