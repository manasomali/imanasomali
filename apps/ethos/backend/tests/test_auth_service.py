import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth import service
from app.auth.security import hash_secret
from app.auth.service import (
    CodeRequestOutcome,
    LoginResult,
    VerifyFailure,
    create_session,
    is_valid_timezone,
    normalize_email,
    request_login_code,
    verify_login_code,
)
from app.db import create_session_factory, write_transaction
from app.mail.language import Locale
from app.models import LoginCode, User, UserSession
from tests.factories import count, new_user, save

ANA = "ana@example.com"
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ana@example.com", "ana@example.com"),
        ("  Ana@Example.COM\n", "ana@example.com"),
        ("\tJOÃO@exemplo.com.br ", "joão@exemplo.com.br"),
        ("", None),
        ("ana", None),
        ("ana@example", None),
        ("ana@@example.com", None),
        ("an a@example.com", None),
        ("ana@exam\x00ple.com", None),
        ("ana@exam​ple.com", None),
        ("<ana@example.com>", None),
        ("a" * 243 + "@example.com", None),
    ],
)
def test_normalize_email(value, expected):
    assert normalize_email(value) == expected


def test_normalize_email_accepts_254_characters():
    email = "a" * 242 + "@example.com"
    assert len(email) == 254
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
        ("/usr/share/zoneinfo/UTC", False),
        ("America/" + "X" * 64, False),
    ],
)
def test_is_valid_timezone(name, expected):
    assert is_valid_timezone(name) is expected


def issue(session, settings, email=ANA) -> str:
    result = request_login_code(session, settings, email=email, ip=None, accept_language=None)
    assert result.outcome is CodeRequestOutcome.SENT
    [outgoing] = result.emails
    return outgoing.email.code


def check(session, code, email=ANA, timezone="America/Sao_Paulo"):
    return verify_login_code(
        session,
        email=email,
        code=code,
        timezone=timezone,
        locale=Locale.PT,
        ip=None,
        user_agent=None,
    )


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
    wrong = f"{(int(code) + 1) % 10**6:06d}"

    results = run_in_parallel(engine, 7, lambda session: check(session, wrong))

    assert results == [VerifyFailure.INVALID_CODE] * 7
    db_session.rollback()
    assert db_session.scalar(select(LoginCode.attempts)) == 5
    # Esgotado: nem o código certo entra mais
    assert check(db_session, code) is VerifyFailure.INVALID_CODE


def test_parallel_first_access_creates_one_user(engine, db_session, settings):
    code = issue(db_session, settings)

    results = run_in_parallel(engine, 2, lambda session: check(session, code))

    logins = [result for result in results if isinstance(result, LoginResult)]
    assert len(logins) == 1
    assert logins[0].new_account is True
    assert results.count(VerifyFailure.INVALID_CODE) == 1
    db_session.rollback()
    assert count(db_session, User) == 1
    assert count(db_session, UserSession) == 1


def test_parallel_requests_create_one_code_per_minute(engine, db_session, settings):
    def ask(session):
        return request_login_code(session, settings, email=ANA, ip=None, accept_language=None)

    results = run_in_parallel(engine, 4, ask)

    outcomes = sorted(result.outcome for result in results)
    assert outcomes == [CodeRequestOutcome.RATE_LIMITED] * 3 + [CodeRequestOutcome.SENT]
    db_session.rollback()
    assert count(db_session, LoginCode) == 1


def test_login_result_and_outgoing_email_hide_secrets(db_session, settings):
    result = request_login_code(db_session, settings, email=ANA, ip=None, accept_language=None)
    [outgoing] = result.emails
    login = check(db_session, outgoing.email.code)

    assert ANA not in repr(outgoing)
    assert outgoing.email.code not in repr(outgoing)
    assert login.token not in repr(login)


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
    assert stored[hash_secret(empty)].ip == "198.51.100.1"


def test_create_session_requires_a_write_transaction(db_session):
    with pytest.raises(RuntimeError, match="write_transaction"):
        create_session(db_session, 1, now=NOW, ip=None, user_agent=None)


def test_constants_match_the_plan():
    assert timedelta(minutes=10) == service.CODE_LIFETIME
    assert service.MAX_CODE_ATTEMPTS == 5
    assert ((timedelta(minutes=1), 1), (timedelta(hours=1), 5)) == service.EMAIL_SEND_LIMITS
    assert timedelta(hours=1) == service.SUPPORT_ALERT_INTERVAL
    assert timedelta(days=60) == service.SESSION_LIFETIME
