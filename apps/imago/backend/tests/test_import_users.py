"""`python -m app.cli import-users -` (ETH-64): as contas do `export-users` do ethos."""

import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from sqlalchemy import select

from app.cli import main
from app.config import ENV_VARS
from app.db import write_transaction
from app.import_users import (
    FIELDS,
    MAX_LINE_LENGTH,
    ImportFailure,
    import_accounts,
    parse_accounts,
)
from app.models import MAX_ACCOUNT_ID, User
from tests.auth_helpers import cookie, login
from tests.conftest import BACKEND_DIR
from tests.factories import count, new_user, save
from tests.test_cli import env_for

NOW = datetime(2026, 11, 8, 21, 0, tzinfo=UTC)


def record(account_id: int = 7, email: str = "ana@example.com", **values: Any) -> dict[str, Any]:
    """Uma conta como o `export-users` do ethos escreve."""
    return {
        "id": account_id,
        "email": email,
        "is_active": True,
        "is_admin": False,
        "timezone": "America/Sao_Paulo",
        "locale": "pt",
        "created_at": "2026-01-31T12:00:00.000000Z",
        "last_login_at": None,
    } | values


def line(data: Any) -> str:
    # O mesmo json.dumps do exportador: ASCII, sem espaços
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))


EXPORT = [
    record(7, "ana@example.com", is_admin=True, last_login_at="2026-11-01T09:15:30.123456Z"),
    record(12, "bia@example.com", locale="en", timezone="Europe/Lisbon"),
    record(4503599627370496, "caio@example.com", is_active=False),
    record(MAX_ACCOUNT_ID, "davi@example.com", created_at="2025-06-01T00:00:00+00:00"),
]


@pytest.fixture
def env(settings, database) -> dict[str, str]:
    return env_for(settings)


@pytest.fixture
def stdin(monkeypatch) -> Callable[[str], None]:
    """Troca o stdin por um pipe (não terminal) com o texto em UTF-8."""

    def feed(content: str) -> None:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(content.encode())))

    return feed


def users(db_session) -> list[User]:
    db_session.rollback()
    return list(
        db_session.scalars(select(User).order_by(User.id).execution_options(populate_existing=True))
    )


def test_import_keeps_ids_emails_flags_and_dates(db_session, env, stdin, capsys):
    stdin("".join(f"{line(data)}\n" for data in EXPORT))

    with time_machine.travel(NOW, tick=False):
        assert main(["import-users", "-"], env) == 0

    out, err = capsys.readouterr()
    assert (out, err) == (
        "import-users: 4 contas importadas (3 ativas, 1 bloqueadas, 1 admins)\n",
        "",
    )
    imported = users(db_session)
    assert [
        (
            user.id,
            user.email,
            user.is_active,
            user.is_admin,
            user.timezone,
            user.locale,
            user.status,
        )
        for user in imported
    ] == [
        (7, "ana@example.com", True, True, "America/Sao_Paulo", "pt", "active"),
        (12, "bia@example.com", True, False, "Europe/Lisbon", "en", "active"),
        (4503599627370496, "caio@example.com", False, False, "America/Sao_Paulo", "pt", "active"),
        (MAX_ACCOUNT_ID, "davi@example.com", True, False, "America/Sao_Paulo", "pt", "active"),
    ]
    ana, *_, davi = imported
    assert ana.created_at == datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
    assert ana.last_login_at == datetime(2026, 11, 1, 9, 15, 30, 123456, tzinfo=UTC)
    assert davi.created_at == datetime(2025, 6, 1, tzinfo=UTC)
    assert davi.last_login_at is None
    # Sem aceite dos termos: o imago os pede no primeiro acesso
    assert all((u.terms_version, u.terms_accepted_at) == (None, None) for u in imported)
    assert all(u.updated_at == NOW for u in imported)


def test_imported_account_signs_in_and_must_accept_the_terms(env, stdin, client, outbox):
    stdin(line(record()) + "\n")
    assert main(["import-users", "-"], env) == 0

    token = login(client, outbox, "ana@example.com")

    me = client.get("/me", headers=cookie(token)).json()
    assert (me["id"], me["terms_pending"], me["terms_version"]) == (7, True, None)


def test_normalizes_the_email_like_the_login(db_session):
    [account] = parse_accounts([line(record(email="  Ana@Example.COM "))])

    assert account.email == "ana@example.com"


@pytest.mark.parametrize(
    ("existing", "reason"),
    [
        ({"id": 12, "email": "outra@example.com"}, "linha 2: o id 12 já existe no imago"),
        ({"id": 42, "email": "bia@example.com"}, "linha 2: o email já tem a conta 42 no imago"),
    ],
)
def test_existing_id_or_email_writes_nothing(db_session, env, stdin, capsys, existing, reason):
    save(db_session, new_user(**existing))
    stdin("".join(f"{line(data)}\n" for data in EXPORT))

    assert main(["import-users", "-"], env) == 1

    out, err = capsys.readouterr()
    assert (out, err) == ("", f"erro: {reason}; nada foi gravado\n")
    assert count(db_session, User) == 1


@pytest.mark.parametrize(
    ("lines", "reason"),
    [
        (
            [record(7), record(7, "outra@example.com")],
            "linha 2: id repetido na entrada (já estava na linha 1)",
        ),
        (
            [record(7), record(8, "ANA@example.com")],
            "linha 2: email repetido na entrada (já estava na linha 1)",
        ),
    ],
)
def test_repeated_id_or_email_in_the_input(lines, reason):
    with pytest.raises(ImportFailure, match=re.escape(reason)):
        parse_accounts(map(line, lines))


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (record(0), "id fora de 1 a 2\\^53 - 1"),
        (record(-1), "id fora de 1 a 2\\^53 - 1"),
        (record(MAX_ACCOUNT_ID + 1), "id fora de 1 a 2\\^53 - 1"),
        (record("7"), "id precisa ser um número inteiro"),
        (record(7.0), "id precisa ser um número inteiro"),
        (record(True), "id precisa ser um número inteiro"),
        (record(email="ana"), "email inválido"),
        (record(email="joão@example.com"), "email inválido"),
        (record(email=None), "email inválido"),
        (record(email="a" * 250 + "@x.io"), "email inválido"),
        (record(is_active="true"), "is_active precisa ser true ou false"),
        (record(is_admin=1), "is_admin precisa ser true ou false"),
        (record(timezone="Mars/Base"), "timezone não é um fuso IANA conhecido"),
        (record(timezone=None), "timezone não é um fuso IANA conhecido"),
        (record(locale="pt-BR"), "locale precisa ser pt ou en"),
        (record(locale=["pt"]), "locale precisa ser pt ou en"),
        (record(created_at="2026-01-31T12:00:00"), "created_at precisa ser uma data ISO 8601"),
        (
            record(created_at="2026-01-31T09:00:00-03:00"),
            "created_at precisa ser uma data ISO 8601",
        ),
        (record(created_at="ontem"), "created_at precisa ser uma data ISO 8601"),
        (record(created_at=None), "created_at precisa ser uma data ISO 8601"),
        (record(last_login_at="2026-13-01T00:00:00Z"), "last_login_at precisa ser uma data"),
        ({k: v for k, v in record().items() if k != "email"}, "faltam os campos email"),
        (record(sobra="x"), "1 campos desconhecidos"),
        ([record()], "não é um objeto JSON"),
    ],
)
def test_invalid_field_refuses_everything(data, reason):
    with pytest.raises(ImportFailure, match=reason) as raised:
        parse_accounts([line(record(1, "ok@example.com")), line(data)])
    assert str(raised.value).startswith("linha 2: ")
    # A mensagem nunca traz o valor recebido
    assert "joão" not in str(raised.value)


@pytest.mark.parametrize(
    "text",
    ["{", "nada", "x" * (MAX_LINE_LENGTH + 1), "[" * 3000 + "]" * 3000],
)
def test_lines_that_are_not_an_export_line(text):
    with pytest.raises(ImportFailure, match=r"linha 1: (não é JSON|linha longa demais)"):
        parse_accounts([text])


def test_blank_lines_are_skipped():
    accounts = parse_accounts(["\n", line(record()) + "\r\n", "   \n"])

    assert [(account.line, account.id) for account in accounts] == [(2, 7)]


def test_fields_match_the_exporter():
    assert tuple(record()) == FIELDS


def test_an_error_on_the_last_line_writes_nothing(db_session, env, stdin, capsys):
    stdin("".join(f"{line(data)}\n" for data in EXPORT) + line(record(99, locale="fr")) + "\n")

    assert main(["import-users", "-"], env) == 1

    assert capsys.readouterr().err == (
        "erro: linha 5: locale precisa ser pt ou en; nada foi gravado\n"
    )
    assert count(db_session, User) == 0


def test_import_needs_a_write_transaction(db_session):
    with pytest.raises(RuntimeError, match="fora de write_transaction"):
        import_accounts(db_session, parse_accounts([line(record())]), now=NOW)


def test_many_accounts_in_one_transaction(db_session):
    lines = [line(record(index, f"user{index}@example.com")) for index in range(1, 1201)]

    with write_transaction(db_session):
        summary = import_accounts(db_session, parse_accounts(lines), now=NOW)

    assert (summary.total, summary.active, summary.blocked, summary.admins) == (1200, 1200, 0, 0)
    assert count(db_session, User) == 1200

    # Um id da última leva (depois de 1000 contas) já existe: nada entra
    save(db_session, new_user("nova@example.com", id=5000))
    more = [line(record(index, f"mais{index}@example.com")) for index in range(4000, 5001)]
    with pytest.raises(ImportFailure, match="o id 5000 já existe"), write_transaction(db_session):
        import_accounts(db_session, parse_accounts(more), now=NOW)
    assert count(db_session, User) == 1201


def test_empty_input_is_refused(db_session, env, stdin, capsys):
    stdin("\n\n")

    assert main(["import-users", "-"], env) == 1
    assert capsys.readouterr().err == (
        "erro: entrada vazia; nada foi gravado (o export-users rodou?)\n"
    )


def test_a_terminal_is_refused(env, monkeypatch, capsys):
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())

    assert main(["import-users", "-"], env) == 1
    assert capsys.readouterr().err.startswith("erro: mande as contas pelo stdin")


def test_unreadable_input(env, monkeypatch, capsys):
    class Broken(io.BytesIO):
        def __iter__(self):
            raise OSError("disco")

    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(Broken()))

    assert main(["import-users", "-"], env) == 1
    assert capsys.readouterr().err == "erro: não consegui ler a entrada (OSError)\n"


@pytest.mark.parametrize("argv", [["import-users"], ["import-users", "contas.jsonl"]])
def test_only_stdin_is_accepted(env, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        main(argv, env)

    assert raised.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_runs_as_a_module_with_a_pipe(db_session, env):
    environ = {key: value for key, value in os.environ.items() if key not in ENV_VARS}

    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "import-users", "-"],
        cwd=BACKEND_DIR,
        env=environ | env | {"PYTHONIOENCODING": "utf-8"},
        input="".join(f"{line(data)}\n" for data in EXPORT).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert (result.returncode, result.stderr.decode()) == (0, "")
    out = result.stdout.decode()
    assert out.strip() == "import-users: 4 contas importadas (3 ativas, 1 bloqueadas, 1 admins)"
    # Só contagens: nenhum email na saída
    assert "@" not in out
    assert count(db_session, User) == 4
