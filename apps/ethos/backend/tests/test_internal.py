"""API interna do ethos, chamada pelo imago (ETH-60, ETH-27): o token, o `refresh` e o `delete`
(`app/internal/router.py` e `app/internal/service.py`)."""

import hmac
import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app import audit
from app.audit import AuditEvent
from app.db import write_transaction
from app.internal import service
from app.internal.service import delete_user_data, without_emails
from app.mail.language import Locale
from app.models import (
    Alert,
    AppUser,
    AuditLog,
    Banner,
    Habit,
    HabitInvite,
    HabitMember,
    HabitPause,
    Mark,
)
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
from tests.fake_imago import INTERNAL_TOKEN
from tests.habit_helpers import Account

ANA = "ana@example.com"
T = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
AUTH = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}
UNAUTHORIZED = {"error": "unauthorized", "field": None}
REFRESH = {"email": "ana.nova@example.com", "locale": "en", "timezone": "Europe/Lisbon"}


@pytest.fixture
def imago_client(app, make_client):
    """Como o imago chama: direto, sem `Origin` (não é um navegador)."""
    return make_client(app, origin=False)


def refresh(client, user_id: int, body: Any = None, headers: dict[str, str] | None = None):
    return client.post(
        f"/internal/users/{user_id}/refresh",
        json=REFRESH if body is None else body,
        headers=AUTH if headers is None else headers,
    )


def delete(client, user_id: int, headers: dict[str, str] | None = None):
    return client.post(
        f"/internal/users/{user_id}/delete", headers=AUTH if headers is None else headers
    )


def rows(db_session, model, *order_by):
    db_session.rollback()
    query = select(model).order_by(*order_by).execution_options(populate_existing=True)
    return list(db_session.scalars(query))


def record(db_session, event, *, user=None, habit=None, details=None) -> AuditLog:
    with write_transaction(db_session):
        return audit.record(
            db_session,
            event,
            user_id=None if user is None else user.id,
            habit_id=None if habit is None else habit.id,
            details=details,
        )


# --- token ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer outro-token-qualquer-de-32-caracteres-xx"},
        {"Authorization": f"Bearer {INTERNAL_TOKEN}x"},
        {"Authorization": INTERNAL_TOKEN},
        {"Authorization": f"Basic {INTERNAL_TOKEN}"},
        {"Authorization": "Bearer "},
        # Fora do ASCII: não confere (sem 500)
        {"Authorization": "Bearer tõken".encode("latin-1")},
    ],
)
@pytest.mark.parametrize("call", [refresh, delete])
def test_wrong_or_missing_token_is_401(imago_client, make_account, db_session, headers, call):
    ana = make_account(ANA)

    response = call(imago_client, ana.user.id, headers=headers)

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)
    assert response.headers["www-authenticate"] == "Bearer"
    # Nada mudou
    assert [user.email for user in rows(db_session, AppUser)] == [ANA]


def test_two_authorization_headers_are_refused(imago_client, make_account):
    ana = make_account(ANA)
    headers = [("authorization", f"Bearer {INTERNAL_TOKEN}")] * 2

    response = imago_client.post(f"/internal/users/{ana.user.id}/delete", headers=headers)

    assert response.status_code == 401


def test_token_is_checked_before_the_body(imago_client):
    # Sem token, nem o JSON é lido: 401, e não 422
    response = imago_client.post(
        "/internal/users/1/refresh", content=b"{nao e json", headers={"Content-Type": "json"}
    )
    assert response.status_code == 401


def test_token_is_compared_in_constant_time(imago_client, monkeypatch):
    calls: list[tuple[bytes, bytes]] = []
    compare_digest = hmac.compare_digest

    def spy(left: bytes, right: bytes) -> bool:
        calls.append((left, right))
        return compare_digest(left, right)

    monkeypatch.setattr("app.identity.hmac.compare_digest", spy)

    assert delete(imago_client, 1).status_code == 200
    # No middleware e na dependência do router
    assert calls == [(INTERNAL_TOKEN.encode(), INTERNAL_TOKEN.encode())] * 2


def test_router_dependency_refuses_without_the_middleware(settings, database, imago):
    # A dependência do router confere o token mesmo se o middleware sair da frente
    from fastapi.testclient import TestClient

    from app.identity import RequestGuardMiddleware
    from app.main import create_app

    api = create_app(settings, imago_transport=imago.transport)
    api.user_middleware = [m for m in api.user_middleware if m.cls is not RequestGuardMiddleware]
    with TestClient(api) as client:
        response = client.post("/internal/users/1/delete")
    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)


def test_internal_routes_need_no_origin_nor_user(imago_client):
    # Sem Origin e sem X-User-*: o token basta
    assert refresh(imago_client, 42).status_code == 200
    assert delete(imago_client, 42).status_code == 200


def test_unknown_internal_route_without_token_is_401(imago_client):
    assert imago_client.get("/internal/qualquer").status_code == 401
    assert imago_client.get("/internal/qualquer", headers=AUTH).status_code == 404


@pytest.mark.parametrize("user_id", ["0", "-1", str(2**53), "abc"])
@pytest.mark.parametrize("action", ["refresh", "delete"])
def test_id_out_of_range_is_422(imago_client, user_id, action):
    response = imago_client.post(f"/internal/users/{user_id}/{action}", json=REFRESH, headers=AUTH)
    assert (response.status_code, response.json()["field"]) == (422, "user_id")


def test_largest_id_is_accepted(imago_client):
    assert delete(imago_client, 2**53 - 1).status_code == 200


# --- refresh -------------------------------------------------------------------------------


def test_refresh_updates_the_copy(imago_client, make_account, db_session):
    ana = make_account(ANA)
    bia = make_account("bia@example.com")

    response = refresh(imago_client, ana.user.id)

    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    [stored, other] = rows(db_session, AppUser, AppUser.email)
    assert (stored.id, stored.email, stored.locale, stored.timezone) == (
        ana.user.id,
        "ana.nova@example.com",
        "en",
        "Europe/Lisbon",
    )
    assert stored.updated_at > stored.first_seen_at
    assert (other.email, other.locale) == (bia.user.email, "pt")


def test_refresh_of_an_unknown_id_creates_nothing(imago_client, db_session):
    response = refresh(imago_client, 777)

    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    assert count(db_session, AppUser) == 0


def test_refresh_with_the_same_values_writes_nothing(imago_client, make_account, db_session):
    ana = make_account(ANA)
    body = {"email": ANA, "locale": "pt", "timezone": "America/Sao_Paulo"}
    before = rows(db_session, AppUser)[0].updated_at

    assert refresh(imago_client, ana.user.id, body).status_code == 200

    assert rows(db_session, AppUser)[0].updated_at == before
    assert (
        service.refresh_app_user(
            db_session,
            user_id=ana.user.id,
            email=ANA,
            locale=Locale.PT,
            timezone="America/Sao_Paulo",
        )
        is False
    )


def test_refresh_ignores_extra_fields(imago_client, make_account, db_session):
    ana = make_account(ANA)

    assert refresh(imago_client, ana.user.id, REFRESH | {"active": True}).status_code == 200
    assert rows(db_session, AppUser)[0].email == "ana.nova@example.com"


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"email": "Ana@Example.com"}, "email"),
        ({"email": " ana@example.com"}, "email"),
        ({"email": "joão@example.com"}, "email"),
        ({"email": "sem-arroba"}, "email"),
        ({"email": "a" * 250 + "@x.com"}, "email"),
        ({"locale": "es"}, "locale"),
        ({"timezone": "Mars/Base"}, "timezone"),
        ({"timezone": "localtime"}, "timezone"),
        ({"email": None}, "email"),
        ({"timezone": 3}, "timezone"),
    ],
)
def test_refresh_refuses_invalid_values(imago_client, make_account, db_session, change, field):
    ana = make_account(ANA)

    response = refresh(imago_client, ana.user.id, REFRESH | change)

    assert (response.status_code, response.json()) == (
        422,
        {"error": "validation_error", "field": field},
    )
    assert rows(db_session, AppUser)[0].email == ANA


@pytest.mark.parametrize("missing", ["email", "locale", "timezone"])
def test_refresh_requires_every_field(imago_client, make_account, missing):
    ana = make_account(ANA)
    body = {key: value for key, value in REFRESH.items() if key != missing}

    response = refresh(imago_client, ana.user.id, body)

    assert (response.status_code, response.json()["field"]) == (422, missing)


# --- delete: o cenário ---------------------------------------------------------------------


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
    """Ana (a ser apagada) com hábitos próprios compartilhados, participação e marcações em
    hábitos de outras pessoas, convites, alertas, banner e auditoria de todo tipo."""
    ana = make_account(ANA, admin=True)
    root = make_account("root@example.com", admin=True)
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
        # O mesmo email, ligado a outra conta (a cópia da Ana poderia estar velha): fica
        new_invite(piano, ANA, invited_user_id=caio.user.id),
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
    logs = {
        # Da Ana: os hábitos dela apagados antes saem
        "ana_old_habit": record(
            db_session, AuditEvent.HABIT_DELETED, user=a, details={"habit_id": 999}
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
            details={"invite_id": 1, "role": "viewer"},
        ),
        # Ação da Ana como admin: anonimizada
        "ana_viewed": record(
            db_session,
            AuditEvent.ADMIN_VIEWED_HABITS,
            user=a,
            details={"target_user_id": b.id},
        ),
        # Do root sobre a Ana: fica, sem email
        "root_viewed_ana": record(
            db_session,
            AuditEvent.ADMIN_VIEWED_HABITS,
            user=r,
            details={"target_user_id": a.id, "note": "pedido de ana@example.com"},
        ),
        # Cita só o email (em maiúsculas), sem o id: achada pelo texto
        "root_banner": record(
            db_session,
            AuditEvent.BANNER_UPDATED,
            user=r,
            details={
                "banner_id": 1,
                "changes": [{"field": "text_pt", "old": f"Fale com {ANA.upper()}", "new": "x"}],
            },
        ),
        # Sem relação com a Ana: intacto (o "@" fica)
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


def test_final_state_table_by_table(imago_client, db_session, scene):
    s = scene
    ana_id = s.ana.user.id

    response = delete(imago_client, ana_id)

    assert (response.status_code, response.json()) == (200, {"status": "deleted"})
    others = [s.root.user.id, s.bia.user.id, s.caio.user.id]
    assert [user.id for user in rows(db_session, AppUser, AppUser.id)] == others
    assert [h.id for h in rows(db_session, Habit, Habit.id)] == [s.piano.id, s.chess.id, s.yoga.id]
    assert rows(db_session, HabitPause) == []
    assert [(m.habit_id, m.user_id) for m in rows(db_session, HabitMember)] == [
        (s.piano.id, s.caio.user.id)
    ]
    assert [(i.habit_id, i.email) for i in rows(db_session, HabitInvite, HabitInvite.id)] == [
        (s.piano.id, ANA),
        (s.chess.id, "eva@example.com"),
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
        (row.id, row.event, row.user_id, row.habit_id, row.details)
        for row in rows(db_session, AuditLog, AuditLog.id)
    ]
    bia_id, root_id = s.bia.user.id, s.root.user.id
    assert remaining == [
        (
            logs["ana_mark"].id,
            "mark_created",
            None,
            s.piano.id,
            {"mark_id": s.ana_mark_on_piano.id, "author_id": None, "has_note": True},
        ),
        (
            logs["bia_deleted_ana_mark"].id,
            "mark_deleted",
            bia_id,
            s.piano.id,
            {"mark_id": 12345, "author_id": None, "has_note": False},
        ),
        (
            logs["role_changed"].id,
            "member_role_changed",
            bia_id,
            s.piano.id,
            {"member_id": None, "changes": [{"field": "role", "old": "viewer", "new": "editor"}]},
        ),
        (
            logs["ana_accepted"].id,
            "invite_accepted",
            None,
            s.piano.id,
            {"invite_id": 1, "role": "viewer"},
        ),
        (logs["ana_viewed"].id, "admin_viewed_habits", None, None, {"target_user_id": bia_id}),
        (
            logs["root_viewed_ana"].id,
            "admin_viewed_habits",
            root_id,
            None,
            {"target_user_id": ana_id, "note": None},
        ),
        (
            logs["root_banner"].id,
            "banner_updated",
            root_id,
            None,
            {"banner_id": 1, "changes": [{"field": "text_pt", "old": None, "new": "x"}]},
        ),
        (
            logs["bia_updated"].id,
            "habit_updated",
            bia_id,
            s.piano.id,
            {"changes": [{"field": "name", "old": "Piano", "new": "Piano @ casa"}]},
        ),
    ]


def test_history_shows_the_removed_user(client, imago_client, scene):
    s = scene
    assert delete(imago_client, s.ana.user.id).status_code == 200

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
    imago_client, db_session, engine, database, make_account
):
    ana = make_account(ANA)
    bia = make_account("bia@example.com")
    root = make_account("root@example.com")
    piano = new_habit(bia.user, name="Piano")
    save(db_session, piano)
    save(db_session, new_invite(piano, ANA), new_invite(piano, "eva@example.com"))
    record(
        db_session,
        AuditEvent.ADMIN_VIEWED_HABITS,
        user=root.user,
        details={"target_user_id": ana.user.id, "note": ANA},
    )
    db_session.close()
    before = _database_bytes(database).lower()
    # Controle: a busca acha o email antes da exclusão
    assert ANA.encode() in before

    assert delete(imago_client, ana.user.id).status_code == 200

    engine.dispose()
    after = _database_bytes(database).lower()
    assert ANA.encode() not in after
    # Os dos outros continuam
    assert b"bia@example.com" in after
    assert b"eva@example.com" in after


# --- delete: avisos, transação, idempotência -----------------------------------------------


def test_access_lost_notices_go_out_after_the_commit(imago, imago_client, database, scene):
    s = scene
    seen: list[bool] = []

    def status(body: dict[str, Any]) -> int:
        # Outra conexão: a Ana já não existe quando o aviso sai
        with closing(sqlite3.connect(database)) as connection:
            query = "SELECT count(*) FROM app_users WHERE user_id = ?"
            [found] = connection.execute(query, (s.ana.user.id,)).fetchone()
        seen.append(bool(found))
        return 202

    imago.mail_status = status

    assert delete(imago_client, s.ana.user.id).status_code == 200

    assert seen == [False, False]
    assert sorted(mail.user_id for mail in imago.mails) == sorted([s.bia.user.id, s.caio.user.id])
    [to_bia] = imago.mails_to(s.bia.user.id)
    assert (to_bia.kind, to_bia.subject) == ("notification", "Notice about shared habits on ethos")
    assert "Leitura" in to_bia.text
    assert "Corrida" in to_bia.text
    [to_caio] = imago.mails_to(s.caio.user.id)
    assert to_caio.subject == "Aviso sobre hábitos compartilhados no ethos"
    assert "Leitura" in to_caio.text
    assert "Corrida" not in to_caio.text
    # A própria pessoa não recebe nada do ethos (o "conta excluída" é do imago)
    assert imago.mails_to(s.ana.user.id) == []


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


@pytest.mark.parametrize("step", ["_scrub_emails", "_access_lost"])
def test_failure_in_the_middle_deletes_nothing_and_sends_nothing(
    app, make_client, imago, database, monkeypatch, scene, step
):
    client = make_client(app, origin=False, raise_server_exceptions=False)
    before = _snapshot(database)

    def boom(*_args, **_kwargs):
        raise RuntimeError("falha no meio")

    monkeypatch.setattr(service, step, boom)
    response = delete(client, scene.ana.user.id)

    assert response.status_code == 500
    assert _snapshot(database) == before
    assert imago.mails == []


def test_failure_after_deleting_the_row_rolls_back(app, make_client, database, scene, monkeypatch):
    client = make_client(app, origin=False, raise_server_exceptions=False)
    before = _snapshot(database)
    real_execute = service._execute

    def execute_then_fail(session, statement):
        real_execute(session, statement)
        if statement.table.name == "app_users":
            raise RuntimeError("falha depois de apagar a linha")

    monkeypatch.setattr(service, "_execute", execute_then_fail)

    assert delete(client, scene.ana.user.id).status_code == 500
    assert _snapshot(database) == before


def test_second_call_changes_nothing(imago, imago_client, database, scene):
    assert delete(imago_client, scene.ana.user.id).status_code == 200
    imago.mails.clear()
    before = _snapshot(database)

    response = delete(imago_client, scene.ana.user.id)

    assert (response.status_code, response.json()) == (200, {"status": "deleted"})
    assert _snapshot(database) == before
    assert imago.mails == []


def test_unknown_id_deletes_the_invites_it_received(imago_client, db_session, make_account):
    bia = make_account("bia@example.com")
    piano = new_habit(bia.user, name="Piano")
    save(db_session, piano)
    # Convidada que nunca abriu o ethos: só existe no imago
    save(
        db_session,
        new_invite(piano, "nova@example.com", invited_user_id=555),
        new_invite(piano, "outra@example.com", invited_user_id=556),
    )

    response = delete(imago_client, 555)

    assert (response.status_code, response.json()) == (200, {"status": "deleted"})
    assert [i.invited_user_id for i in rows(db_session, HabitInvite)] == [556]


def test_log_has_only_the_numeric_id(imago_client, make_account, caplog):
    ana = make_account(ANA)

    with caplog.at_level(logging.DEBUG):
        assert delete(imago_client, ana.user.id).status_code == 200

    assert f"dados da conta {ana.user.id} apagados" in caplog.messages
    assert ANA not in caplog.text
    assert INTERNAL_TOKEN not in caplog.text


def test_unknown_id_logs_nothing(imago_client, caplog):
    with caplog.at_level(logging.INFO):
        assert delete(imago_client, 999).status_code == 200
    assert [record for record in caplog.records if record.name.startswith("app.internal")] == []


def test_delete_user_data_reports_whether_the_row_existed(db_session, make_account):
    ana = make_account(ANA)
    habit = new_habit(ana.user)
    save(db_session, habit)
    bia = make_account("bia@example.com", locale="en")
    save(db_session, new_member(habit, bia.user, "viewer"))

    first = delete_user_data(db_session, user_id=ana.user.id)
    second = delete_user_data(db_session, user_id=ana.user.id)

    assert (first.user_id, first.existed) == (ana.user.id, True)
    [notice] = first.notices
    assert (notice.user_id, notice.locale, notice.email.habit_names) == (
        bia.user.id,
        "en",
        ("Exercício",),
    )
    assert (second.existed, second.notices) == (False, ())


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
