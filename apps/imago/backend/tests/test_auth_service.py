"""Regras do login por código (`app/auth/service.py`), sem HTTP."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from sqlalchemy import select, update

from app.audit import AuditEvent
from app.auth import service
from app.auth.security import hash_secret
from app.auth.service import (
    CodeRequestOutcome,
    CodeRequestResult,
    LoginResult,
    VerifyFailure,
    can_sign_in,
    create_session,
    is_valid_timezone,
    normalize_email,
    request_delete_code,
    request_login_code,
    use_delete_code,
    verify_login_code,
)
from app.db import create_session_factory, write_transaction
from app.mail.catalog import DeleteCode, LoginCode, SendCapReached
from app.mail.language import Locale
from app.models import (
    MAX_ACCOUNT_ID,
    AuditLog,
    MailLog,
    User,
    UserSession,
)
from app.models import (
    LoginCode as LoginCodeRow,
)
from app.terms import TERMS_VERSION
from tests.factories import count, new_user, save

ANA = "ana@example.com"
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


def ask(session, settings, email=ANA, accept_language=None) -> CodeRequestResult:
    return request_login_code(
        session, settings, email=email, ip="203.0.113.7", accept_language=accept_language
    )


def issue(session, settings, email=ANA) -> str:
    result = ask(session, settings, email)
    assert result.outcome is CodeRequestOutcome.SENT
    [outgoing] = result.emails
    return outgoing.email.code


def check(session, code, email=ANA, timezone="America/Sao_Paulo", locale=Locale.PT):
    return verify_login_code(
        session,
        email=email,
        code=code,
        timezone=timezone,
        locale=locale,
        ip="203.0.113.7",
        user_agent="navegador",
    )


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def events(session, event: AuditEvent) -> list[AuditLog]:
    session.rollback()
    return list(session.scalars(select(AuditLog).where(AuditLog.event == event.value)))


# --- validações ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ana@example.com", "ana@example.com"),
        ("  Ana@Example.COM\n", "ana@example.com"),
        ("ana@xn--exmple-cua.com", "ana@xn--exmple-cua.com"),
        # Só ASCII: o email vai no header X-User-Email
        ("joão@exemplo.com.br", None),
        ("ana@exämple.com", None),
        ("", None),
        ("ana", None),
        ("ana@example", None),
        ("ana@@example.com", None),
        ("an a@example.com", None),
        ("ana@exam\x00ple.com", None),
        ("<ana@example.com>", None),
        ("a" * 243 + "@example.com", None),
    ],
)
def test_normalize_email(value, expected):
    assert normalize_email(value) == expected


def test_normalize_email_accepts_254_characters():
    email = "a" * 242 + "@example.com"
    assert normalize_email(email) == email


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("America/Sao_Paulo", True),
        ("UTC", True),
        ("Europe/Lisbon", True),
        ("america/sao_paulo", False),
        ("Mars/Base", False),
        ("", False),
        ("../../etc/passwd", False),
        ("America/" + "X" * 64, False),
    ],
)
def test_is_valid_timezone(name, expected):
    assert is_valid_timezone(name) is expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({}, True),
        ({"is_active": False}, False),
        ({"status": "deleting"}, False),
        ({"is_active": False, "status": "deleting"}, False),
    ],
)
def test_can_sign_in(values, expected):
    assert can_sign_in(new_user(**({"is_active": True, "status": "active"} | values))) is expected


# --- pedir código ---


def test_new_email_gets_a_code_in_the_browser_language(db_session, settings):
    result = ask(db_session, settings, accept_language="pt-BR,pt;q=0.9,en;q=0.8")

    assert result.accepted
    [outgoing] = result.emails
    assert (outgoing.to, outgoing.locale) == (ANA, Locale.PT)
    assert isinstance(outgoing.email, LoginCode)
    db_session.rollback()
    [row] = db_session.scalars(select(LoginCodeRow))
    # No banco, só o hash
    assert row.code_hash == hash_secret(outgoing.email.code)
    assert (row.purpose, row.user_id, row.attempts) == ("login", None, 0)
    assert row.expires_at == NOW + timedelta(minutes=10)
    # Uma linha no teto, como "imago" e "code"
    [mail] = db_session.scalars(select(MailLog))
    assert (mail.app, mail.kind) == ("imago", "code")
    # Sem conta, sem evento (não há a quem ligar)
    assert count(db_session, AuditLog) == 0


def test_existing_account_gets_the_code_in_its_language(db_session, settings):
    user = new_user(ANA, locale="en")
    save(db_session, user)

    result = ask(db_session, settings, accept_language="pt-BR")

    assert result.emails[0].locale is Locale.EN
    [event] = events(db_session, AuditEvent.CODE_REQUESTED)
    assert (event.user_id, event.ip) == (user.id, "203.0.113.7")


@pytest.mark.parametrize("values", [{"is_active": False}, {"status": "deleting"}])
def test_blocked_or_deleting_account_gets_a_row_but_no_email(db_session, settings, values):
    save(db_session, new_user(ANA, **values))

    result = ask(db_session, settings)

    assert result.outcome is CodeRequestOutcome.INACTIVE_ACCOUNT
    assert result.accepted
    assert result.emails == ()
    db_session.rollback()
    # Conta nos limites como as outras, mas não no teto (nada sai)
    assert count(db_session, LoginCodeRow) == 1
    assert count(db_session, MailLog) == 0


def test_one_code_per_minute(db_session, settings, frozen):
    issue(db_session, settings)

    assert ask(db_session, settings).outcome is CodeRequestOutcome.RATE_LIMITED
    frozen.shift(MINUTE)
    assert ask(db_session, settings).outcome is CodeRequestOutcome.SENT


def test_sixth_code_in_an_hour_is_refused_even_with_the_others_expired(
    db_session, settings, frozen
):
    for _ in range(5):
        issue(db_session, settings)
        # Cada código vence (10 min) antes do próximo pedido
        frozen.shift(11 * MINUTE)

    result = ask(db_session, settings)

    assert result.outcome is CodeRequestOutcome.RATE_LIMITED
    assert not result.accepted
    assert result.emails == ()
    db_session.rollback()
    assert count(db_session, LoginCodeRow) == 5
    # Uma hora depois do primeiro, cabe de novo
    frozen.shift(6 * MINUTE)
    assert ask(db_session, settings).outcome is CodeRequestOutcome.SENT


def test_delete_codes_count_in_the_same_limit(db_session, settings):
    user = new_user(ANA)
    save(db_session, user)
    with write_transaction(db_session):
        assert request_delete_code(db_session, settings, user=user, ip=None).accepted

    assert ask(db_session, settings).outcome is CodeRequestOutcome.RATE_LIMITED


def test_new_code_invalidates_the_previous_one_of_the_same_purpose(db_session, settings, frozen):
    first = issue(db_session, settings)
    frozen.shift(MINUTE)
    second = issue(db_session, settings)

    assert check(db_session, first) is VerifyFailure.INVALID_CODE
    assert isinstance(check(db_session, second), LoginResult)


def test_new_code_cleans_expired_sessions_and_old_codes(db_session, settings):
    user = new_user("bia@example.com")
    save(db_session, user)
    save(
        db_session,
        UserSession(token_hash="a" * 64, user_id=user.id, expires_at=NOW - MINUTE),
        UserSession(token_hash="b" * 64, user_id=user.id, expires_at=NOW + MINUTE),
        LoginCodeRow(
            email="caio@example.com",
            purpose="login",
            code_hash="c" * 64,
            created_at=NOW - timedelta(hours=25),
            expires_at=NOW - timedelta(hours=24, minutes=50),
        ),
    )

    issue(db_session, settings)

    db_session.rollback()
    assert list(db_session.scalars(select(UserSession.token_hash))) == ["b" * 64]
    assert list(db_session.scalars(select(LoginCodeRow.email))) == [ANA]


def fill_mail_log(session, total: int) -> None:
    save(
        session, *(MailLog(app="ethos", kind="code", created_at=NOW - MINUTE) for _ in range(total))
    )


def test_cap_reached_refuses_and_alerts_support_once_an_hour(db_session, settings, frozen):
    fill_mail_log(db_session, 60)

    first = ask(db_session, settings)
    second = ask(db_session, settings, email="bia@example.com")

    assert first.outcome is CodeRequestOutcome.CAP_REACHED
    assert not first.accepted
    [alert] = first.emails
    assert (alert.to, alert.locale) == ("suporte@example.com", Locale.PT)
    assert alert.email == SendCapReached(window="hour", limit=60)
    # Segundo pedido na mesma hora: recusado, sem outro aviso
    assert second.outcome is CodeRequestOutcome.CAP_REACHED
    assert second.emails == ()
    db_session.rollback()
    assert count(db_session, LoginCodeRow) == 0
    assert count(db_session, MailLog) == 60
    assert len(events(db_session, AuditEvent.SEND_CAP_REACHED)) == 1


def test_delete_code_respects_the_cap(db_session, settings):
    user = new_user(ANA)
    save(db_session, user)
    fill_mail_log(db_session, 60)

    with write_transaction(db_session):
        result = request_delete_code(db_session, settings, user=user, ip=None)

    assert result.outcome is CodeRequestOutcome.CAP_REACHED
    assert len(result.emails) == 1


# --- verificar ---


def test_first_access_creates_the_account(db_session, settings):
    code = issue(db_session, settings)

    result = check(db_session, code, timezone="Europe/Lisbon", locale=Locale.EN)

    assert isinstance(result, LoginResult)
    assert result.new_account is True
    db_session.rollback()
    user = db_session.scalar(select(User))
    assert user.id == result.user_id
    assert 1 <= user.id <= MAX_ACCOUNT_ID
    assert (user.email, user.timezone, user.locale, user.status) == (
        ANA,
        "Europe/Lisbon",
        "en",
        "active",
    )
    assert (user.is_active, user.is_admin) == (True, False)
    assert (user.terms_version, user.terms_accepted_at) == (TERMS_VERSION, NOW)
    assert user.last_login_at == NOW
    session_row = db_session.scalar(select(UserSession))
    assert session_row.token_hash == hash_secret(result.token)
    assert (session_row.ip, session_row.user_agent) == ("203.0.113.7", "navegador")
    [login] = events(db_session, AuditEvent.LOGIN)
    assert login.details == {"new_account": True}
    used = db_session.scalar(select(LoginCodeRow))
    assert (used.used_at, used.attempts) == (NOW, 1)


def test_account_id_is_redrawn_on_collision(db_session, settings, monkeypatch):
    taken = new_user("bia@example.com", id=42)
    save(db_session, taken)
    draws = iter([42, 42, 77])
    monkeypatch.setattr(service, "generate_account_id", lambda: next(draws))
    code = issue(db_session, settings)

    result = check(db_session, code)

    assert result.user_id == 77


def test_account_id_gives_up_after_many_collisions(db_session, settings, monkeypatch):
    save(db_session, new_user("bia@example.com", id=42))
    monkeypatch.setattr(service, "generate_account_id", lambda: 42)
    code = issue(db_session, settings)

    with pytest.raises(RuntimeError, match="nenhum id de conta livre"):
        check(db_session, code)

    db_session.rollback()
    # Nada criado; o código continua valendo
    assert count(db_session, User) == 1
    assert db_session.scalar(select(LoginCodeRow.used_at)) is None


def test_existing_account_ignores_timezone_and_locale(db_session, settings, frozen):
    user = new_user(ANA, timezone="America/Sao_Paulo", locale="pt")
    save(db_session, user)
    code = issue(db_session, settings)

    result = check(db_session, code, timezone="Asia/Tokyo", locale=Locale.EN)

    assert result.new_account is False
    db_session.rollback()
    saved = db_session.scalar(select(User))
    assert (saved.timezone, saved.locale, saved.last_login_at) == ("America/Sao_Paulo", "pt", NOW)


def test_existing_account_with_unknown_timezone_still_signs_in(db_session, settings):
    save(db_session, new_user(ANA))
    code = issue(db_session, settings)

    assert isinstance(check(db_session, code, timezone="Mars/Base"), LoginResult)


def test_unknown_timezone_on_first_access_keeps_the_code_valid(db_session, settings):
    code = issue(db_session, settings)

    assert check(db_session, code, timezone="Mars/Base") is VerifyFailure.INVALID_TIMEZONE
    assert isinstance(check(db_session, code), LoginResult)


def test_wrong_expired_used_and_other_email_codes_are_refused(db_session, settings, frozen):
    code = issue(db_session, settings)
    other = issue(db_session, settings, "bia@example.com")

    assert check(db_session, wrong(code)) is VerifyFailure.INVALID_CODE
    assert check(db_session, other) is VerifyFailure.INVALID_CODE
    assert isinstance(check(db_session, code), LoginResult)
    # Já usado
    assert check(db_session, code) is VerifyFailure.INVALID_CODE
    # Vencido (10 min)
    frozen.shift(10 * MINUTE)
    assert check(db_session, other, "bia@example.com") is VerifyFailure.INVALID_CODE
    # Sem código nenhum
    assert check(db_session, code, "caio@example.com") is VerifyFailure.INVALID_CODE


def test_sixth_attempt_is_refused_even_with_the_right_code(db_session, settings):
    code = issue(db_session, settings)

    for _ in range(5):
        assert check(db_session, wrong(code)) is VerifyFailure.INVALID_CODE

    assert check(db_session, code) is VerifyFailure.INVALID_CODE
    db_session.rollback()
    assert db_session.scalar(select(LoginCodeRow.attempts)) == 5


@pytest.mark.parametrize("values", [{"is_active": False}, {"status": "deleting"}])
def test_blocked_or_deleting_account_cannot_sign_in(db_session, settings, values):
    # O código foi pedido antes do bloqueio
    user = new_user(ANA)
    save(db_session, user)
    code = issue(db_session, settings)
    with write_transaction(db_session):
        db_session.execute(update(User).where(User.id == user.id).values(**values))

    assert check(db_session, code) is VerifyFailure.INVALID_CODE
    [failed] = events(db_session, AuditEvent.LOGIN_FAILED)
    assert failed.user_id == user.id
    # A conta em exclusão continua sendo a do email: nenhuma conta nova
    assert count(db_session, User) == 1
    assert count(db_session, UserSession) == 0


def test_wrong_code_of_unknown_email_records_nothing(db_session, settings):
    code = issue(db_session, settings)

    assert check(db_session, wrong(code)) is VerifyFailure.INVALID_CODE

    assert events(db_session, AuditEvent.LOGIN_FAILED) == []


def run_in_parallel(engine, calls: int, action):
    """Roda `action(sessão)` em `calls` threads, cada uma com a sua conexão, ao mesmo tempo."""
    factory = create_session_factory(engine)
    barrier = threading.Barrier(calls)

    def task(_index):
        with factory() as session:
            barrier.wait()
            return action(session)

    with ThreadPoolExecutor(max_workers=calls) as executor:
        return list(executor.map(task, range(calls)))


def test_parallel_wrong_codes_never_pass_five_attempts(engine, db_session, settings):
    code = issue(db_session, settings)

    results = run_in_parallel(engine, 7, lambda session: check(session, wrong(code)))

    assert results == [VerifyFailure.INVALID_CODE] * 7
    db_session.rollback()
    assert db_session.scalar(select(LoginCodeRow.attempts)) == 5
    assert check(db_session, code) is VerifyFailure.INVALID_CODE


def test_parallel_first_access_creates_one_user(engine, db_session, settings):
    code = issue(db_session, settings)

    results = run_in_parallel(engine, 2, lambda session: check(session, code))

    logins = [result for result in results if isinstance(result, LoginResult)]
    assert len(logins) == 1
    assert results.count(VerifyFailure.INVALID_CODE) == 1
    db_session.rollback()
    assert count(db_session, User) == 1
    assert count(db_session, UserSession) == 1


def test_parallel_requests_create_one_code_per_minute(engine, db_session, settings):
    results = run_in_parallel(engine, 4, lambda session: ask(session, settings))

    outcomes = sorted(result.outcome for result in results)
    assert outcomes == [CodeRequestOutcome.RATE_LIMITED] * 3 + [CodeRequestOutcome.SENT]
    db_session.rollback()
    assert count(db_session, LoginCodeRow) == 1


# --- código de exclusão ---


def delete_code(db_session, settings, user: User) -> str:
    with write_transaction(db_session):
        result = request_delete_code(db_session, settings, user=user, ip="203.0.113.7")
    [outgoing] = result.emails
    assert isinstance(outgoing.email, DeleteCode)
    assert (outgoing.to, outgoing.locale) == (user.email, Locale(user.locale))
    return outgoing.email.code


def use(db_session, user: User, code: str) -> bool:
    with write_transaction(db_session):
        return use_delete_code(db_session, user=user, code=code)


def test_delete_code_round_trip(db_session, settings):
    user = new_user(ANA, locale="en")
    save(db_session, user)

    code = delete_code(db_session, settings, user)

    db_session.rollback()
    row = db_session.scalar(select(LoginCodeRow))
    assert (row.purpose, row.user_id) == ("delete_account", user.id)
    assert [event.user_id for event in events(db_session, AuditEvent.DELETE_CODE_REQUESTED)] == [
        user.id
    ]
    assert use(db_session, user, wrong(code)) is False
    assert use(db_session, user, code) is True
    # Uma vez só
    assert use(db_session, user, code) is False


def test_login_code_does_not_delete_the_account(db_session, settings):
    user = new_user(ANA)
    save(db_session, user)
    code = issue(db_session, settings)

    assert use(db_session, user, code) is False


def test_delete_code_of_the_email_previous_owner_is_refused(db_session, settings):
    # O email mudou de dono (troca pelo suporte): o código ligado à conta antiga não vale
    old = new_user(ANA)
    save(db_session, old)
    code = delete_code(db_session, settings, old)
    new_owner = new_user(ANA, id=old.id + 1)

    assert use(db_session, new_owner, code) is False


def test_delete_functions_require_a_write_transaction(db_session, settings):
    user = new_user(ANA)
    with pytest.raises(RuntimeError, match="write_transaction"):
        request_delete_code(db_session, settings, user=user, ip=None)
    with pytest.raises(RuntimeError, match="write_transaction"):
        use_delete_code(db_session, user=user, code="123456")


# --- sessão ---


def test_create_session_stores_only_the_hash(db_session):
    user = new_user()
    save(db_session, user)

    with write_transaction(db_session):
        token = create_session(db_session, user.id, now=NOW, ip=None, user_agent="x" * 600)
        empty = create_session(db_session, user.id, now=NOW, ip="198.51.100.1", user_agent=None)

    db_session.rollback()
    stored = {row.token_hash: row for row in db_session.scalars(select(UserSession))}
    assert set(stored) == {hash_secret(token), hash_secret(empty)}
    assert stored[hash_secret(token)].user_agent == "x" * 512
    assert stored[hash_secret(token)].expires_at == NOW + timedelta(days=60)
    assert stored[hash_secret(empty)].user_agent is None


def test_create_session_requires_a_write_transaction(db_session):
    with pytest.raises(RuntimeError, match="write_transaction"):
        create_session(db_session, 1, now=NOW, ip=None, user_agent=None)


def test_results_hide_secrets(db_session, settings):
    result = ask(db_session, settings)
    [outgoing] = result.emails
    login = check(db_session, outgoing.email.code)

    assert ANA not in repr(outgoing)
    assert outgoing.email.code not in repr(outgoing)
    assert login.token not in repr(login)


def test_constants_match_the_plan():
    assert timedelta(minutes=10) == service.CODE_LIFETIME
    assert service.MAX_CODE_ATTEMPTS == 5
    assert ((timedelta(minutes=1), 1), (timedelta(hours=1), 5)) == service.EMAIL_SEND_LIMITS
    assert timedelta(days=60) == service.SESSION_LIFETIME
