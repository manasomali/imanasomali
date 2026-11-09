"""Reaplicar as exclusões de antes do imago depois de um restore (ETH-42, ETH-64):
`app/internal/reapply.py` e `python -m app.cli reapply-deletions`.

As linhas do journal são as do login próprio do ethos (`INFO app.auth.deletion: conta <id>
excluída`), gravadas até a passagem para o imago. Um backup de antes delas, restaurado e migrado,
traz as contas de volta como linhas de `app_users`."""

import io
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
from sqlalchemy import select

from app.cli import main
from app.config import ENV_VARS
from app.internal.reapply import (
    LEGACY_LOGGER,
    AccountIds,
    InputError,
    read_account_ids,
    reapply_deletions,
)
from app.mail.sender import Mailer
from app.models import AppUser, Habit, HabitInvite, Mark
from tests.conftest import BACKEND_DIR
from tests.factories import count, new_habit, new_invite, new_mark, new_member, save
from tests.test_cli import env_for

# Linhas de verdade do `journalctl -u app-ethos -o cat`, em volta das de exclusão
SYSTEMD_START = "Started app-ethos.service - ethos: API em /api/ethos/."
ALEMBIC = "INFO  [alembic.runtime.migration] Context impl SQLiteImpl."
UVICORN = "INFO:     Started server process [4242]"
REQUEST = "INFO app.request: DELETE /admin/users/{user_id} 204 12.3ms"
EMAIL = "INFO app.mail.sender: email account_deleted enviado"
MAX_ID = 2**53 - 1

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
    return list(db_session.scalars(select(AppUser.id).order_by(AppUser.id)))


# --- Leitura dos ids -------------------------------------------------------------------------


def test_reads_the_legacy_line():
    assert LEGACY_LOGGER == "app.auth.deletion"
    assert read_account_ids([deleted_line(7)]) == AccountIds(ids=(7,), lines=1, repeated=0)


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
        # As exclusões de depois do imago (outra linha, de outro módulo) são ignoradas aqui
        "INFO app.internal.service: dados da conta 99 apagados",
    ]

    assert read_account_ids(lines) == AccountIds(ids=(7, 3, 42, 43), lines=13, repeated=2)


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
        (str(MAX_ID + 1), "id grande demais"),
    ],
)
def test_refuses_lines_that_look_like_a_deletion_or_an_id(line, reason):
    with pytest.raises(InputError, match=reason) as caught:
        read_account_ids([REQUEST, line])
    assert str(caught.value).startswith("linha 2: ")


def test_largest_valid_id():
    assert read_account_ids([str(MAX_ID)]).ids == (MAX_ID,)


# --- reapply_deletions -----------------------------------------------------------------------


def test_existing_and_missing(db_session, make_account):
    ana = make_account("ana@example.com", admin=True)
    bia = make_account("bia@example.com")
    caio = make_account("caio@example.com")
    habit = new_habit(ana.user)
    save(db_session, habit)
    save(db_session, new_member(habit, bia.user))
    # Convite recebido por quem não existe mais no ethos: sai também
    save(db_session, new_invite(habit, "x@example.com", invited_user_id=555))
    missing = 555

    result = reapply_deletions(db_session, [ana.user.id, missing, bia.user.id])

    assert result.deleted == (ana.user.id, bia.user.id)
    assert result.missing == (missing,)
    # Sem conferir admin: o admin é do imago
    assert users(db_session) == [caio.user.id]
    assert count(db_session, Habit) == 0
    assert count(db_session, HabitInvite) == 0

    # De novo: nada muda
    again = reapply_deletions(db_session, [ana.user.id, missing, bia.user.id])
    assert (again.deleted, again.missing) == ((), (ana.user.id, missing, bia.user.id))
    assert users(db_session) == [caio.user.id]


def test_no_ids_does_nothing(db_session, make_account):
    ana = make_account("ana@example.com")

    result = reapply_deletions(db_session, [])

    assert (result.deleted, result.missing) == ((), ())
    assert users(db_session) == [ana.user.id]


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
        "reapply-deletions: 1 contas apagadas, 1 sem linha em app_users "
        "(só convites recebidos, se sobravam)\n",
        "",
    )
    assert users(db_session) == [bia.user.id]


def test_cli_reads_a_file_with_loose_ids(db_session, env, make_account, tmp_path, capsys):
    ana = make_account("ana@example.com")
    path = tmp_path / "ids.txt"
    path.write_text(f"{ana.user.id}\n{ana.user.id}\n", encoding="utf-8")

    assert main(["reapply-deletions", str(path)], env) == 0

    assert capsys.readouterr().out.endswith(
        "1 contas apagadas, 0 sem linha em app_users (só convites recebidos, se sobravam)\n"
    )
    assert users(db_session) == []


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

    # Bytes de UTF-8 no pipe, como o journalctl manda; a saída sai em UTF-8 (PYTHONIOENCODING).
    # No log, só o id numérico de cada conta apagada
    assert result.returncode == 0
    assert result.stderr.decode().splitlines() == [
        f"INFO app.internal.service: dados da conta {ana.user.id} apagados"
    ]
    assert result.stdout.decode().splitlines()[-1] == (
        "reapply-deletions: 1 contas apagadas, 0 sem linha em app_users "
        "(só convites recebidos, se sobravam)"
    )
    assert users(db_session) == []


# --- Ensaio: backup, exclusão, restore e reapply-deletions ------------------------------------


def test_restore_rehearsal(db_session, engine, settings, env, make_account, stdin, capsys):
    """O roteiro do infra/RESTORE.md para as exclusões de antes do imago, com um banco de verdade.

    O backup é tirado com a Bia e o Caio. Depois dele, a Bia (com um hábito compartilhado com o
    Caio e marcações dele) foi excluída pelo login próprio, que gravou a linha no journal. O
    restore traz a Bia de volta, e o log do serviço manda apagar a Bia de novo.
    """
    bia = make_account("bia@example.com")
    caio = make_account("caio@example.com")
    habit = new_habit(bia.user)
    save(db_session, habit)
    save(db_session, new_member(habit, caio.user), new_mark(habit, MARKED_AT, user_id=caio.user.id))
    database = settings.database_path
    backup = database.with_name("pre-deploy-teste.db")
    db_session.close()
    with closing(sqlite3.connect(database)) as live, closing(sqlite3.connect(backup)) as copy:
        live.backup(copy)
    journal = [SYSTEMD_START, UVICORN, REQUEST, deleted_line(bia.user.id), EMAIL]

    # Restore, com tudo fechado (o serviço parado): o arquivo do backup no lugar do banco
    engine.dispose()
    shutil.copyfile(backup, database)
    for suffix in ("-wal", "-shm"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert users(db_session) == [bia.user.id, caio.user.id]

    stdin("\n".join(journal) + "\n")
    assert main(["reapply-deletions"], env) == 0
    assert "1 contas apagadas, 0 sem linha" in capsys.readouterr().out

    # A Bia continua apagada, sem email (fixture no_email); a marcação do Caio sai com o hábito
    assert users(db_session) == [caio.user.id]
    assert count(db_session, Habit) == 0
    assert count(db_session, Mark) == 0

    # De novo, com o mesmo log: nada muda
    stdin("\n".join(journal) + "\n")
    assert main(["reapply-deletions"], env) == 0
    assert "0 contas apagadas, 1 sem linha" in capsys.readouterr().out
    assert users(db_session) == [caio.user.id]
