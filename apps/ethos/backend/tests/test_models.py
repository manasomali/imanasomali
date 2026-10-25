from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
import time_machine
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db import write_transaction
from app.models import (
    Alert,
    AuditLog,
    Banner,
    Habit,
    HabitColor,
    HabitInvite,
    HabitMember,
    HabitPause,
    LoginCode,
    Mark,
    User,
    UserSession,
)
from tests.factories import count, new_habit, new_user, save

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
HASH = "a" * 64


@pytest.fixture
def ana(db_session) -> User:
    user = new_user()
    save(db_session, user)
    return user


@pytest.fixture
def bia(db_session) -> User:
    user = new_user("bia@example.com")
    save(db_session, user)
    return user


def assert_check_fails(session: Session, constraint: str, *objects: Any) -> None:
    # O nome inteiro da constraint, seguido do fim da linha da mensagem do sqlite
    with pytest.raises(IntegrityError, match=rf"CHECK constraint failed: {constraint}\n"):
        save(session, *objects)


# --- Exclusão em cascata ----------------------------------------------------------------------


def test_deleting_user_cascades_to_everything_that_is_theirs(db_session, ana, bia):
    habit = new_habit(ana)
    save(db_session, habit)
    save(
        db_session,
        UserSession(token_hash=HASH, user_id=ana.id, expires_at=NOW),
        LoginCode(
            email=ana.email,
            user_id=ana.id,
            purpose="delete_account",
            code_hash=HASH,
            expires_at=NOW,
        ),
        Mark(habit_id=habit.id, user_id=ana.id, marked_at=NOW),
        Mark(habit_id=habit.id, user_id=bia.id, marked_at=NOW),
        HabitPause(habit_id=habit.id, started_at=NOW),
        HabitMember(habit_id=habit.id, user_id=bia.id, role="editor"),
        HabitInvite(habit_id=habit.id, email="caio@example.com", role="viewer"),
        Alert(habit_id=habit.id, user_id=bia.id, hour=8, frequency="daily"),
        AuditLog(user_id=bia.id, habit_id=habit.id, event="mark_created"),
    )

    with write_transaction(db_session):
        db_session.execute(delete(User).where(User.id == ana.id))

    for model in (
        User,
        UserSession,
        LoginCode,
        Habit,
        Mark,
        HabitPause,
        HabitMember,
        HabitInvite,
        Alert,
        AuditLog,
    ):
        assert count(db_session, model) == (1 if model is User else 0), model
    # Bia continua, só perdeu o acesso ao hábito apagado
    assert db_session.scalar(select(User.email)) == "bia@example.com"


def test_deleting_user_anonymizes_authorship_in_other_peoples_data(db_session, ana, bia):
    habit = new_habit(bia)
    save(db_session, habit)
    mark = Mark(habit_id=habit.id, user_id=ana.id, marked_at=NOW)
    event = AuditLog(user_id=ana.id, habit_id=habit.id, event="mark_created")
    banner = Banner(
        text_pt="Olá",
        text_en="Hi",
        starts_at=NOW,
        ends_at=NOW + timedelta(days=1),
        created_by=ana.id,
    )
    save(
        db_session,
        mark,
        event,
        banner,
        HabitMember(habit_id=habit.id, user_id=ana.id, role="editor"),
        Alert(habit_id=habit.id, user_id=ana.id, hour=8, frequency="daily"),
        HabitInvite(habit_id=habit.id, email=ana.email, invited_user_id=ana.id, role="viewer"),
    )

    with write_transaction(db_session):
        db_session.execute(delete(User).where(User.id == ana.id))

    # O dado fica, sem autor ("usuário removido")
    assert db_session.scalar(select(Mark.user_id).where(Mark.id == mark.id)) is None
    assert db_session.scalar(select(AuditLog.user_id).where(AuditLog.id == event.id)) is None
    assert db_session.scalar(select(Banner.created_by).where(Banner.id == banner.id)) is None
    assert count(db_session, Habit, Habit.id == habit.id) == 1
    # A participação, os alertas e os convites dela no hábito alheio saem
    assert count(db_session, HabitMember) == 0
    assert count(db_session, Alert) == 0
    assert count(db_session, HabitInvite) == 0


def test_deleting_habit_cascades_to_its_data_and_audit(db_session, ana, bia):
    habit = new_habit(ana)
    other = new_habit(ana, name="Leitura")
    save(db_session, habit, other)
    save(
        db_session,
        Mark(habit_id=habit.id, user_id=ana.id, marked_at=NOW),
        AuditLog(user_id=ana.id, habit_id=habit.id, event="mark_created"),
        AuditLog(user_id=ana.id, habit_id=other.id, event="mark_created"),
        AuditLog(user_id=ana.id, event="login"),
        HabitMember(habit_id=habit.id, user_id=bia.id, role="viewer"),
    )

    with write_transaction(db_session):
        db_session.execute(delete(Habit).where(Habit.id == habit.id))

    assert count(db_session, Mark) == 0
    assert count(db_session, HabitMember) == 0
    assert db_session.scalars(select(AuditLog.habit_id).order_by(AuditLog.id)).all() == [
        other.id,
        None,
    ]
    assert count(db_session, User) == 2


def test_foreign_key_to_missing_row_is_refused(db_session):
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        save(db_session, UserSession(token_hash=HASH, user_id=999, expires_at=NOW))


# --- CHECK nos enums --------------------------------------------------------------------------


ENUM_CASES = [
    ("ck_users_locale", "users", "locale", "es"),
    ("ck_habits_color", "habits", "color", "magenta"),
    ("ck_habits_goal_type", "habits", "goal_type", "at_least"),
    ("ck_habits_goal_period", "habits", "goal_period", "day"),
    ("ck_habits_cost_level", "habits", "cost_level", "day"),
    ("ck_habits_cost_limit_period", "habits", "cost_limit_period", "day"),
    ("ck_habits_status", "habits", "status", "deleted"),
    ("ck_habit_members_role", "habit_members", "role", "owner"),
    ("ck_habit_invites_role", "habit_invites", "role", "owner"),
    ("ck_alerts_frequency", "alerts", "frequency", "monthly"),
    ("ck_login_codes_purpose", "login_codes", "purpose", "change_email"),
]


@pytest.fixture
def full_rows(db_session, ana, bia) -> dict[str, Any]:
    """Uma linha válida de cada tabela com enum, para os testes trocarem um campo por vez."""
    habit = new_habit(ana, cost_limit_cents=1000, cost_limit_period="month")
    save(db_session, habit)
    return {
        "users": new_user("caio@example.com"),
        "habits": new_habit(ana, cost_limit_cents=1000, cost_limit_period="month"),
        "habit_members": HabitMember(habit_id=habit.id, user_id=bia.id, role="viewer"),
        "habit_invites": HabitInvite(habit_id=habit.id, email="caio@example.com", role="viewer"),
        "alerts": Alert(habit_id=habit.id, user_id=ana.id, hour=8, frequency="daily"),
        "login_codes": LoginCode(
            email="caio@example.com", purpose="login", code_hash=HASH, expires_at=NOW
        ),
    }


@pytest.mark.parametrize(("constraint", "table", "column", "value"), ENUM_CASES)
def test_check_refuses_value_outside_enum(db_session, full_rows, constraint, table, column, value):
    row = full_rows[table]
    setattr(row, column, value)

    assert_check_fails(db_session, constraint, row)


@pytest.mark.parametrize("table", sorted({table for _c, table, _col, _v in ENUM_CASES}))
def test_valid_rows_are_accepted(db_session, full_rows, table):
    # Controle do teste acima: a mesma linha, sem o valor inválido, entra
    save(db_session, full_rows[table])


def test_every_palette_color_is_accepted(db_session, ana):
    habits = [new_habit(ana, color=color) for color in HabitColor]

    save(db_session, *habits)

    assert len(HabitColor) == 12
    assert count(db_session, Habit) == 12


def test_custom_color_is_accepted(db_session, ana):
    save(db_session, new_habit(ana, color="#0a1b2c"), new_habit(ana, color="#ffffff"))

    assert count(db_session, Habit) == 2


@pytest.mark.parametrize("color", ["#0A1B2C", "#fff", "#gggggg", "#0a1b2c0", "0a1b2c0", "#0a1b2"])
def test_custom_color_must_be_lowercase_rrggbb(db_session, ana, color):
    assert_check_fails(db_session, "ck_habits_color", new_habit(ana, color=color))


# --- CHECK nos tamanhos e valores -------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "accepted", "refused", "constraint"),
    [
        ("name", "a" * 60, "a" * 61, "ck_habits_name_length"),
        ("name", "a", "", "ck_habits_name_length"),
        ("description", "a" * 500, "a" * 501, "ck_habits_description_length"),
        ("reward", "a" * 140, "a" * 141, "ck_habits_reward_length"),
        ("punishment", "a" * 140, "a" * 141, "ck_habits_punishment_length"),
        ("code", "AB12", "AB123", "ck_habits_code"),
        ("code", "É1", "ab1", "ck_habits_code"),
        ("code", "A", "", "ck_habits_code"),
        ("score_threshold", 1, 0, "ck_habits_score_threshold"),
        ("score_threshold", 100, 101, "ck_habits_score_threshold"),
        ("duration_minutes", 1, 0, "ck_habits_duration_minutes_positive"),
        ("cost_cents", 0, -1, "ck_habits_cost_cents_not_negative"),
    ],
)
def test_habit_field_limits(db_session, ana, field, accepted, refused, constraint):
    save(db_session, new_habit(ana, **{field: accepted}))

    assert_check_fails(db_session, constraint, new_habit(ana, **{field: refused}))


def test_name_length_counts_characters_not_bytes(db_session, ana):
    save(db_session, new_habit(ana, name="ç" * 60))


@pytest.mark.parametrize(
    ("goal_type", "goal_count", "accepted"),
    [
        ("max", 0, True),
        ("min", 0, False),
        ("exact", 0, False),
        ("max", -1, False),
        ("min", 1, True),
        ("exact", 1, True),
    ],
)
def test_goal_count_rules(db_session, ana, goal_type, goal_count, accepted):
    habit = new_habit(ana, goal_type=goal_type, goal_count=goal_count)
    if accepted:
        save(db_session, habit)
    else:
        assert_check_fails(db_session, "ck_habits_goal_count", habit)


def test_cost_limit_and_period_come_together(db_session, ana):
    assert_check_fails(
        db_session, "ck_habits_cost_limit_pair", new_habit(ana, cost_limit_cents=1000)
    )
    assert_check_fails(
        db_session, "ck_habits_cost_limit_pair", new_habit(ana, cost_limit_period="week")
    )
    assert_check_fails(
        db_session,
        "ck_habits_cost_limit_cents_not_negative",
        new_habit(ana, cost_limit_cents=-1, cost_limit_period="week"),
    )


def test_archived_status_and_archived_at_come_together(db_session, ana):
    save(db_session, new_habit(ana, status="archived", archived_at=NOW))
    assert_check_fails(
        db_session, "ck_habits_archived_at_status", new_habit(ana, status="archived")
    )
    assert_check_fails(
        db_session, "ck_habits_archived_at_status", new_habit(ana, status="paused", archived_at=NOW)
    )


@pytest.mark.parametrize(
    ("text_pt", "text_en", "constraint"),
    [
        ("a" * 281, "a", "ck_banners_text_pt_length"),
        ("a", "a" * 281, "ck_banners_text_en_length"),
        ("", "a", "ck_banners_text_pt_length"),
    ],
)
def test_banner_text_limits(db_session, text_pt, text_en, constraint):
    window = {"starts_at": NOW, "ends_at": NOW + timedelta(hours=1)}
    save(db_session, Banner(text_pt="a" * 280, text_en="a" * 280, **window))

    assert_check_fails(db_session, constraint, Banner(text_pt=text_pt, text_en=text_en, **window))


def test_banner_must_end_after_it_starts(db_session):
    assert_check_fails(
        db_session,
        "ck_banners_ends_after_starts",
        Banner(text_pt="a", text_en="a", starts_at=NOW, ends_at=NOW),
    )


def test_users_email_is_unique(db_session, ana):
    with pytest.raises(IntegrityError, match=r"UNIQUE constraint failed: users[.]email"):
        save(db_session, new_user(ana.email))


@pytest.mark.parametrize("email", ["Ana@example.com", " ana@example.com", "ana@example.com "])
def test_users_email_must_be_normalized(db_session, email):
    assert_check_fails(db_session, "ck_users_email_normalized", new_user(email))


def test_users_email_length(db_session):
    local = "a" * 64
    accepted = f"{local}@{'b' * (254 - len(local) - 5)}.com"
    assert len(accepted) == 254
    save(db_session, new_user(accepted))

    assert_check_fails(db_session, "ck_users_email_length", new_user("b" + accepted))


def test_invite_email_is_unique_per_habit_and_normalized(db_session, ana):
    habit = new_habit(ana)
    save(db_session, habit)
    save(db_session, HabitInvite(habit_id=habit.id, email="caio@example.com", role="viewer"))

    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        save(db_session, HabitInvite(habit_id=habit.id, email="caio@example.com", role="editor"))
    assert_check_fails(
        db_session,
        "ck_habit_invites_email_normalized",
        HabitInvite(habit_id=habit.id, email="CAIO@example.com", role="viewer"),
    )


def test_only_one_open_pause_per_habit(db_session, ana):
    habit = new_habit(ana)
    save(db_session, habit)
    save(
        db_session,
        HabitPause(habit_id=habit.id, started_at=NOW, ended_at=NOW + timedelta(days=1)),
        HabitPause(habit_id=habit.id, started_at=NOW + timedelta(days=2)),
    )

    with pytest.raises(IntegrityError, match=r"UNIQUE constraint failed: habit_pauses[.]habit_id"):
        save(db_session, HabitPause(habit_id=habit.id, started_at=NOW + timedelta(days=3)))
    assert_check_fails(
        db_session,
        "ck_habit_pauses_ended_after_started",
        HabitPause(habit_id=habit.id, started_at=NOW, ended_at=NOW - timedelta(seconds=1)),
    )


def test_alert_limits(db_session, ana):
    habit = new_habit(ana)
    save(db_session, habit)

    def alert(**fields: Any) -> Alert:
        return Alert(**({"habit_id": habit.id, "user_id": ana.id} | fields))

    assert_check_fails(db_session, "ck_alerts_hour", alert(hour=24, frequency="daily"))
    assert_check_fails(
        db_session, "ck_alerts_weekday", alert(hour=8, frequency="weekly", weekday=7)
    )
    assert_check_fails(db_session, "ck_alerts_weekly_weekday", alert(hour=8, frequency="weekly"))
    # O diário pode guardar o dia escolhido antes
    save(db_session, alert(hour=0, frequency="daily", weekday=6))


def test_login_code_attempts_cannot_be_negative(db_session):
    code = LoginCode(
        email="ana@example.com", purpose="login", code_hash=HASH, expires_at=NOW, attempts=-1
    )
    assert_check_fails(db_session, "ck_login_codes_attempts_not_negative", code)


@pytest.mark.parametrize("token_hash", ["a" * 63, "a" * 65])
def test_session_token_hash_is_a_sha256(db_session, ana, token_hash):
    session = UserSession(token_hash=token_hash, user_id=ana.id, expires_at=NOW)
    assert_check_fails(db_session, "ck_sessions_token_hash_length", session)


def test_audit_details_must_be_json(engine, ana):
    with engine.begin() as connection, pytest.raises(IntegrityError, match="details_json"):
        connection.execute(
            text(
                "INSERT INTO audit_log (event, created_at, details) "
                "VALUES ('login', '2026-01-15 12:00:00.000000', 'not json')"
            )
        )


# --- Padrões ----------------------------------------------------------------------------------


@time_machine.travel(NOW, tick=False)
def test_orm_defaults(db_session):
    ana = new_user()
    save(db_session, ana)
    habit = new_habit(ana)
    code = LoginCode(email=ana.email, purpose="login", code_hash=HASH, expires_at=NOW)
    event = AuditLog(event="login")
    save(db_session, habit, code, event)
    alert = Alert(habit_id=habit.id, user_id=ana.id, hour=8, frequency="daily")
    save(db_session, alert)

    assert (ana.is_active, ana.is_admin) == (True, False)
    assert (ana.created_at, ana.updated_at, ana.last_login_at) == (NOW, NOW, None)
    assert habit.score_threshold == 70
    assert habit.status == "active"
    assert habit.cost_level == "habit"
    assert not any(
        (
            habit.multi_mark,
            habit.duration_enabled,
            habit.notes_enabled,
            habit.score_enabled,
            habit.cost_enabled,
        )
    )
    assert code.attempts == 0
    assert event.details == {}
    assert (alert.goal_enabled, alert.cost_enabled) == (False, False)


def test_server_defaults_match_orm_defaults(engine, ana):
    """Linha inserida por SQL puro (ex.: num script de manutenção) recebe os mesmos padrões."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO habits (owner_id, name, color, goal_type, goal_count, goal_period, "
                "created_at, updated_at) VALUES (:owner, 'x', 'teal', 'min', 1, 'week', "
                "'2026-01-15 12:00:00.000000', '2026-01-15 12:00:00.000000')"
            ),
            {"owner": ana.id},
        )
        row = (
            connection.execute(
                text(
                    "SELECT multi_mark, duration_enabled, notes_enabled, score_enabled, "
                    "score_threshold, cost_enabled, cost_level, status FROM habits"
                )
            )
            .mappings()
            .one()
        )

    assert dict(row) == {
        "multi_mark": 0,
        "duration_enabled": 0,
        "notes_enabled": 0,
        "score_enabled": 0,
        "score_threshold": 70,
        "cost_enabled": 0,
        "cost_level": "habit",
        "status": "active",
    }


def test_updated_at_changes_on_update(db_session, ana):
    habit = new_habit(ana)
    with time_machine.travel(NOW, tick=False):
        save(db_session, habit)
        mark = Mark(habit_id=habit.id, user_id=ana.id, marked_at=NOW)
        save(db_session, mark)

    later = NOW + timedelta(hours=2)
    with time_machine.travel(later, tick=False), write_transaction(db_session):
        mark = db_session.get_one(Mark, mark.id)
        mark.note = "no parque"

    assert (mark.created_at, mark.updated_at, mark.marked_at) == (NOW, later, NOW)


def test_deleted_ids_are_never_reused(db_session, ana, bia):
    with write_transaction(db_session):
        db_session.execute(delete(User).where(User.id == bia.id))
    caio = new_user("caio@example.com")
    save(db_session, caio)

    assert caio.id > bia.id


# --- Datas em UTC -----------------------------------------------------------------------------


def test_datetimes_are_stored_in_utc_and_returned_aware(db_session, engine, ana):
    sao_paulo = timezone(timedelta(hours=-3))
    local = datetime(2026, 1, 15, 9, 0, tzinfo=sao_paulo)
    with write_transaction(db_session):
        db_session.execute(update(User).where(User.id == ana.id).values(last_login_at=local))

    with engine.connect() as connection:
        stored = connection.execute(text("SELECT last_login_at FROM users")).scalar_one()
    loaded = db_session.scalar(select(User.last_login_at))

    # Mesmo instante, gravado em UTC, em texto de largura fixa
    assert stored == "2026-01-15 12:00:00.000000"
    assert loaded == local
    assert loaded.tzinfo is UTC


def test_naive_datetime_is_refused(db_session, ana):
    with pytest.raises(StatementError, match="datetime sem fuso"):
        save(db_session, Mark(habit_id=None, user_id=ana.id, marked_at=datetime(2026, 1, 15)))


@pytest.mark.parametrize("value", [date(2026, 1, 15), "2026-01-15 12:00:00"])
def test_non_datetime_is_refused(db_session, value):
    with pytest.raises(StatementError, match="esperava datetime"):
        db_session.scalars(select(Mark.id).where(Mark.marked_at >= value)).all()


def test_naive_datetime_is_refused_in_queries(db_session):
    with pytest.raises(StatementError, match="datetime sem fuso"):
        db_session.scalars(select(Mark).where(Mark.marked_at >= datetime(2026, 1, 15))).all()


def test_aware_datetime_in_queries_is_compared_in_utc(db_session, ana):
    habit = new_habit(ana)
    save(db_session, habit)
    save(db_session, Mark(habit_id=habit.id, user_id=ana.id, marked_at=NOW))
    # 09:00 em São Paulo = 12:00 UTC
    same_instant = NOW.astimezone(timezone(timedelta(hours=-3)))

    found = db_session.scalars(select(Mark.id).where(Mark.marked_at >= same_instant)).all()

    assert len(found) == 1


def test_json_details_round_trip(db_session):
    details = {"changed": {"name": ["a", "b"]}, "count": 2, "ok": True}
    event = AuditLog(event="habit_updated", details=details)
    save(db_session, event)
    db_session.expire_all()

    assert db_session.get_one(AuditLog, event.id).details == details
