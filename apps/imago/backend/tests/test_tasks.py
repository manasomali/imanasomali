"""Tarefas para as aplicações (`app/internal/tasks.py`), o `run-tasks` e o refresh do
`PATCH /me` (ETH-59)."""

import logging
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
import time_machine
from sqlalchemy import select, update

from app.cli import main
from app.db import create_session_factory, write_transaction
from app.internal import tasks
from app.internal.tasks import (
    CALL_TIMEOUT_SECONDS,
    MAX_REFRESH_ROUNDS,
    RunSummary,
    TaskContext,
    TaskOutcome,
    cancel_tasks,
    request_tasks,
    run_pending,
    run_task,
)
from app.main import create_app
from app.models import AppTask, TaskAction, User
from app.terms import TERMS_VERSION
from tests.apps_helpers import Call
from tests.auth_helpers import Account, cookie, open_session
from tests.factories import count, new_user, save
from tests.internal_helpers import ENGRAFI_TOKEN, ETHOS_TOKEN
from tests.test_cli import env_for

NOW = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
ANA = "ana@example.com"
REFRESH = TaskAction.REFRESH
DELETE = TaskAction.DELETE


@pytest.fixture
def ana(make_account) -> Account:
    return make_account(ANA)


def create(db_session, settings, user_id: int, action: TaskAction = REFRESH) -> int:
    with write_transaction(db_session):
        return request_tasks(db_session, settings, user_id=user_id, action=action)


def all_tasks(db_session) -> list[AppTask]:
    db_session.rollback()
    return list(
        db_session.scalars(
            select(AppTask).order_by(AppTask.id).execution_options(populate_existing=True)
        )
    )


def set_profile(db_session, user_id: int, **values) -> None:
    with write_transaction(db_session):
        db_session.execute(update(User).where(User.id == user_id).values(**values))


# --- criação ---


def test_one_task_per_app_and_at_most_one_pending(db_session, settings, ana):
    assert create(db_session, settings, ana.user.id) == 2
    # De novo, com as duas pendentes: nada novo
    assert create(db_session, settings, ana.user.id) == 0
    # Outra ação é outra tarefa
    assert create(db_session, settings, ana.user.id, DELETE) == 2

    rows = [(task.app, task.action, task.done_at) for task in all_tasks(db_session)]
    assert rows == [
        ("ethos", "refresh", None),
        ("engrafi", "refresh", None),
        ("ethos", "delete", None),
        ("engrafi", "delete", None),
    ]


def test_a_done_task_does_not_block_a_new_one(db_session, settings, task_context, ana):
    create(db_session, settings, ana.user.id)
    run_pending(task_context)

    assert create(db_session, settings, ana.user.id) == 2
    assert count(db_session, AppTask) == 4


def test_without_apps_nothing_is_created(make_settings, db_session, ana):
    settings = make_settings(imago_apps="")

    assert create(db_session, settings, ana.user.id) == 0
    assert count(db_session, AppTask) == 0


def test_request_and_cancel_need_a_write_transaction(db_session, settings, ana):
    with pytest.raises(RuntimeError, match="fora de write_transaction"):
        request_tasks(db_session, settings, user_id=ana.user.id, action=REFRESH)
    with pytest.raises(RuntimeError, match="fora de write_transaction"):
        cancel_tasks(db_session, user_id=ana.user.id, action=REFRESH)


def test_cancel_removes_only_the_pending_tasks_of_the_action(
    db_session, settings, task_context, ana
):
    create(db_session, settings, ana.user.id)
    run_pending(task_context)
    create(db_session, settings, ana.user.id)
    create(db_session, settings, ana.user.id, DELETE)

    with write_transaction(db_session):
        assert cancel_tasks(db_session, user_id=ana.user.id, action=REFRESH) == 2

    rows = [(task.action, task.done_at is None) for task in all_tasks(db_session)]
    assert rows == [("refresh", False), ("refresh", False), ("delete", True), ("delete", True)]


# --- execução ---


def test_success_marks_done_with_each_app_token(db_session, settings, task_context, apps, ana):
    create(db_session, settings, ana.user.id)

    with time_machine.travel(NOW, tick=False):
        summary = run_pending(task_context)

    assert summary == RunSummary(done=2)
    assert summary.tried == 2
    body = {"email": ANA, "locale": "pt", "timezone": "America/Sao_Paulo"}
    assert apps.calls == [
        Call("ethos", "refresh", ana.user.id, ETHOS_TOKEN, body),
        Call("engrafi", "refresh", ana.user.id, ENGRAFI_TOKEN, body),
    ]
    for task in all_tasks(db_session):
        assert (task.done_at, task.last_attempt_at, task.attempts) == (NOW, NOW, 0)


def test_delete_has_no_body(db_session, settings, task_context, apps, ana):
    create(db_session, settings, ana.user.id, DELETE)

    run_pending(task_context)

    assert [(call.app, call.action, call.body) for call in apps.calls] == [
        ("ethos", "delete", None),
        ("engrafi", "delete", None),
    ]


def test_one_app_down_does_not_stop_the_other(db_session, settings, task_context, apps, ana):
    apps.down.add("ethos")
    create(db_session, settings, ana.user.id)

    with time_machine.travel(NOW, tick=False):
        summary = run_pending(task_context)

    assert summary == RunSummary(done=1, failed=1)
    assert apps.of("refresh") == [("ethos", ana.user.id), ("engrafi", ana.user.id)]
    ethos, engrafi = all_tasks(db_session)
    assert (ethos.done_at, ethos.attempts, ethos.last_attempt_at) == (None, 1, NOW)
    assert (engrafi.done_at, engrafi.attempts) == (NOW, 0)


@pytest.mark.parametrize("status", [201, 204, 302, 401, 404, 422, 500, 503])
def test_any_status_but_200_is_a_failure(db_session, settings, task_context, apps, ana, status):
    apps.status["ethos"] = status
    create(db_session, settings, ana.user.id)

    assert run_pending(task_context) == RunSummary(done=1, failed=1)


@pytest.mark.parametrize(
    "error", [httpx2.ReadTimeout, httpx2.ConnectTimeout, httpx2.RemoteProtocolError]
)
def test_timeouts_and_protocol_errors_are_failures(
    db_session, settings, task_context, apps, ana, error
):
    def fail(call: Call) -> None:
        if call.app == "engrafi":
            raise error("falhou")

    apps.before_reply = fail
    create(db_session, settings, ana.user.id)

    assert run_pending(task_context) == RunSummary(done=1, failed=1)


def test_the_client_has_the_timeout_and_ignores_proxies(task_context):
    with task_context.http_client() as client:
        assert client.timeout == httpx2.Timeout(CALL_TIMEOUT_SECONDS)
        assert client.trust_env is False
        assert client.follow_redirects is False


def test_failures_are_logged_and_the_fifth_is_an_error(
    db_session, settings, task_context, apps, ana, caplog
):
    apps.down.add("ethos")
    create(db_session, settings, ana.user.id)
    caplog.set_level(logging.WARNING, logger="app.internal.tasks")

    for hour in range(5):
        with time_machine.travel(NOW + timedelta(hours=hour), tick=False):
            run_pending(task_context)

    records = [(r.levelno, r.getMessage()) for r in caplog.records]
    line = f"tarefa refresh de ethos para a conta {ana.user.id} falhou (ConnectError)"
    assert records == [
        (logging.WARNING, f"{line}; 1 falhas seguidas"),
        (logging.WARNING, f"{line}; 2 falhas seguidas"),
        (logging.WARNING, f"{line}; 3 falhas seguidas"),
        (logging.WARNING, f"{line}; 4 falhas seguidas"),
        (logging.ERROR, f"{line}; 5 falhas seguidas"),
    ]
    assert ANA not in caplog.text
    ethos = all_tasks(db_session)[0]
    assert (ethos.attempts, ethos.last_attempt_at) == (5, NOW + timedelta(hours=4))

    # Quando a aplicação volta, a tarefa termina
    apps.down.clear()
    assert run_pending(task_context) == RunSummary(done=1)


def test_refresh_sends_the_values_at_call_time(db_session, settings, task_context, apps, ana):
    create(db_session, settings, ana.user.id)
    set_profile(db_session, ana.user.id, timezone="Asia/Tokyo", locale="en", email="a@example.org")

    run_pending(task_context)

    assert {tuple(call.body.values()) for call in apps.calls} == {
        ("a@example.org", "en", "Asia/Tokyo")
    }


def test_a_change_during_the_call_is_sent_again(db_session, settings, task_context, apps, ana):
    changed = []

    def change_once(call: Call) -> None:
        if call.app == "ethos" and not changed:
            changed.append(call)
            set_profile(db_session, ana.user.id, timezone="UTC")

    apps.before_reply = change_once
    create(db_session, settings, ana.user.id)

    assert run_pending(task_context) == RunSummary(done=2)

    ethos_calls = [call.body["timezone"] for call in apps.calls if call.app == "ethos"]
    assert ethos_calls == ["America/Sao_Paulo", "UTC"]
    assert all(task.done_at is not None for task in all_tasks(db_session))


def test_a_profile_that_keeps_changing_stays_pending(db_session, settings, task_context, apps, ana):
    zones = iter(["UTC", "Asia/Tokyo", "Europe/Lisbon", "America/Recife"])

    def change_always(call: Call) -> None:
        if call.app == "ethos":
            set_profile(db_session, ana.user.id, timezone=next(zones))

    apps.before_reply = change_always
    create(db_session, settings, ana.user.id)

    assert run_pending(task_context) == RunSummary(done=1, pending=1)

    assert len(apps.of("refresh")) == MAX_REFRESH_ROUNDS + 1
    ethos = all_tasks(db_session)[0]
    # Não é falha: a aplicação respondeu, só a conta mudou de novo
    assert (ethos.done_at, ethos.attempts) == (None, 0)


def test_a_task_running_in_another_thread_is_busy(db_session, settings, task_context, apps, ana):
    create(db_session, settings, ana.user.id)
    first = all_tasks(db_session)[0].id
    assert tasks._claim(first)
    try:
        assert run_pending(task_context) == RunSummary(done=1, busy=1)
    finally:
        tasks._release(first)

    assert apps.of("refresh") == [("engrafi", ana.user.id)]
    assert run_pending(task_context) == RunSummary(done=1)


def test_done_or_deleted_tasks_are_gone(db_session, settings, task_context, apps, ana):
    create(db_session, settings, ana.user.id)
    ethos, engrafi = (task.id for task in all_tasks(db_session))
    run_pending(task_context)

    with task_context.http_client() as client:
        assert run_task(task_context, client, ethos) == TaskOutcome.GONE
        assert run_task(task_context, client, engrafi + 1000) == TaskOutcome.GONE
    assert len(apps.calls) == 2


def test_task_deleted_during_the_call_is_gone(db_session, settings, task_context, apps, ana):
    def cancel(_call: Call) -> None:
        with write_transaction(db_session):
            cancel_tasks(db_session, user_id=ana.user.id, action=REFRESH)

    apps.before_reply = cancel
    create(db_session, settings, ana.user.id)

    assert run_pending(task_context) == RunSummary(gone=2)
    assert count(db_session, AppTask) == 0


def test_refresh_of_an_account_being_deleted_is_dropped(
    db_session, settings, task_context, apps, ana
):
    create(db_session, settings, ana.user.id)
    set_profile(db_session, ana.user.id, status="deleting")

    with time_machine.travel(NOW, tick=False):
        assert run_pending(task_context) == RunSummary(gone=2)

    assert apps.calls == []
    assert [task.done_at for task in all_tasks(db_session)] == [NOW, NOW]


def test_refresh_of_a_blocked_account_is_sent(db_session, settings, task_context, apps, ana):
    create(db_session, settings, ana.user.id)
    set_profile(db_session, ana.user.id, is_active=False)

    assert run_pending(task_context) == RunSummary(done=2)


def test_app_removed_from_imago_apps_fails_without_calling(
    make_settings, db_session, settings, engine, apps, ana, caplog
):
    create(db_session, settings, ana.user.id)
    only_ethos = make_settings(imago_apps="ethos=http://127.0.0.1:3001")
    context = TaskContext(only_ethos, create_session_factory(engine), apps.transport)

    assert run_pending(context) == RunSummary(done=1, failed=1)

    assert apps.of("refresh") == [("ethos", ana.user.id)]
    assert "engrafi para a conta" in caplog.text
    assert "(aplicação fora do IMAGO_APPS)" in caplog.text
    assert all_tasks(db_session)[1].attempts == 1


def test_run_pending_filters_by_user_and_action(
    db_session, settings, task_context, apps, ana, make_account
):
    bia = make_account("bia@example.com")
    create(db_session, settings, ana.user.id)
    create(db_session, settings, bia.user.id)
    create(db_session, settings, bia.user.id, DELETE)

    assert run_pending(task_context, user_id=bia.user.id, action=REFRESH) == RunSummary(done=2)
    assert {(call.user_id, call.action) for call in apps.calls} == {(bia.user.id, "refresh")}

    assert run_pending(task_context, user_id=bia.user.id) == RunSummary(done=2)
    assert run_pending(task_context) == RunSummary(done=2)
    assert run_pending(task_context) == RunSummary()


def test_background_run_never_raises(task_context, monkeypatch, caplog):
    def broken(*_args, **_kwargs):
        raise RuntimeError("segredo@example.com")

    monkeypatch.setattr(tasks, "run_pending", broken)

    tasks.run_in_background(task_context, user_id=42, action=REFRESH)

    assert caplog.messages == [
        "tarefas refresh da conta 42 não rodaram (RuntimeError); ficam para o run-tasks"
    ]
    assert "segredo" not in caplog.text


# --- PATCH /me ---


def test_patch_me_creates_and_runs_one_refresh_per_app(client, db_session, apps, ana):
    response = client.patch("/me", json={"timezone": "Asia/Tokyo"}, headers=ana.headers)

    assert response.status_code == 200
    body = {"email": ANA, "locale": "pt", "timezone": "Asia/Tokyo"}
    assert [(call.app, call.action, call.body) for call in apps.calls] == [
        ("ethos", "refresh", body),
        ("engrafi", "refresh", body),
    ]
    assert all(task.done_at is not None for task in all_tasks(db_session))


def test_patch_me_without_changes_creates_nothing(client, db_session, apps, ana):
    response = client.patch("/me", json={"locale": "pt"}, headers=ana.headers)

    assert response.status_code == 200
    assert apps.calls == []
    assert count(db_session, AppTask) == 0


def test_two_patches_with_the_app_down_leave_one_task(client, db_session, task_context, apps, ana):
    apps.down.add("ethos")

    with time_machine.travel(NOW, tick=False):
        client.patch("/me", json={"timezone": "Asia/Tokyo"}, headers=ana.headers)
    with time_machine.travel(NOW + timedelta(minutes=1), tick=False):
        client.patch("/me", json={"locale": "en"}, headers=ana.headers)

    pending = [task for task in all_tasks(db_session) if task.done_at is None]
    assert [(task.app, task.attempts) for task in pending] == [("ethos", 2)]
    assert count(db_session, AppTask, AppTask.app == "engrafi") == 2

    # O ethos volta: a tarefa que falhou manda os valores de agora, não os da primeira mudança
    apps.down.clear()
    apps.calls.clear()
    assert run_pending(task_context) == RunSummary(done=1)
    assert apps.calls[0].body == {"email": ANA, "locale": "en", "timezone": "Asia/Tokyo"}


def test_patch_me_without_apps_schedules_nothing(make_settings, db_session, make_client, apps):
    # Mesmo arquivo de banco do `db_session` (make_settings usa o mesmo caminho)
    client = make_client(create_app(make_settings(imago_apps=""), app_transport=apps.transport))
    user = new_user(ANA, terms_version=TERMS_VERSION)
    save(db_session, user)

    response = client.patch(
        "/me", json={"timezone": "UTC"}, headers=cookie(open_session(db_session, user))
    )

    assert response.status_code == 200
    assert apps.calls == []
    assert count(db_session, AppTask) == 0


# --- run-tasks ---


@pytest.fixture
def env(settings, database) -> dict[str, str]:
    return env_for(settings)


def test_run_tasks_exits_0_even_with_failures(db_session, settings, env, apps, ana, capsys):
    apps.down.add("engrafi")
    create(db_session, settings, ana.user.id)

    assert main(["run-tasks"], env, app_transport=apps.transport) == 0

    assert capsys.readouterr().out == (
        "run-tasks: 2 tarefas tentadas, 1 concluídas, 1 falhas, 0 ficaram para depois\n"
    )


def test_run_tasks_with_nothing_to_do(env, apps, capsys):
    assert main(["run-tasks"], env, app_transport=apps.transport) == 0

    assert capsys.readouterr().out.startswith("run-tasks: 0 tarefas tentadas")


def test_run_tasks_exits_1_when_the_database_fails(env, apps, tmp_path, capsys):
    # Um arquivo que existe, mas sem as tabelas: o erro é do banco, não de uma tarefa
    empty = tmp_path / "vazio.db"
    empty.write_bytes(b"")
    env["DATABASE_PATH"] = str(empty)

    assert main(["run-tasks"], env, app_transport=apps.transport) == 1

    err = capsys.readouterr().err
    assert err.startswith("erro: falha no banco de dados (OperationalError em app/")
