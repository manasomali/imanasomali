"""Exclusão de conta (`app/deletion.py`, `POST /me/delete/request`, `DELETE /me`), ETH-61."""

import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import time_machine
from sqlalchemy import select, update

from app import audit, deletion
from app.audit import AuditEvent
from app.auth.cookies import SESSION_COOKIE_NAME
from app.auth.service import VerifyFailure
from app.cli import main
from app.db import create_session_factory, write_transaction
from app.deletion import DeletionMode, finish_and_notify, finish_deletion, start_deletion
from app.errors import ApiError, ErrorCode
from app.internal import tasks
from app.internal.tasks import TaskContext, run_task
from app.mail.sender import Mailer
from app.main import create_app
from app.models import AppTask, AuditLog, LoginCode, MailLog, User, UserSession
from app.terms import TERMS_VERSION
from tests.apps_helpers import Call
from tests.auth_helpers import Account, code_in
from tests.factories import count, new_user, save
from tests.internal_helpers import ENGRAFI_TOKEN, ETHOS_TOKEN
from tests.mail_helpers import Outbox
from tests.test_cli import env_for

ANA = "ana@example.com"
ANA_OLD = "ana.antiga@example.com"
NOW = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)
LAST_ADMIN = {"error": "last_admin", "field": None}
INVALID_CODE = {"error": "invalid_code", "field": "code"}
UNAUTHORIZED = {"error": "unauthorized", "field": None}
DELETED_SUBJECT = "Sua conta do manasomali.com foi excluída"


def ask_code(client, outbox: Outbox, account: Account) -> str:
    response = client.post("/me/delete/request", headers=account.headers)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    return code_in(outbox.to(account.user.email)[-1])


def delete_me(client, account: Account, code: str):
    return client.request("DELETE", "/me", json={"code": code}, headers=account.headers)


def events(db_session, event: AuditEvent) -> list[AuditLog]:
    db_session.rollback()
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(AuditLog.event == event.value)
            .order_by(AuditLog.id)
            .execution_options(populate_existing=True)
        )
    )


def reload(db_session, user_id: int) -> User | None:
    db_session.rollback()
    return deletion.reload_user(db_session, user_id)


def subjects(outbox: Outbox, address: str) -> list[str]:
    return [message["Subject"] for message in outbox.to(address)]


@pytest.fixture
def ana(make_account) -> Account:
    return make_account(ANA)


@pytest.fixture
def env(settings, database) -> dict[str, str]:
    return env_for(settings)


# --- fluxo completo ---


def test_full_flow_with_two_apps(client, outbox, db_session, apps, ana, caplog):
    code = ask_code(client, outbox, ana)

    with caplog.at_level(logging.INFO, logger="app"):
        response = delete_me(client, ana, code)

    assert response.status_code == 204
    # As duas aplicações receberam o delete, cada uma com o seu token
    assert apps.calls == [
        Call("ethos", "delete", ana.user.id, ETHOS_TOKEN, None),
        Call("engrafi", "delete", ana.user.id, ENGRAFI_TOKEN, None),
    ]
    assert reload(db_session, ana.user.id) is None
    assert count(db_session, AppTask) == 0
    assert count(db_session, UserSession) == 0
    assert count(db_session, LoginCode) == 0
    assert subjects(outbox, ANA) == [
        "Código para excluir sua conta do manasomali.com",
        DELETED_SUBJECT,
    ]
    [deleted] = events(db_session, AuditEvent.ACCOUNT_DELETED)
    assert (deleted.user_id, deleted.ip, deleted.details) == (
        None,
        None,
        {"account_id": ana.user.id, "by_admin": False},
    )
    # Só o account_deleted sobra: a auditoria da conta (o pedido do código, o início) saiu
    assert [entry.event for entry in db_session.scalars(select(AuditLog))] == ["account_deleted"]
    # Um código e um email de conta no teto, sem destinatário
    assert sorted(db_session.scalars(select(MailLog.kind))) == ["account", "code"]
    assert f"conta {ana.user.id} excluída" in caplog.messages
    assert f"exclusão da conta {ana.user.id} concluída" in caplog.messages


def test_request_writes_the_code_and_the_event(client, outbox, db_session, ana):
    ask_code(client, outbox, ana)

    [row] = db_session.scalars(select(LoginCode))
    assert (row.email, row.user_id, row.purpose) == (ANA, ana.user.id, "delete_account")
    [event] = events(db_session, AuditEvent.DELETE_CODE_REQUESTED)
    assert event.user_id == ana.user.id


def test_one_app_down_leaves_the_account_deleting_until_run_tasks(
    client, outbox, db_session, apps, env, ana, capsys
):
    apps.down.add("ethos")
    code = ask_code(client, outbox, ana)
    outbox.messages.clear()

    with time_machine.travel(NOW, tick=False):
        assert delete_me(client, ana, code).status_code == 204

    user = reload(db_session, ana.user.id)
    assert user is not None
    assert user.status == "deleting"
    pending = [task for task in db_session.scalars(select(AppTask)) if task.done_at is None]
    assert [(task.app, task.action, task.attempts) for task in pending] == [("ethos", "delete", 1)]
    assert outbox.messages == []

    # Enquanto isso: não entra, não recebe código e o email não cria conta nova
    assert client.get("/me", headers=ana.headers).status_code == 401
    assert client.post("/auth/code/request", json={"email": ANA}).status_code == 202
    assert outbox.messages == []

    # O ethos volta; o run-tasks da hora seguinte termina a exclusão e manda o email
    apps.down.clear()
    with time_machine.travel(NOW + timedelta(hours=1), tick=False):
        assert main(["run-tasks"], env, app_transport=apps.transport, mail_backend=outbox) == 0

    assert capsys.readouterr().out == (
        "run-tasks: 1 tarefas tentadas, 1 concluídas, 0 falhas, 0 ficaram para depois; "
        "1 exclusões de conta concluídas\n"
    )
    assert reload(db_session, ana.user.id) is None
    assert subjects(outbox, ANA) == [DELETED_SUBJECT]
    assert len(events(db_session, AuditEvent.ACCOUNT_DELETED)) == 1

    # De novo: nada a fazer
    assert main(["run-tasks"], env, app_transport=apps.transport, mail_backend=outbox) == 0
    assert capsys.readouterr().out.endswith("0 exclusões de conta concluídas\n")


def test_without_apps_the_deletion_ends_in_the_request(
    make_settings, db_session, make_client, outbox, apps, make_account
):
    client = make_client(
        create_app(make_settings(imago_apps=""), mail_backend=outbox, app_transport=apps.transport)
    )
    ana = make_account(ANA)

    assert delete_me(client, ana, ask_code(client, outbox, ana)).status_code == 204

    assert apps.calls == []
    assert reload(db_session, ana.user.id) is None
    assert subjects(outbox, ANA)[-1] == DELETED_SUBJECT


def test_request_and_run_tasks_finishing_at_the_same_time(settings, engine, db_session, apps, ana):
    with write_transaction(db_session):
        user = deletion.reload_user(db_session, ana.user.id)
        start_deletion(db_session, settings, user, actor_id=user.id, mode=DeletionMode.SELF)
    ethos, engrafi = (task.id for task in db_session.scalars(select(AppTask).order_by(AppTask.id)))
    context = TaskContext(settings, create_session_factory(engine), apps.transport)
    outbox = Outbox()
    mailer = Mailer(settings, outbox)
    in_flight = threading.Barrier(2, timeout=10)
    both_done = threading.Barrier(2, timeout=10)
    apps.before_reply = lambda _call: in_flight.wait()

    def finish_one(task_id: int) -> bool:
        with context.http_client() as client:
            assert run_task(context, client, task_id) == tasks.TaskOutcome.DONE
        both_done.wait()
        return finish_and_notify(context, mailer, ana.user.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(finish_one, [ethos, engrafi]))

    assert sorted(results) == [False, True]
    assert subjects(outbox, ANA) == [DELETED_SUBJECT]
    assert len(events(db_session, AuditEvent.ACCOUNT_DELETED)) == 1


def test_finish_deletion_does_nothing_until_it_is_time(db_session, settings, ana):
    # Conta ativa
    assert finish_deletion(db_session, settings, ana.user.id) is None
    with write_transaction(db_session):
        user = deletion.reload_user(db_session, ana.user.id)
        start_deletion(db_session, settings, user, actor_id=user.id, mode=DeletionMode.SELF)
    # Tarefas pendentes
    assert finish_deletion(db_session, settings, ana.user.id) is None
    with write_transaction(db_session):
        db_session.execute(update(AppTask).values(done_at=NOW))
    finished = finish_deletion(db_session, settings, ana.user.id)
    assert finished is not None
    assert (finished.account_id, finished.mode) == (ana.user.id, DeletionMode.SELF)
    # Conta que já não existe
    assert finish_deletion(db_session, settings, ana.user.id) is None


def test_continue_deletion_never_raises(task_context, settings, monkeypatch, caplog):
    def broken(*_args, **_kwargs):
        raise RuntimeError("segredo@example.com")

    monkeypatch.setattr(deletion, "run_pending", broken)

    deletion.continue_deletion(task_context, Mailer(settings, Outbox()), 42)

    assert caplog.messages == [
        "a exclusão da conta 42 não continuou (RuntimeError); fica para o run-tasks"
    ]


# --- quem apagou ---


def test_admin_deletion_records_the_admin(db_session, settings, task_context, make_account):
    root = make_account("root@example.com", is_admin=True)
    bia = make_account("bia@example.com")
    outbox = Outbox()
    with write_transaction(db_session):
        user = deletion.reload_user(db_session, bia.user.id)
        start_deletion(
            db_session,
            settings,
            user,
            actor_id=root.user.id,
            mode=DeletionMode.ADMIN,
            ip="203.0.113.7",
        )
    [started] = events(db_session, AuditEvent.ACCOUNT_DELETION_STARTED)
    assert (started.user_id, started.ip, started.details) == (
        root.user.id,
        "203.0.113.7",
        {"target_user_id": bia.user.id, "by_admin": True},
    )

    deletion.continue_deletion(task_context, Mailer(settings, outbox), bia.user.id)

    [deleted] = events(db_session, AuditEvent.ACCOUNT_DELETED)
    assert (deleted.user_id, deleted.ip, deleted.details) == (
        root.user.id,
        None,
        {"account_id": bia.user.id, "by_admin": True},
    )
    assert events(db_session, AuditEvent.ACCOUNT_DELETION_STARTED) == []
    assert subjects(outbox, "bia@example.com") == [DELETED_SUBJECT]


def test_admin_deleted_before_the_end_leaves_no_actor(
    db_session, settings, task_context, apps, make_account
):
    root = make_account("root@example.com", is_admin=True)
    make_account("outro-admin@example.com", is_admin=True)
    bia = make_account("bia@example.com")
    apps.down.add("ethos")
    for account, actor, mode in (
        (bia, root.user.id, DeletionMode.ADMIN),
        (root, root.user.id, DeletionMode.SELF),
    ):
        with write_transaction(db_session):
            user = deletion.reload_user(db_session, account.user.id)
            start_deletion(db_session, settings, user, actor_id=actor, mode=mode)
    # O root termina primeiro; a bia depois, com o admin que a apagou já fora do banco
    apps.down.clear()
    with write_transaction(db_session):
        db_session.execute(
            update(AppTask).where(AppTask.user_id == bia.user.id).values(done_at=NOW)
        )
    deletion.continue_deletion(task_context, Mailer(settings, Outbox()), root.user.id)
    deletion.continue_deletion(task_context, Mailer(settings, Outbox()), bia.user.id)

    by_account = {
        entry.details["account_id"]: entry
        for entry in events(db_session, AuditEvent.ACCOUNT_DELETED)
    }
    assert (by_account[bia.user.id].user_id, by_account[bia.user.id].details["by_admin"]) == (
        None,
        True,
    )


def test_deleting_account_without_the_start_event_counts_as_self(
    db_session, settings, task_context
):
    user = new_user(ANA, status="deleting")
    save(db_session, user)
    outbox = Outbox()

    deletion.continue_deletion(task_context, Mailer(settings, outbox), user.id)

    [deleted] = events(db_session, AuditEvent.ACCOUNT_DELETED)
    assert deleted.details == {"account_id": user.id, "by_admin": False}
    assert subjects(outbox, ANA) == [DELETED_SUBJECT]


# --- dados que somem ---


def change_email(db_session, admin: Account, target: Account, old: str, new: str) -> None:
    with write_transaction(db_session):
        audit.record(
            db_session,
            AuditEvent.EMAIL_CHANGED,
            user_id=admin.user.id,
            ip="203.0.113.7",
            details={"target_user_id": target.user.id, "old_email": old, "new_email": new},
        )


@pytest.fixture
def scene(db_session, make_account, outbox, client) -> Account:
    """Ana trocou de email pelo suporte (ANA_OLD -> ANA) e tem um código velho do email antigo."""
    root = make_account("root@example.com", is_admin=True)
    ana = make_account(ANA)
    make_account("bia@example.com")
    change_email(db_session, root, ana, ANA_OLD, ANA)
    with time_machine.travel(datetime.now(UTC) - timedelta(hours=2), tick=False):
        client.post("/auth/code/request", json={"email": ANA_OLD})
    return ana


def test_email_change_before_the_deletion_leaves_no_email_in_the_audit(
    client, outbox, db_session, scene
):
    assert delete_me(client, scene, ask_code(client, outbox, scene)).status_code == 204

    [changed] = events(db_session, AuditEvent.EMAIL_CHANGED)
    # A ação do admin fica, sem os emails e sem o IP; o id da conta alvo fica
    assert changed.details == {
        "target_user_id": scene.user.id,
        "old_email": None,
        "new_email": None,
    }
    assert changed.ip is None
    texts = [str(entry.details) for entry in db_session.scalars(select(AuditLog))]
    assert not any(ANA in text or ANA_OLD in text for text in texts)


def _database_bytes(path: Path) -> bytes:
    """O arquivo do banco e o WAL, depois de VACUUM e checkpoint (sem páginas livres)."""
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("VACUUM")
        busy, _, _ = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        assert busy == 0
    wal = path.with_name(path.name + "-wal")
    return path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")


def test_no_email_of_the_user_is_left_in_the_database_file(
    client, outbox, db_session, engine, database, scene
):
    code = ask_code(client, outbox, scene)
    db_session.close()
    before = _database_bytes(database).lower()
    # Controle: a busca acha os emails antes da exclusão
    assert ANA.encode() in before
    assert ANA_OLD.encode() in before

    assert delete_me(client, scene, code).status_code == 204

    engine.dispose()
    after = _database_bytes(database).lower()
    assert ANA.encode() not in after
    assert ANA_OLD.encode() not in after
    # Os dos outros continuam
    assert b"bia@example.com" in after
    assert b"root@example.com" in after


def test_old_email_that_belongs_to_another_account_keeps_its_codes(
    client, outbox, db_session, make_account, scene
):
    # O email antigo da Ana virou de outra pessoa, que pediu um código
    make_account(ANA_OLD)
    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=2), tick=False):
        client.post("/auth/code/request", json={"email": ANA_OLD})
    code = ask_code(client, outbox, scene)

    assert delete_me(client, scene, code).status_code == 204

    assert count(db_session, LoginCode, LoginCode.email == ANA_OLD) == 2


def test_audit_already_anonymized_by_an_earlier_deletion(
    client, outbox, db_session, settings, task_context, scene
):
    # O admin que trocou o email foi apagado antes: o email_changed já perdeu os emails
    [changed] = events(db_session, AuditEvent.EMAIL_CHANGED)
    with write_transaction(db_session):
        root = deletion.reload_user(db_session, changed.user_id)
        root.is_admin = False
        start_deletion(db_session, settings, root, actor_id=root.id, mode=DeletionMode.SELF)
    deletion.continue_deletion(task_context, Mailer(settings, Outbox()), changed.user_id)
    assert events(db_session, AuditEvent.EMAIL_CHANGED)[0].details["old_email"] is None

    assert delete_me(client, scene, ask_code(client, outbox, scene)).status_code == 204

    assert reload(db_session, scene.user.id) is None


def test_actions_of_the_account_as_admin_lose_actor_and_ip(
    client, outbox, db_session, make_account
):
    ana = make_account(ANA, is_admin=True)
    make_account("root@example.com", is_admin=True)
    bia = make_account("bia@example.com")
    with write_transaction(db_session):
        audit.record(
            db_session,
            AuditEvent.USER_BLOCKED,
            user_id=ana.user.id,
            ip="203.0.113.7",
            details={"target_user_id": bia.user.id, "sessions": 1},
        )

    assert delete_me(client, ana, ask_code(client, outbox, ana)).status_code == 204

    [blocked] = events(db_session, AuditEvent.USER_BLOCKED)
    assert (blocked.user_id, blocked.ip, blocked.details) == (
        None,
        None,
        {"target_user_id": bia.user.id, "sessions": 1},
    )


def test_without_emails():
    value = {"a": "x@y.z", "b": ["ok", "c@d.e", {"e": "f@g.h"}], "n": 1, "none": None}
    assert deletion.without_emails(value) == {
        "a": None,
        "b": ["ok", None, {"e": None}],
        "n": 1,
        "none": None,
    }


# --- transação e emails ---


def _snapshot(path: Path) -> dict[str, list[tuple]]:
    with closing(sqlite3.connect(path)) as connection:
        tables = [
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        return {
            table: sorted(connection.execute(f"SELECT * FROM {table}").fetchall(), key=repr)  # noqa: S608
            for table in tables
        }


@pytest.mark.parametrize("step", ["request_tasks", "record_started"])
def test_failure_in_step_1_changes_nothing_and_sends_nothing(
    settings, database, make_client, outbox, apps, monkeypatch, ana, caplog, step
):
    client = make_client(
        create_app(settings, mail_backend=outbox, app_transport=apps.transport),
        raise_server_exceptions=False,
    )
    code = ask_code(client, outbox, ana)
    outbox.messages.clear()
    before = _snapshot(database)

    def boom(*_args, **_kwargs):
        raise RuntimeError("falha no meio")

    monkeypatch.setattr(deletion, step, boom)
    response = delete_me(client, ana, code)

    assert response.status_code == 500
    assert _snapshot(database) == before
    assert outbox.messages == []
    assert apps.calls == []
    assert "excluída" not in caplog.text
    # A conta continua funcionando
    assert client.get("/me", headers=ana.headers).status_code == 200


def test_account_email_refused_by_the_cap_alerts_support(
    make_settings, db_session, make_client, outbox, apps, make_account
):
    settings = make_settings(
        max_emails_per_hour=1,
        max_emails_per_day=1,
        mail_reserved_for_codes_per_hour=0,
        mail_reserved_for_codes_per_day=0,
    )
    client = make_client(create_app(settings, mail_backend=outbox, app_transport=apps.transport))
    ana = make_account(ANA)

    assert delete_me(client, ana, ask_code(client, outbox, ana)).status_code == 204

    # O código coube no teto; o "conta excluída" não: no lugar dele, o aviso ao suporte
    assert subjects(outbox, ANA) == ["Código para excluir sua conta do manasomali.com"]
    assert subjects(outbox, "suporte@example.com") == [
        "manasomali.com: teto de envio de email atingido"
    ]
    assert reload(db_session, ana.user.id) is None
    [alert] = events(db_session, AuditEvent.SEND_CAP_REACHED)
    assert alert.details == {"window": "hour", "limit": 1, "kind": "account"}


# --- resposta, sessão e log ---


def test_response_clears_the_cookie_and_ends_the_session(client, outbox, ana):
    code = ask_code(client, outbox, ana)

    response = delete_me(client, ana, code)

    assert response.status_code == 204
    assert response.content == b""
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "Max-Age=0" in set_cookie
    assert client.get("/me", headers=ana.headers).status_code == 401
    assert delete_me(client, ana, code).status_code == 401


def test_log_has_only_the_numeric_id(client, outbox, ana, caplog):
    code = ask_code(client, outbox, ana)

    with caplog.at_level(logging.DEBUG):
        assert delete_me(client, ana, code).status_code == 204

    assert f"conta {ana.user.id} excluída" in caplog.messages
    for sensitive in (ANA, code):
        assert sensitive not in caplog.text


def test_requires_session(client):
    assert client.post("/me/delete/request").json() == UNAUTHORIZED
    response = client.request("DELETE", "/me", json={"code": "123456"})
    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)


@pytest.mark.parametrize(
    "body",
    [{}, {"code": "12345"}, {"code": "1234567"}, {"code": "12345a"}, {"code": 123456}],
)
def test_invalid_body(client, ana, body):
    response = client.request("DELETE", "/me", json=body, headers=ana.headers)

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_extra_field_is_refused(client, ana):
    body = {"code": "123456", "user_id": 1}
    response = client.request("DELETE", "/me", json=body, headers=ana.headers)

    assert response.json() == {"error": "validation_error", "field": "user_id"}


def test_works_with_terms_pending(client, outbox, make_account):
    ana = make_account(ANA, terms_version="2020-01-01")

    assert delete_me(client, ana, ask_code(client, outbox, ana)).status_code == 204


def test_needs_the_origin(client, outbox, ana):
    code = ask_code(client, outbox, ana)

    response = client.request(
        "DELETE", "/me", json={"code": code}, headers=ana.headers | {"Origin": "https://x.example"}
    )

    assert response.status_code == 403


# --- código ---


def test_wrong_code_is_refused_and_counted(client, outbox, db_session, ana):
    code = ask_code(client, outbox, ana)
    wrong = "000000" if code != "000000" else "111111"

    response = delete_me(client, ana, wrong)

    assert (response.status_code, response.json()) == (400, INVALID_CODE)
    assert db_session.scalar(select(LoginCode.attempts)) == 1
    assert reload(db_session, ana.user.id).status == "active"


def test_attempts_run_out(client, outbox, ana):
    code = ask_code(client, outbox, ana)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert delete_me(client, ana, wrong).status_code == 400

    assert delete_me(client, ana, code).json() == INVALID_CODE


def test_expired_code_is_refused(client, outbox, ana):
    code = ask_code(client, outbox, ana)

    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=10, seconds=1)):
        assert delete_me(client, ana, code).json() == INVALID_CODE


def test_login_code_is_refused(client, outbox, ana):
    client.post("/auth/code/request", json={"email": ANA})
    login_code = code_in(outbox.to(ANA)[-1])

    assert delete_me(client, ana, login_code).json() == INVALID_CODE


def test_parallel_deletes_with_the_same_code(client, outbox, settings, engine, db_session, ana):
    code = ask_code(client, outbox, ana)
    factory = create_session_factory(engine)
    barrier = threading.Barrier(2, timeout=10)

    def attempt(_index: int):
        with factory() as session:
            barrier.wait()
            try:
                return deletion.delete_own_account(
                    session, settings, user_id=ana.user.id, code=code
                )
            except ApiError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, range(2)))

    assert sorted(map(str, results)) == ["None", ErrorCode.UNAUTHORIZED.value]
    assert len(events(db_session, AuditEvent.ACCOUNT_DELETION_STARTED)) == 1
    assert VerifyFailure.INVALID_CODE not in results


# --- último admin ---


def test_last_admin_cannot_ask_for_the_code(client, outbox, make_account):
    ana = make_account(ANA, is_admin=True)
    # Outros admins, mas bloqueado ou em exclusão: não contam
    make_account("root@example.com", is_admin=True, is_active=False)
    make_account("velho@example.com", is_admin=True, status="deleting")

    response = client.post("/me/delete/request", headers=ana.headers)

    assert (response.status_code, response.json()) == (409, LAST_ADMIN)
    assert outbox.messages == []


def test_last_admin_cannot_delete_with_a_code(client, outbox, db_session, make_account):
    ana = make_account(ANA, is_admin=True)
    root = make_account("root@example.com", is_admin=True)
    code = ask_code(client, outbox, ana)
    with write_transaction(db_session):
        db_session.get(User, root.user.id).is_admin = False

    response = delete_me(client, ana, code)

    assert (response.status_code, response.json()) == (409, LAST_ADMIN)
    assert reload(db_session, ana.user.id).status == "active"
    # O código não foi gasto
    assert db_session.scalar(select(LoginCode.attempts)) == 0


def test_admin_can_delete_when_another_admin_exists(client, outbox, make_account):
    ana = make_account(ANA, is_admin=True)
    make_account("root@example.com", is_admin=True)

    assert delete_me(client, ana, ask_code(client, outbox, ana)).status_code == 204


def test_start_deletion_refuses_the_last_admin(db_session, settings, make_account):
    ana = make_account(ANA, is_admin=True)

    user = deletion.reload_user(db_session, ana.user.id)
    with pytest.raises(ApiError) as raised, write_transaction(db_session):
        start_deletion(db_session, settings, user, actor_id=None, mode=DeletionMode.REAPPLIED)

    assert raised.value.code is ErrorCode.LAST_ADMIN
    assert reload(db_session, ana.user.id).status == "active"


def test_blocked_admin_is_not_the_last_admin(db_session, make_account):
    ana = make_account(ANA, is_admin=True, is_active=False)

    assert deletion.is_last_admin(db_session, ana.user) is False


def test_blocked_in_the_middle_cannot_ask_for_the_code(db_session, settings, make_account):
    ana = make_account(ANA)
    with write_transaction(db_session):
        db_session.get(User, ana.user.id).is_active = False

    with pytest.raises(ApiError) as raised:
        deletion.request_account_deletion(db_session, settings, user_id=ana.user.id, ip=None)

    assert raised.value.code is ErrorCode.UNAUTHORIZED


def test_account_created_with_terms_is_not_affected(client, outbox, db_session, make_account):
    # Outra conta não perde nada com a exclusão da Ana
    ana = make_account(ANA)
    bia = make_account("bia@example.com", terms_version=TERMS_VERSION)

    assert delete_me(client, ana, ask_code(client, outbox, ana)).status_code == 204

    assert client.get("/me", headers=bia.headers).status_code == 200
    assert count(db_session, UserSession) == 1
