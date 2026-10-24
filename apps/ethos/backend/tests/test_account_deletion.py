"""Exclusão de conta (ETH-27): `POST /auth/me/delete/request`, `DELETE /auth/me` e o serviço
`app/auth/deletion.py`, também usado pelo admin (ETH-28)."""

import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import time_machine
from sqlalchemy import select, text

from app import audit
from app.audit import AuditEvent
from app.auth import deletion
from app.auth.cookies import SESSION_COOKIE_NAME
from app.auth.deletion import AccountDeletion, delete_account, delete_own_account, without_emails
from app.auth.security import hash_secret
from app.auth.service import MAX_CODE_ATTEMPTS, VerifyFailure
from app.db import create_session_factory, write_transaction
from app.errors import ApiError, ErrorCode
from app.main import create_app
from app.models import (
    Alert,
    AuditLog,
    Banner,
    CodePurpose,
    Habit,
    HabitInvite,
    HabitMember,
    HabitPause,
    LoginCode,
    Mark,
    User,
    UserSession,
)
from tests.auth_helpers import Outbox, code_in
from tests.factories import (
    count,
    new_alert,
    new_habit,
    new_invite,
    new_mark,
    new_member,
    new_pause,
    save,
)
from tests.habit_helpers import Account

ANA = "ana@example.com"
# Email antigo da Ana, de antes de uma troca feita pelo suporte (está no audit_log do root)
ANA_OLD = "ana.old@example.com"
ANA_IP = "203.0.113.7"
ROOT_IP = "198.51.100.1"
T = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
INVALID_CODE = {"error": "invalid_code", "field": "code"}
LAST_ADMIN = {"error": "last_admin", "field": None}


@pytest.fixture
def client(settings, database, make_client, outbox):
    return make_client(create_app(settings, mail_backend=outbox))


def ask_code(client, outbox: Outbox, account: Account) -> str:
    response = client.post("/auth/me/delete/request", headers=account.headers)
    assert response.status_code == 202, response.json()
    assert response.json() == {"status": "accepted"}
    return code_in(outbox.to(account.user.email)[-1])


def delete_me(client, account: Account, code: str):
    return client.request("DELETE", "/auth/me", json={"code": code}, headers=account.headers)


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def record(db_session, event, *, user=None, habit=None, ip=None, details=None) -> AuditLog:
    with write_transaction(db_session):
        return audit.record(
            db_session,
            event,
            user_id=None if user is None else user.id,
            habit_id=None if habit is None else habit.id,
            ip=ip,
            details=details,
        )


def rows(db_session, model, *order_by):
    db_session.rollback()
    query = select(model).order_by(*order_by).execution_options(populate_existing=True)
    return list(db_session.scalars(query))


@dataclass
class Scene:
    ana: Account
    root: Account
    bia: Account
    caio: Account
    # Hábitos da Ana
    reading: Habit
    running: Habit
    # Hábitos dos outros
    piano: Habit
    chess: Habit
    yoga: Habit
    ana_mark_on_piano: Mark
    bia_mark_on_piano: Mark
    logs: dict[str, AuditLog]


def build_scene(db_session, make_account) -> Scene:
    """Ana (admin, a ser apagada) com hábitos próprios compartilhados, participação e marcações em
    hábitos de outras pessoas, convites, alertas, códigos, banner e auditoria de todo tipo."""
    ana = make_account(ANA, is_admin=True)
    root = make_account("root@example.com", is_admin=True)
    bia = make_account("bia@example.com", locale="en")
    caio = make_account("caio@example.com")
    reading = new_habit(ana.user, name="Leitura")
    running = new_habit(ana.user, name="Corrida")
    piano = new_habit(bia.user, name="Piano")
    chess = new_habit(bia.user, name="Xadrez")
    yoga = new_habit(caio.user, name="Yoga")
    save(db_session, reading, running, piano, chess, yoga)
    ana_mark_on_piano = new_mark(piano, T, user_id=ana.user.id, note="nota da Ana")
    bia_mark_on_piano = new_mark(piano, T, user_id=bia.user.id)
    save(
        db_session,
        new_member(reading, bia.user, "editor"),
        new_member(reading, caio.user, "viewer"),
        new_member(running, bia.user, "viewer"),
        new_member(piano, ana.user, "editor"),
        new_member(piano, caio.user, "viewer"),
        new_mark(reading, T, user_id=ana.user.id),
        new_mark(reading, T, user_id=bia.user.id),
        ana_mark_on_piano,
        bia_mark_on_piano,
        new_pause(reading, T - timedelta(days=3), T - timedelta(days=2)),
        new_alert(reading, ana.user),
        new_alert(reading, bia.user),
        new_alert(piano, ana.user),
        new_alert(piano, bia.user),
        # Convite enviado pela Ana (some com o hábito)
        new_invite(reading, "dan@example.com"),
        # Convites recebidos: para a conta e só para o email (feito antes da conta existir)
        new_invite(chess, ANA, invited_user_id=ana.user.id),
        new_invite(yoga, ANA),
        # Convite de outra pessoa, que fica
        new_invite(chess, "eva@example.com"),
        Banner(
            text_pt="Aviso",
            text_en="Notice",
            starts_at=T,
            ends_at=T + timedelta(days=1),
            created_by=ana.user.id,
        ),
    )
    a, r, b = ana.user, root.user, bia.user
    # Agora, e não em T: a limpeza ao pedir um código apaga os vencidos há mais de 1 dia
    now = datetime.now(UTC)
    save(
        db_session,
        *(
            LoginCode(
                email=email,
                purpose=CodePurpose.LOGIN.value,
                code_hash=hash_secret("111111"),
                expires_at=now - timedelta(minutes=5),
                created_at=now - timedelta(minutes=15),
            )
            for email in (ANA, "bia@example.com")
        ),
    )
    logs = {
        # Da conta: apagados
        "ana_login": record(db_session, AuditEvent.LOGIN, user=a, ip=ANA_IP),
        "ana_profile": record(db_session, AuditEvent.PROFILE_UPDATED, user=a, ip=ANA_IP),
        "ana_terms": record(db_session, AuditEvent.TERMS_ACCEPTED, user=a, ip=ANA_IP),
        "ana_admin": record(db_session, AuditEvent.ADMIN_CREATED, user=a, details={"via": "cli"}),
        "ana_old_habit": record(
            db_session, AuditEvent.HABIT_DELETED, user=a, ip=ANA_IP, details={"habit_id": 999}
        ),
        # Dos hábitos dela: apagados no CASCADE
        "reading_created": record(db_session, AuditEvent.HABIT_CREATED, user=a, habit=reading),
        "bia_on_reading": record(
            db_session,
            AuditEvent.MARK_CREATED,
            user=b,
            habit=reading,
            details={"mark_id": 1, "author_id": b.id},
        ),
        # Em hábitos de outras pessoas: anonimizados
        "ana_mark": record(
            db_session,
            AuditEvent.MARK_CREATED,
            user=a,
            habit=piano,
            ip=ANA_IP,
            details={"mark_id": ana_mark_on_piano.id, "author_id": a.id, "has_note": True},
        ),
        "bia_deleted_ana_mark": record(
            db_session,
            AuditEvent.MARK_DELETED,
            user=b,
            habit=piano,
            details={"mark_id": 12345, "author_id": a.id, "has_note": False},
        ),
        "role_changed": record(
            db_session,
            AuditEvent.MEMBER_ROLE_CHANGED,
            user=b,
            habit=piano,
            details={
                "member_id": a.id,
                "changes": [{"field": "role", "old": "viewer", "new": "editor"}],
            },
        ),
        "ana_accepted": record(
            db_session,
            AuditEvent.INVITE_ACCEPTED,
            user=a,
            habit=piano,
            ip=ANA_IP,
            details={"invite_id": 1, "role": "viewer"},
        ),
        # Ações da Ana como admin: anonimizadas, sem email
        "ana_viewed": record(
            db_session,
            AuditEvent.ADMIN_VIEWED_HABITS,
            user=a,
            ip=ANA_IP,
            details={"target_user_id": b.id},
        ),
        "ana_changed_caio": record(
            db_session,
            AuditEvent.EMAIL_CHANGED,
            user=a,
            ip=ANA_IP,
            details={
                "target_user_id": caio.user.id,
                "old_email": "caio.old@example.com",
                "new_email": "caio@example.com",
            },
        ),
        # Do root sobre a Ana: ficam, sem email
        "root_changed_ana": record(
            db_session,
            AuditEvent.EMAIL_CHANGED,
            user=r,
            ip=ROOT_IP,
            details={"target_user_id": a.id, "old_email": ANA_OLD, "new_email": ANA.upper()},
        ),
        "root_viewed_ana": record(
            db_session,
            AuditEvent.ADMIN_VIEWED_HABITS,
            user=r,
            ip=ROOT_IP,
            details={"target_user_id": a.id},
        ),
        # Cita só o email (em maiúsculas), sem o id: achada pelo texto
        "root_unblocked": record(
            db_session,
            AuditEvent.USER_UNBLOCKED,
            user=r,
            details={"contact": [ANA.upper(), "suporte"]},
        ),
        # Sem relação com a Ana: intactos (o "@" fica)
        "bia_login": record(db_session, AuditEvent.LOGIN, user=b, ip=ROOT_IP),
        "bia_updated": record(
            db_session,
            AuditEvent.HABIT_UPDATED,
            user=b,
            habit=piano,
            details={"changes": [{"field": "name", "old": "Piano", "new": "Piano @ casa"}]},
        ),
    }
    return Scene(
        ana, root, bia, caio, reading, running, piano, chess, yoga,
        ana_mark_on_piano, bia_mark_on_piano, logs,
    )  # fmt: skip


@pytest.fixture
def scene(db_session, make_account) -> Scene:
    return build_scene(db_session, make_account)


# --- estado final ---


def test_final_state_table_by_table(client, outbox, db_session, scene):
    s = scene
    ana_id = s.ana.user.id
    code = ask_code(client, outbox, s.ana)

    response = delete_me(client, s.ana, code)

    assert response.status_code == 204
    others = [s.root.user.id, s.bia.user.id, s.caio.user.id]
    assert [user.id for user in rows(db_session, User, User.id)] == others
    assert sorted({row.user_id for row in rows(db_session, UserSession)}) == others
    assert [(c.email, c.user_id) for c in rows(db_session, LoginCode)] == [
        ("bia@example.com", None)
    ]
    assert [h.id for h in rows(db_session, Habit, Habit.id)] == [s.piano.id, s.chess.id, s.yoga.id]
    assert rows(db_session, HabitPause) == []
    assert [(m.habit_id, m.user_id) for m in rows(db_session, HabitMember)] == [
        (s.piano.id, s.caio.user.id)
    ]
    assert [(i.habit_id, i.email) for i in rows(db_session, HabitInvite)] == [
        (s.chess.id, "eva@example.com")
    ]
    marks = rows(db_session, Mark, Mark.id)
    assert [(m.id, m.habit_id, m.user_id, m.note) for m in marks] == [
        (s.ana_mark_on_piano.id, s.piano.id, None, "nota da Ana"),
        (s.bia_mark_on_piano.id, s.piano.id, s.bia.user.id, None),
    ]
    assert [(a.habit_id, a.user_id) for a in rows(db_session, Alert)] == [
        (s.piano.id, s.bia.user.id)
    ]
    assert [banner.created_by for banner in rows(db_session, Banner)] == [None]

    logs = s.logs
    remaining = [
        (row.id, row.event, row.user_id, row.habit_id, row.ip, row.details)
        for row in rows(db_session, AuditLog, AuditLog.id)
    ]
    bia_id, root_id = s.bia.user.id, s.root.user.id
    mark_id = s.ana_mark_on_piano.id
    assert remaining == [
        (
            logs["ana_mark"].id,
            "mark_created",
            None,
            s.piano.id,
            None,
            {"mark_id": mark_id, "author_id": None, "has_note": True},
        ),
        (
            logs["bia_deleted_ana_mark"].id,
            "mark_deleted",
            bia_id,
            s.piano.id,
            None,
            {"mark_id": 12345, "author_id": None, "has_note": False},
        ),
        (
            logs["role_changed"].id,
            "member_role_changed",
            bia_id,
            s.piano.id,
            None,
            {"member_id": None, "changes": [{"field": "role", "old": "viewer", "new": "editor"}]},
        ),
        (
            logs["ana_accepted"].id,
            "invite_accepted",
            None,
            s.piano.id,
            None,
            {"invite_id": 1, "role": "viewer"},
        ),
        (
            logs["ana_viewed"].id,
            "admin_viewed_habits",
            None,
            None,
            None,
            {"target_user_id": bia_id},
        ),
        (
            logs["ana_changed_caio"].id,
            "email_changed",
            None,
            None,
            None,
            {"target_user_id": s.caio.user.id, "old_email": None, "new_email": None},
        ),
        (
            logs["root_changed_ana"].id,
            "email_changed",
            root_id,
            None,
            ROOT_IP,
            {"target_user_id": ana_id, "old_email": None, "new_email": None},
        ),
        (
            logs["root_viewed_ana"].id,
            "admin_viewed_habits",
            root_id,
            None,
            ROOT_IP,
            {"target_user_id": ana_id},
        ),
        (
            logs["root_unblocked"].id,
            "user_unblocked",
            root_id,
            None,
            None,
            {"contact": [None, "suporte"]},
        ),
        (logs["bia_login"].id, "login", bia_id, None, ROOT_IP, {}),
        (
            logs["bia_updated"].id,
            "habit_updated",
            bia_id,
            s.piano.id,
            None,
            {"changes": [{"field": "name", "old": "Piano", "new": "Piano @ casa"}]},
        ),
        (
            remaining[-1][0],
            "account_deleted",
            None,
            None,
            None,
            {"account_id": ana_id, "by_admin": False},
        ),
    ]


def test_history_shows_the_removed_user(client, outbox, scene):
    s = scene
    delete_me(client, s.ana, ask_code(client, outbox, s.ana))

    response = client.get(
        "/history", params={"habit_id": s.piano.id, "event": "mark_created"}, headers=s.bia.headers
    )

    [entry] = response.json()["events"]
    assert entry["author"] is None
    assert entry["details"]["author_id"] is None


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
    code = ask_code(client, outbox, scene.ana)
    db_session.close()
    before = _database_bytes(database).lower()
    # Controle: a busca acha os emails antes da exclusão
    assert ANA.encode() in before
    assert ANA_OLD.encode() in before

    assert delete_me(client, scene.ana, code).status_code == 204

    engine.dispose()
    after = _database_bytes(database).lower()
    assert ANA.encode() not in after
    assert ANA_OLD.encode() not in after
    # Os dos outros continuam
    assert b"bia@example.com" in after


# --- emails e transação ---


class CommitCheckingOutbox(Outbox):
    """Outbox que anota, a cada envio, se a conta ainda existe no banco (outra conexão)."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.account_id: int | None = None
        self.account_existed: list[bool] = []

    def send(self, message) -> None:
        if self.account_id is not None:
            with closing(sqlite3.connect(self.path)) as connection:
                query = "SELECT count(*) FROM users WHERE id = ?"
                [found] = connection.execute(query, (self.account_id,)).fetchone()
            self.account_existed.append(bool(found))
        super().send(message)


def test_emails_go_out_only_after_the_commit(settings, database, make_client, scene):
    s = scene
    outbox = CommitCheckingOutbox(database)
    client = make_client(create_app(settings, mail_backend=outbox))
    code = ask_code(client, outbox, s.ana)
    outbox.messages.clear()
    outbox.account_id = s.ana.user.id

    assert delete_me(client, s.ana, code).status_code == 204

    assert outbox.account_existed == [False, False, False]
    assert sorted(message["To"] for message in outbox.messages) == [
        ANA,
        "bia@example.com",
        "caio@example.com",
    ]
    [bia_email] = outbox.to("bia@example.com")
    bia_text = bia_email.get_body(preferencelist=("plain",)).get_content()
    assert "Leitura" in bia_text
    assert "Corrida" in bia_text
    [caio_email] = outbox.to("caio@example.com")
    caio_text = caio_email.get_body(preferencelist=("plain",)).get_content()
    assert "Leitura" in caio_text
    assert "Corrida" not in caio_text


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


@pytest.mark.parametrize("step", ["_scrub_emails", "record"])
def test_failure_in_the_middle_deletes_nothing_and_sends_nothing(
    settings, database, make_client, outbox, monkeypatch, scene, step
):
    client = make_client(create_app(settings, mail_backend=outbox), raise_server_exceptions=False)
    code = ask_code(client, outbox, scene.ana)
    outbox.messages.clear()
    before = _snapshot(database)

    def boom(*_args, **_kwargs):
        raise RuntimeError("falha no meio")

    # No meio (depois de apagar os hábitos) ou no fim (depois de apagar a conta)
    monkeypatch.setattr(deletion if step == "_scrub_emails" else deletion.audit, step, boom)
    response = delete_me(client, scene.ana, code)

    assert response.status_code == 500
    assert _snapshot(database) == before
    assert outbox.messages == []
    # A conta continua funcionando
    assert client.get("/auth/me", headers=scene.ana.headers).status_code == 200


# --- resposta, sessão e log ---


def test_response_clears_the_cookie_and_ends_the_session(client, outbox, make_account):
    ana = make_account(ANA)
    code = ask_code(client, outbox, ana)

    response = delete_me(client, ana, code)

    assert response.status_code == 204
    assert response.content == b""
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "Max-Age=0" in set_cookie
    assert client.get("/auth/me", headers=ana.headers).status_code == 401
    # A sessão já não existe: nem outro DELETE passa
    assert delete_me(client, ana, code).status_code == 401


def test_log_has_only_the_numeric_id(client, outbox, make_account, caplog):
    ana = make_account(ANA)
    code = ask_code(client, outbox, ana)

    with caplog.at_level(logging.DEBUG):
        assert delete_me(client, ana, code).status_code == 204

    assert f"conta {ana.user.id} excluída" in caplog.messages
    for sensitive in (ANA, code):
        assert sensitive not in caplog.text


def test_requires_session(client):
    assert client.post("/auth/me/delete/request").status_code == 401
    assert client.request("DELETE", "/auth/me", json={"code": "123456"}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [{}, {"code": "12345"}, {"code": "1234567"}, {"code": "12345a"}, {"code": 123456}],
)
def test_invalid_body(client, make_account, body):
    ana = make_account(ANA)

    response = client.request("DELETE", "/auth/me", json=body, headers=ana.headers)

    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "field": "code"}


def test_works_with_terms_pending(client, outbox, make_account):
    ana = make_account(ANA, terms_version="2000-01-01")
    assert client.get("/habits", headers=ana.headers).status_code == 403

    code = ask_code(client, outbox, ana)

    assert delete_me(client, ana, code).status_code == 204


def test_request_writes_the_code_and_the_event(client, outbox, db_session, make_account):
    ana = make_account(ANA)

    ask_code(client, outbox, ana)

    [message] = outbox.messages
    assert message["To"] == ANA
    [stored] = rows(db_session, LoginCode)
    assert (stored.email, stored.user_id, stored.purpose) == (ANA, ana.user.id, "delete_account")
    [event] = rows(db_session, AuditLog)
    assert (event.event, event.user_id) == ("delete_code_requested", ana.user.id)


# --- código ---


def test_wrong_code_is_refused_and_counted(client, outbox, db_session, make_account):
    ana = make_account(ANA)
    code = ask_code(client, outbox, ana)

    response = delete_me(client, ana, wrong(code))

    assert response.status_code == 400
    assert response.json() == INVALID_CODE
    assert db_session.scalar(select(LoginCode.attempts)) == 1
    assert count(db_session, User) == 1


def test_attempts_run_out(client, outbox, make_account):
    ana = make_account(ANA)
    code = ask_code(client, outbox, ana)
    for _ in range(MAX_CODE_ATTEMPTS):
        assert delete_me(client, ana, wrong(code)).json() == INVALID_CODE

    assert delete_me(client, ana, code).json() == INVALID_CODE


def test_expired_code_is_refused(client, outbox, make_account):
    ana = make_account(ANA)
    with time_machine.travel(T, tick=False) as traveller:
        code = ask_code(client, outbox, ana)
        traveller.shift(timedelta(minutes=10))

        assert delete_me(client, ana, code).json() == INVALID_CODE


def test_code_works_until_it_expires(client, outbox, make_account):
    ana = make_account(ANA)
    with time_machine.travel(T, tick=False) as traveller:
        code = ask_code(client, outbox, ana)
        traveller.shift(timedelta(minutes=10) - timedelta(microseconds=1))

        assert delete_me(client, ana, code).status_code == 204


def test_new_code_invalidates_the_previous(client, outbox, make_account):
    ana = make_account(ANA)
    with time_machine.travel(T, tick=False) as traveller:
        first = ask_code(client, outbox, ana)
        traveller.shift(timedelta(minutes=2))
        second = ask_code(client, outbox, ana)

        assert delete_me(client, ana, first).json() == INVALID_CODE
        assert delete_me(client, ana, second).status_code == 204


def test_login_code_is_refused(client, outbox, db_session, make_account):
    ana = make_account(ANA)
    assert client.post("/auth/code/request", json={"email": ANA}).status_code == 202
    login_code = code_in(outbox.to(ANA)[-1])

    assert delete_me(client, ana, login_code).json() == INVALID_CODE
    assert count(db_session, User) == 1


def test_delete_code_does_not_log_in(client, outbox, make_account):
    ana = make_account(ANA)
    code = ask_code(client, outbox, ana)

    response = client.post(
        "/auth/code/verify",
        json={"email": ANA, "code": code, "timezone": "America/Sao_Paulo", "locale": "pt"},
    )

    assert response.json() == INVALID_CODE


def test_delete_code_does_not_invalidate_the_login_code(client, outbox, make_account):
    ana = make_account(ANA)
    with time_machine.travel(T, tick=False) as traveller:
        client.post("/auth/code/request", json={"email": ANA})
        login_code = code_in(outbox.to(ANA)[-1])
        traveller.shift(timedelta(minutes=2))
        ask_code(client, outbox, ana)

        response = client.post(
            "/auth/code/verify",
            json={"email": ANA, "code": login_code, "timezone": "UTC", "locale": "pt"},
        )

    assert response.status_code == 200


def test_code_of_another_account_is_refused(db_session, make_account):
    ana = make_account(ANA)
    bia = make_account("bia@example.com")
    # Código de exclusão para o email da Ana, mas ligado a outra conta (o email mudou de dono)
    save(
        db_session,
        LoginCode(
            email=ANA,
            user_id=bia.user.id,
            purpose=CodePurpose.DELETE_ACCOUNT.value,
            code_hash=hash_secret("123456"),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
    )

    result = delete_own_account(db_session, user_id=ana.user.id, code="123456")

    assert result is VerifyFailure.INVALID_CODE
    assert db_session.scalar(select(LoginCode.attempts)) == 0


def test_same_limits_as_the_login_code(client, outbox, make_account):
    ana = make_account(ANA)
    with time_machine.travel(T, tick=False) as traveller:
        assert client.post("/auth/code/request", json={"email": ANA}).status_code == 202

        # 1 por minuto, contando os códigos de login do mesmo email
        response = client.post("/auth/me/delete/request", headers=ana.headers)
        assert response.status_code == 429
        assert response.json() == {"error": "rate_limited", "field": None}

        traveller.shift(timedelta(minutes=1))
        assert client.post("/auth/me/delete/request", headers=ana.headers).status_code == 202


def test_global_cap_counts_the_delete_codes(make_settings, database, make_client, make_account):
    outbox = Outbox()
    client = make_client(create_app(make_settings(max_code_emails_per_hour=1), mail_backend=outbox))
    ana = make_account(ANA)
    assert client.post("/auth/code/request", json={"email": "bia@example.com"}).status_code == 202

    response = client.post("/auth/me/delete/request", headers=ana.headers)

    assert response.status_code == 429
    # Só o aviso ao suporte, nenhum código para a Ana
    assert [message["To"] for message in outbox.messages] == [
        "bia@example.com",
        "suporte@example.com",
    ]


def test_parallel_deletes_with_the_same_code(client, outbox, engine, db_session, make_account):
    ana = make_account(ANA)
    code = ask_code(client, outbox, ana)
    factory = create_session_factory(engine)
    barrier = threading.Barrier(2)

    def task(_index):
        with factory() as session:
            barrier.wait()
            try:
                return delete_own_account(session, user_id=ana.user.id, code=code)
            except ApiError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(task, range(2)))

    assert sum(isinstance(result, AccountDeletion) for result in results) == 1
    assert ErrorCode.UNAUTHORIZED in results
    assert count(db_session, AuditLog, AuditLog.event == "account_deleted") == 1


# --- último admin ---


def test_last_admin_cannot_ask_for_the_code(client, outbox, make_account):
    ana = make_account(ANA, is_admin=True)
    # Outro admin, mas bloqueado: não conta
    make_account("root@example.com", is_admin=True, is_active=False)

    response = client.post("/auth/me/delete/request", headers=ana.headers)

    assert response.status_code == 409
    assert response.json() == LAST_ADMIN
    assert outbox.messages == []


def test_last_admin_cannot_delete_with_a_code(client, outbox, db_session, make_account):
    ana = make_account(ANA, is_admin=True)
    root = make_account("root@example.com", is_admin=True)
    code = ask_code(client, outbox, ana)
    # O outro admin perdeu o admin depois do pedido do código
    with write_transaction(db_session):
        db_session.get(User, root.user.id).is_admin = False

    response = delete_me(client, ana, code)

    assert response.status_code == 409
    assert response.json() == LAST_ADMIN
    assert count(db_session, User) == 2
    # O código não foi gasto
    assert db_session.scalar(select(LoginCode.attempts)) == 0


def test_admin_can_delete_when_another_admin_exists(client, outbox, make_account):
    ana = make_account(ANA, is_admin=True)
    make_account("root@example.com", is_admin=True)

    assert delete_me(client, ana, ask_code(client, outbox, ana)).status_code == 204


# --- pelo admin (serviço da ETH-28) ---


def test_admin_deletes_an_account(db_session, scene):
    s = scene

    result = delete_account(db_session, account_id=s.bia.user.id, actor_id=s.ana.user.id, ip=ANA_IP)

    assert result.account_id == s.bia.user.id
    # A Bia recebe "conta excluída"; ninguém participava dos hábitos dela além da Ana e do Caio
    assert [(email.to, type(email.email).__name__) for email in result.emails] == [
        ("bia@example.com", "AccountDeleted"),
        (ANA, "AccessLost"),
        ("caio@example.com", "AccessLost"),
    ]
    [ana_lost] = [email for email in result.emails if email.to == ANA]
    assert ana_lost.email.habit_names == ("Piano",)
    [event] = rows(db_session, AuditLog, AuditLog.id)[-1:]
    assert (event.event, event.user_id, event.ip, event.details) == (
        "account_deleted",
        s.ana.user.id,
        ANA_IP,
        {"account_id": s.bia.user.id, "by_admin": True},
    )
    assert db_session.get(User, s.bia.user.id) is None


def test_admin_deletes_a_blocked_account(db_session, make_account):
    root = make_account("root@example.com", is_admin=True)
    ana = make_account(ANA, is_active=False)

    delete_account(db_session, account_id=ana.user.id, actor_id=root.user.id, ip=None)

    assert count(db_session, User) == 1


def test_admin_deleting_itself_is_a_self_deletion(db_session, make_account):
    ana = make_account(ANA, is_admin=True)
    make_account("root@example.com", is_admin=True)

    delete_account(db_session, account_id=ana.user.id, actor_id=ana.user.id, ip=ANA_IP)

    [event] = rows(db_session, AuditLog)
    assert (event.user_id, event.ip, event.details) == (
        None,
        None,
        {"account_id": ana.user.id, "by_admin": False},
    )


def test_admin_cannot_delete_the_last_admin(db_session, make_account):
    ana = make_account(ANA, is_admin=True)
    bia = make_account("bia@example.com")

    with pytest.raises(ApiError) as caught:
        delete_account(db_session, account_id=ana.user.id, actor_id=bia.user.id, ip=None)

    assert (caught.value.status_code, caught.value.code) == (409, ErrorCode.LAST_ADMIN)
    assert count(db_session, User) == 2


def test_admin_deletes_an_account_that_does_not_exist(db_session, make_account):
    root = make_account("root@example.com", is_admin=True)

    with pytest.raises(ApiError) as caught:
        delete_account(db_session, account_id=root.user.id + 1, actor_id=root.user.id, ip=None)

    assert (caught.value.status_code, caught.value.code) == (404, ErrorCode.NOT_FOUND)


def test_blocked_in_the_middle_cannot_ask_for_the_code(db_session, settings, make_account):
    ana = make_account(ANA, is_active=False)

    with pytest.raises(ApiError) as caught:
        deletion.request_account_deletion(db_session, settings, user_id=ana.user.id, ip=None)

    assert caught.value.code is ErrorCode.UNAUTHORIZED


def test_without_emails():
    value = {
        "a": "x@y.z",
        "b": ["texto", "com @ no meio", {"c": "Ana@Example.com"}],
        "d": 1,
        "e": None,
        "f": True,
    }

    assert without_emails(value) == {
        "a": None,
        "b": ["texto", None, {"c": None}],
        "d": 1,
        "e": None,
        "f": True,
    }


def test_email_outside_ascii_is_found_in_the_details(db_session, make_account):
    root = make_account("root@example.com", is_admin=True)
    joao = make_account("joão@exemplo.com.br")
    # No JSON gravado, o "ã" fica escapado (ensure_ascii): a busca pelo texto usa a mesma forma
    entry = record(
        db_session, AuditEvent.USER_UNBLOCKED, user=root.user, details={"contact": joao.user.email}
    )
    raw = db_session.scalar(text("SELECT details FROM audit_log WHERE id = :id"), {"id": entry.id})
    assert "jo\\u00e3o@" in raw

    delete_account(db_session, account_id=joao.user.id, actor_id=root.user.id, ip=None)

    [stored] = [row for row in rows(db_session, AuditLog) if row.id == entry.id]
    assert stored.details == {"contact": None}
