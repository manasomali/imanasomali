"""Reaplicar exclusões depois de um restore (ETH-61): `app/reapply.py` e
`python -m app.cli reapply-deletions`."""

import io
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import select, text, update

from app import deletion, logs
from app.audit import AuditEvent
from app.cli import main
from app.config import ENV_VARS
from app.db import create_session_factory, write_transaction
from app.deletion import DeletionMode, start_deletion
from app.internal.tasks import TaskContext
from app.mail.sender import Mailer
from app.models import MAX_ACCOUNT_ID, AppTask, AuditLog, MailLog, User
from app.reapply import (
    AccountIds,
    InputError,
    ReapplyResult,
    parse_account_id,
    read_account_ids,
    reapply_deletions,
)
from tests.conftest import BACKEND_DIR
from tests.factories import count, new_user, save
from tests.test_cli import env_for

# Linhas de verdade do `journalctl -u app-imago -o cat`, em volta das de exclusão
SYSTEMD_START = "Started app-imago.service - imago: API em /api/imago/."
ALEMBIC = "INFO  [alembic.runtime.migration] Context impl SQLiteImpl."
UVICORN = "INFO:     Started server process [4242]"
REQUEST = "INFO app.request: DELETE /me 204 12.3ms"
FINISHED = "INFO app.deletion: exclusão da conta 7 concluída"
TASK = "WARNING app.internal.tasks: tarefa delete de ethos para a conta 7 falhou (ConnectError)"


def deleted_line(account_id: int) -> str:
    return f"INFO app.deletion: conta {account_id} excluída"


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


@pytest.fixture
def cli(env, apps) -> Callable[..., int]:
    def run(*argv: str) -> int:
        return main(["reapply-deletions", *argv], env, app_transport=apps.transport)

    return run


def users(db_session) -> list[int]:
    db_session.rollback()
    return sorted(db_session.scalars(select(User.id)))


def deleted_events(db_session, account_id: int) -> list[tuple]:
    db_session.rollback()
    rows = db_session.execute(
        select(AuditLog.user_id, AuditLog.ip, AuditLog.details).where(
            AuditLog.event == AuditEvent.ACCOUNT_DELETED,
            AuditLog.details["account_id"].as_integer() == account_id,
        )
    ).all()
    return [tuple(row) for row in rows]


def reapplied(account_id: int) -> tuple:
    return (None, None, {"account_id": account_id, "reapplied": True})


# --- leitura dos ids ---


def test_reads_the_line_the_app_writes(caplog):
    # A linha montada pelo próprio app: o logger e a mensagem de deletion.py com o formato de
    # app/logs.py. Se um dos dois mudar, a leitura das linhas antigas precisa mudar junto
    with caplog.at_level(logging.INFO, logger=deletion.logger.name):
        deletion.log_started(7)
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
        f"{TASK}\n",
        f"{FINISHED}\n",
        "\n",
        f"{deleted_line(3)}\r\n",
        "42\n",
        "  43  \n",
        f"{deleted_line(7)}\n",
        "42",
    ]

    assert read_account_ids(lines) == AccountIds(ids=(7, 3, 42, 43), lines=13, repeated=2)


def test_empty_input():
    assert read_account_ids([]) == AccountIds(ids=(), lines=0, repeated=0)


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        # journalctl sem -o cat: data, host e processo na frente
        (
            f"nov 08 12:00:00 vm uvicorn[4242]: {deleted_line(7)}",
            "fora do formato do journalctl -o cat",
        ),
        ("WARNING app.deletion: conta 7 excluída", "fora do formato"),
        ("INFO app.deletion: conta 0 excluída", "fora do formato"),
        ("INFO app.deletion: conta 7 excluída de novo", "fora do formato"),
        (deleted_line(MAX_ACCOUNT_ID + 1), "maior que 2\\^53 - 1"),
        ("0", "id inválido"),
        ("007", "id inválido"),
        ("-3", "id inválido"),
        ("+3", "id inválido"),
        (str(MAX_ACCOUNT_ID + 1), "maior que 2\\^53 - 1"),
        ("12345678901234567890", "maior que 2\\^53 - 1"),
    ],
)
def test_refuses_lines_that_look_like_a_deletion_or_an_id(line, reason):
    with pytest.raises(InputError, match=reason) as caught:
        read_account_ids([REQUEST, line])
    assert str(caught.value).startswith("linha 2: ")


def test_largest_valid_id():
    assert read_account_ids([str(MAX_ACCOUNT_ID)]).ids == (MAX_ACCOUNT_ID,)
    assert parse_account_id(str(MAX_ACCOUNT_ID)) == MAX_ACCOUNT_ID


@pytest.mark.parametrize("value", ["0", "01", "-1", "1.0", "", " 1", str(MAX_ACCOUNT_ID + 1)])
def test_parse_account_id_refuses(value):
    with pytest.raises(ValueError, match="id de conta inválido"):
        parse_account_id(value)


# --- reapply_deletions ---


def test_existing_account_is_deleted_again_without_email(
    db_session, task_context, apps, make_account, caplog
):
    ana = make_account("ana@example.com")

    with caplog.at_level(logging.INFO, logger="app"):
        result = reapply_deletions(task_context, [ana.user.id])

    assert result == ReapplyResult(deleted=(ana.user.id,))
    assert users(db_session) == []
    assert apps.of("delete") == [("ethos", ana.user.id), ("engrafi", ana.user.id)]
    assert deleted_events(db_session, ana.user.id) == [reapplied(ana.user.id)]
    # Nenhuma linha nova de exclusão no log (a original continua no journald) e nenhum email
    assert f"conta {ana.user.id} excluída" not in caplog.messages
    assert count(db_session, MailLog) == 0
    assert count(db_session, AuditLog, AuditLog.event == "account_deletion_started") == 0


def test_missing_account_is_deleted_in_the_apps(db_session, task_context, apps, make_account):
    bia = make_account("bia@example.com")
    missing = bia.user.id + 1

    result = reapply_deletions(task_context, [missing])

    assert result == ReapplyResult(missing=(missing,))
    assert apps.of("delete") == [("ethos", missing), ("engrafi", missing)]
    assert users(db_session) == [bia.user.id]
    assert count(db_session, AuditLog) == 0


def test_app_down_leaves_a_task_or_a_failed_call(
    db_session, task_context, env, apps, make_account, capsys
):
    ana = make_account("ana@example.com")
    missing = ana.user.id + 1
    apps.down.add("engrafi")

    result = reapply_deletions(task_context, [ana.user.id, missing])

    assert result == ReapplyResult(
        deleted=(ana.user.id,),
        missing=(missing,),
        pending=(ana.user.id,),
        failed_calls=((missing, "engrafi", "ConnectError"),),
    )
    assert users(db_session) == [ana.user.id]
    assert db_session.get(User, ana.user.id).status == "deleting"

    # O engrafi volta: o run-tasks termina a exclusão, também sem email
    apps.down.clear()
    assert main(["run-tasks"], env, app_transport=apps.transport) == 0
    assert capsys.readouterr().out.endswith("1 exclusões de conta concluídas\n")
    assert users(db_session) == []
    assert deleted_events(db_session, ana.user.id) == [reapplied(ana.user.id)]


def test_last_admin_is_skipped(db_session, task_context, apps, make_account):
    ana = make_account("ana@example.com", is_admin=True)

    assert reapply_deletions(task_context, [ana.user.id]) == ReapplyResult(
        last_admin=(ana.user.id,)
    )
    assert users(db_session) == [ana.user.id]
    assert apps.calls == []


def test_blocked_admin_is_deleted(db_session, task_context, make_account):
    ana = make_account("ana@example.com", is_admin=True, is_active=False)

    assert reapply_deletions(task_context, [ana.user.id]).deleted == (ana.user.id,)
    assert users(db_session) == []


def test_deletion_in_progress_in_the_backup_finishes_without_email(
    db_session, settings, task_context, apps, make_account
):
    root = make_account("root@example.com", is_admin=True)
    bia = make_account("bia@example.com")
    # O backup pegou a Bia no meio da exclusão, pedida pelo admin, com o ethos já feito
    with write_transaction(db_session):
        user = deletion.reload_user(db_session, bia.user.id)
        start_deletion(db_session, settings, user, actor_id=root.user.id, mode=DeletionMode.ADMIN)
        db_session.execute(
            update(AppTask).where(AppTask.app == "ethos").values(done_at=AppTask.created_at)
        )

    result = reapply_deletions(task_context, [bia.user.id])

    assert result == ReapplyResult(deleted=(bia.user.id,))
    # O ethos recebe o delete de novo (o banco dele pode ser o restaurado)
    assert apps.of("delete") == [("engrafi", bia.user.id), ("ethos", bia.user.id)]
    assert users(db_session) == [root.user.id]
    assert deleted_events(db_session, bia.user.id) == [reapplied(bia.user.id)]


def test_without_apps_only_the_imago_changes(make_settings, engine, db_session, apps, make_account):
    context = TaskContext(
        make_settings(imago_apps=""), create_session_factory(engine), apps.transport
    )
    ana = make_account("ana@example.com")

    result = reapply_deletions(context, [ana.user.id, ana.user.id + 1])

    assert result == ReapplyResult(deleted=(ana.user.id,), missing=(ana.user.id + 1,))
    assert apps.calls == []
    assert users(db_session) == []


def test_running_twice_changes_nothing(db_session, task_context, apps, make_account):
    ana = make_account("ana@example.com")
    reapply_deletions(task_context, [ana.user.id])
    before = db_session.execute(text("SELECT * FROM audit_log ORDER BY id")).all()

    assert reapply_deletions(task_context, [ana.user.id]) == ReapplyResult(missing=(ana.user.id,))

    db_session.rollback()
    assert db_session.execute(text("SELECT * FROM audit_log ORDER BY id")).all() == before


# --- CLI ---


def test_cli_reads_the_journal_from_stdin(db_session, cli, make_account, stdin, capsys):
    ana = make_account("ana@example.com")
    bia = make_account("bia@example.com")
    missing = max(ana.user.id, bia.user.id) + 1
    stdin(
        "\n".join(
            [
                SYSTEMD_START,
                REQUEST,
                deleted_line(ana.user.id),
                FINISHED,
                deleted_line(missing),
                deleted_line(ana.user.id),
                "",
            ]
        )
    )

    assert cli() == 0

    assert capsys.readouterr() == (
        "reapply-deletions: 6 linhas lidas, 2 contas no log (1 repetições ignoradas)\n"
        "reapply-deletions: 1 contas apagadas de novo no imago (0 esperando uma aplicação: "
        "rode o run-tasks), 1 que já não existiam no imago, 0 puladas (último admin); "
        "0 chamadas às aplicações falharam\n",
        "",
    )
    assert users(db_session) == [bia.user.id]


def test_cli_takes_ids_as_arguments(db_session, cli, make_account, capsys):
    ana = make_account("ana@example.com")

    assert cli(str(ana.user.id), str(ana.user.id)) == 0

    out = capsys.readouterr().out
    assert out.startswith("reapply-deletions: 1 contas nos argumentos\n")
    assert "1 contas apagadas de novo no imago" in out
    assert users(db_session) == []


@pytest.mark.parametrize("value", ["0", "abc", str(MAX_ACCOUNT_ID + 1)])
def test_cli_refuses_an_invalid_id_argument(cli, capsys, value):
    with pytest.raises(SystemExit) as raised:
        cli(value)

    assert raised.value.code == 2
    assert "id de conta inválido" in capsys.readouterr().err


def test_cli_fails_when_an_app_did_not_delete_a_missing_account(
    db_session, cli, apps, make_account, capsys
):
    bia = make_account("bia@example.com")
    missing = bia.user.id + 1
    apps.status["ethos"] = 500

    assert cli(str(missing)) == 1

    out, err = capsys.readouterr()
    assert out.endswith("1 chamadas às aplicações falharam\n")
    assert err == (
        f"aviso: ethos não apagou a conta {missing} (HTTP 500)\n"
        "erro: o delete falhou em alguma aplicação para contas que já não existem no imago; "
        "confira a aplicação e rode o reapply-deletions de novo\n"
    )


def test_cli_warns_about_the_last_admin(db_session, cli, make_account, stdin, capsys):
    ana = make_account("ana@example.com", is_admin=True)
    stdin(f"{ana.user.id}\n")

    assert cli() == 0

    out, err = capsys.readouterr()
    assert out.endswith("1 puladas (último admin); 0 chamadas às aplicações falharam\n")
    assert err == (
        f"aviso: a conta {ana.user.id} é o último admin ativo e não foi apagada. Torne outra "
        "conta admin (create-admin) e rode o reapply-deletions de novo\n"
    )
    assert users(db_session) == [ana.user.id]


def test_cli_refuses_a_terminal(cli, monkeypatch, capsys):
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())

    assert cli() == 1
    assert capsys.readouterr().err.startswith("erro: mande as linhas pelo stdin")


def test_cli_refuses_empty_input(cli, stdin, capsys):
    stdin("")

    assert cli() == 1
    assert capsys.readouterr() == (
        "",
        "erro: entrada vazia; confira o journalctl (precisa de sudo)\n",
    )


def test_cli_unreadable_input(cli, monkeypatch, capsys):
    class Broken(io.BytesIO):
        def __iter__(self):
            raise OSError("disco")

    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(Broken()))

    assert cli() == 1
    assert capsys.readouterr().err == "erro: não consegui ler a entrada (OSError)\n"


def test_cli_bad_line_deletes_nothing(db_session, cli, apps, make_account, stdin, capsys):
    ana = make_account("ana@example.com")
    bia = make_account("bia@example.com")
    stdin(
        f"{deleted_line(ana.user.id)}\nnov 08 12:00:00 vm uvicorn[1]: {deleted_line(bia.user.id)}\n"
    )

    assert cli() == 1

    assert capsys.readouterr() == (
        "",
        "erro: linha 2: linha de exclusão fora do formato do journalctl -o cat; nada foi apagado\n",
    )
    assert users(db_session) == sorted([ana.user.id, bia.user.id])
    assert apps.calls == []


def test_cli_runs_as_a_module_with_a_pipe(db_session, env, make_account):
    # Como no ensaio do infra/RESTORE.md: IMAGO_APPS vazio, só o banco do imago muda
    ana = make_account("ana@example.com")
    environ = {key: value for key, value in os.environ.items() if key not in ENV_VARS}

    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "reapply-deletions"],
        cwd=BACKEND_DIR,
        env=environ | env | {"IMAGO_APPS": "", "PYTHONIOENCODING": "utf-8"},
        input=f"{UVICORN}\n{deleted_line(ana.user.id)}\n".encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )

    # Bytes de UTF-8 no pipe, como o journalctl manda; a saída sai em UTF-8 (PYTHONIOENCODING)
    assert result.returncode == 0
    # No stderr, só o log do passo 3 (o id, nunca o email)
    assert result.stderr.decode().splitlines() == [
        f"INFO app.deletion: exclusão da conta {ana.user.id} concluída"
    ]
    assert (
        result.stdout.decode()
        .splitlines()[-1]
        .startswith("reapply-deletions: 1 contas apagadas de novo no imago")
    )
    assert users(db_session) == []


# --- ensaio: backup, exclusão, restore e reapply-deletions ---


def test_restore_rehearsal(
    db_session, engine, settings, env, apps, make_account, stdin, capsys, caplog
):
    """O roteiro do infra/RESTORE.md com um banco de verdade.

    O backup é tirado com o root, a Bia e o Caio. Depois dele: o Davi se cadastra e se exclui, e a
    Bia é excluída pelo admin. O restore traz a Bia de volta, e o log do serviço manda apagar a
    Bia e o Davi. A Bia sai do imago e das aplicações; o Davi, que o backup não tem, só das
    aplicações.
    """
    root = make_account("root@example.com", is_admin=True)
    bia = make_account("bia@example.com")
    caio = make_account("caio@example.com")
    database = settings.database_path
    backup = database.with_name("pre-deploy-teste.db")
    with closing(sqlite3.connect(database)) as live, closing(sqlite3.connect(backup)) as copy:
        live.backup(copy)

    davi = new_user("davi@example.com")
    save(db_session, davi)
    with caplog.at_level(logging.INFO, logger=deletion.logger.name):
        for account_id, actor, mode in (
            (davi.id, davi.id, DeletionMode.SELF),
            (bia.user.id, root.user.id, DeletionMode.ADMIN),
        ):
            with write_transaction(db_session):
                user = deletion.reload_user(db_session, account_id)
                start_deletion(db_session, settings, user, actor_id=actor, mode=mode)
            deletion.log_started(account_id)
    journal = [
        SYSTEMD_START,
        UVICORN,
        REQUEST,
        *(logs._handler.format(record) for record in caplog.records),
    ]

    # Restore, com tudo fechado (o serviço parado): o arquivo do backup no lugar do banco
    db_session.close()
    engine.dispose()
    shutil.copyfile(backup, database)
    for suffix in ("-wal", "-shm"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert users(db_session) == sorted([root.user.id, bia.user.id, caio.user.id])

    stdin("\n".join(journal) + "\n")
    assert main(["reapply-deletions"], env, app_transport=apps.transport) == 0
    assert capsys.readouterr().out.endswith(
        "1 contas apagadas de novo no imago (0 esperando uma aplicação: rode o run-tasks), "
        "1 que já não existiam no imago, 0 puladas (último admin); "
        "0 chamadas às aplicações falharam\n"
    )
    assert users(db_session) == sorted([root.user.id, caio.user.id])
    assert deleted_events(db_session, bia.user.id) == [reapplied(bia.user.id)]
    assert deleted_events(db_session, davi.id) == []
    assert sorted(apps.of("delete")) == sorted(
        [(app, account) for app in ("ethos", "engrafi") for account in (davi.id, bia.user.id)]
    )

    # De novo, com o mesmo log: nada muda no imago (as aplicações recebem o delete outra vez)
    before = db_session.execute(text("SELECT * FROM audit_log ORDER BY id")).all()
    stdin("\n".join(journal) + "\n")
    assert main(["reapply-deletions"], env, app_transport=apps.transport) == 0
    assert "0 contas apagadas de novo no imago" in capsys.readouterr().out
    db_session.rollback()
    assert db_session.execute(text("SELECT * FROM audit_log ORDER BY id")).all() == before
