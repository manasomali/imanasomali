"""Importação das contas do ethos (`python -m app.cli import-users -`, ETH-64), uma vez só.

Na passagem do login do ethos para o imago, o `export-users` do ethos escreve no stdout uma linha
JSON por conta e, depois da última, uma linha final com o total, e um pipe as leva ao
`import-users -` (roteiro no apps/imago/README.md), sem arquivo em disco. Cada linha de conta tem
exatamente estes campos (o formato do exportador):

    {"id": 7, "email": "ana@example.com", "is_active": true, "is_admin": false,
     "timezone": "America/Sao_Paulo", "locale": "pt", "created_at": "2026-01-31T12:00:00.000000Z",
     "last_login_at": null}

e a linha final, exatamente estes dois (nenhum deles existe numa conta, então uma não passa pela
outra):

    {"end": true, "count": 4}

A linha final é o que diz que a entrada chegou inteira: se o export morre no meio (falta de
memória, erro no banco), o pipe fecha e o import recebe só parte das contas, sem ela. Por isso a
entrada precisa terminar nela, com o `count` igual ao número de contas lidas.

As contas mantêm os ids do ethos, para os dados delas lá continuarem ligados às mesmas pessoas.
Sessões e o aceite dos termos não passam: `terms_version` fica vazio, e todo mundo aceita os termos
do imago no primeiro acesso.

Tudo ou nada: `parse_accounts` confere a entrada inteira antes de abrir a transação, e
`import_accounts` grava numa transação só (BEGIN IMMEDIATE), depois de conferir nela que nenhum id
nem email já existe no imago. Nada é gravado se uma linha não é JSON, se falta ou sobra um campo,
se um valor é inválido (id de 1 a 2^53 - 1, email pela normalização do login, `is_active` e
`is_admin` booleanos, fuso IANA, idioma `pt` ou `en`, datas ISO 8601 em UTC), se um id ou email se
repete na entrada ou se já existe no imago, se falta a linha final, se o total dela não bate com as
contas lidas ou se vem qualquer linha (mesmo em branco) depois dela. As mensagens de erro dizem a
linha e o motivo (e o id da conta do imago que já existe), nunca um valor recebido (nem o email).
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import is_valid_timezone, normalize_email
from app.db import require_write_transaction
from app.mail.language import Locale
from app.models import MAX_ACCOUNT_ID, User, UserStatus

# Campos de cada linha, na ordem do `export-users` do ethos
FIELDS = (
    "id",
    "email",
    "is_active",
    "is_admin",
    "timezone",
    "locale",
    "created_at",
    "last_login_at",
)
# Campos da linha final, que fecha a saída do exportador: {"end": true, "count": <total>}
END_FIELDS = ("end", "count")
# Uma linha do exportador tem bem menos que isto; acima, não é uma linha dele
MAX_LINE_LENGTH = 4096
# Ids e emails por consulta ao conferir o que já existe (abaixo do limite de variáveis do SQLite)
_CHUNK = 500


class ImportFailure(ValueError):
    """Entrada recusada. A mensagem diz a linha (se o erro é de uma) e o motivo, nunca o valor."""

    def __init__(self, line_number: int | None, reason: str) -> None:
        super().__init__(reason if line_number is None else f"linha {line_number}: {reason}")


@dataclass(frozen=True, slots=True)
class ImportedAccount:
    line: int
    id: int
    email: str = field(repr=False)
    is_active: bool
    is_admin: bool
    timezone: str
    locale: str
    created_at: datetime
    last_login_at: datetime | None


@dataclass(frozen=True, slots=True)
class ImportSummary:
    total: int
    active: int
    blocked: int
    admins: int


def parse_accounts(lines: Iterable[str]) -> list[ImportedAccount]:
    """As contas da entrada, conferidas (ver o docstring do módulo).

    A entrada precisa terminar na linha final, com o total igual ao número de contas lidas. Linhas
    em branco antes dela são puladas; depois dela, nenhuma linha é aceita. Levanta `ImportFailure`
    no primeiro problema, com o número da linha (sem número quando falta a linha final).
    """
    accounts: list[ImportedAccount] = []
    ids: dict[int, int] = {}
    emails: dict[str, int] = {}
    # (número da linha, total) da linha final, quando ela chega
    end: tuple[int, int] | None = None
    for number, raw in enumerate(lines, start=1):
        if end is not None:
            raise ImportFailure(number, "linha depois da linha final do export-users")
        line = raw.strip()
        if not line:
            continue
        record = _json_object(number, line)
        if "end" in record:
            end = (number, _end_count(number, record))
            continue
        account = _account(number, record)
        if account.id in ids:
            raise ImportFailure(
                number, f"id repetido na entrada (já estava na linha {ids[account.id]})"
            )
        if account.email in emails:
            raise ImportFailure(
                number, f"email repetido na entrada (já estava na linha {emails[account.email]})"
            )
        ids[account.id] = emails[account.email] = number
        accounts.append(account)
    if end is None:
        # O export falhou antes de terminar (ou nem rodou): o pipe fechou sem a linha final
        raise ImportFailure(
            None,
            "a entrada acabou sem a linha final do export-users (ele falhou ou parou no meio?)",
        )
    end_number, total = end
    if total != len(accounts):
        # Só o número de contas lidas: o total recebido é um valor da entrada
        raise ImportFailure(
            end_number, f"o total da linha final não bate com as {len(accounts)} contas lidas"
        )
    return accounts


def _json_object(number: int, line: str) -> dict[str, Any]:
    if len(line) > MAX_LINE_LENGTH:
        raise ImportFailure(number, "linha longa demais")
    try:
        record = json.loads(line)
    except ValueError, RecursionError:
        raise ImportFailure(number, "não é JSON") from None
    if not isinstance(record, dict):
        raise ImportFailure(number, "não é um objeto JSON")
    return record


def _end_count(number: int, record: dict[str, Any]) -> int:
    """O total da linha final: exatamente `{"end": true, "count": <inteiro de 0 para cima>}`."""
    count = record.get("count")
    if (
        len(record) != len(END_FIELDS)
        or record["end"] is not True
        # bool é int no Python, mas true como total é sempre engano
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
    ):
        raise ImportFailure(
            number, 'linha final inválida (o formato é {"end": true, "count": <total>})'
        )
    return count


def _account(number: int, record: dict[str, Any]) -> ImportedAccount:
    missing = [name for name in FIELDS if name not in record]
    if missing:
        raise ImportFailure(number, f"faltam os campos {', '.join(missing)}")
    if len(record) != len(FIELDS):
        # Os nomes que sobraram não aparecem: vêm da entrada
        raise ImportFailure(number, f"{len(record) - len(FIELDS)} campos desconhecidos")
    return ImportedAccount(
        line=number,
        id=_account_id(number, record["id"]),
        email=_email(number, record["email"]),
        is_active=_bool(number, "is_active", record["is_active"]),
        is_admin=_bool(number, "is_admin", record["is_admin"]),
        timezone=_timezone(number, record["timezone"]),
        locale=_locale(number, record["locale"]),
        created_at=_instant(number, "created_at", record["created_at"]),
        last_login_at=(
            None
            if record["last_login_at"] is None
            else _instant(number, "last_login_at", record["last_login_at"])
        ),
    )


def _account_id(number: int, value: Any) -> int:
    # bool é int no Python, mas true como id é sempre engano
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImportFailure(number, "id precisa ser um número inteiro")
    if not 1 <= value <= MAX_ACCOUNT_ID:
        raise ImportFailure(number, "id fora de 1 a 2^53 - 1")
    return value


def _email(number: int, value: Any) -> str:
    email = normalize_email(value) if isinstance(value, str) else None
    if email is None:
        raise ImportFailure(number, "email inválido")
    return email


def _bool(number: int, name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ImportFailure(number, f"{name} precisa ser true ou false")
    return value


def _timezone(number: int, value: Any) -> str:
    if not isinstance(value, str) or not is_valid_timezone(value):
        raise ImportFailure(number, "timezone não é um fuso IANA conhecido")
    return value


def _locale(number: int, value: Any) -> str:
    if not isinstance(value, str) or value not in {locale.value for locale in Locale}:
        raise ImportFailure(number, "locale precisa ser pt ou en")
    return value


def _instant(number: int, name: str, value: Any) -> datetime:
    """Data ISO 8601 em UTC (com `Z` ou `+00:00`)."""
    try:
        instant = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        instant = None
    if instant is None or instant.utcoffset() != timedelta(0):
        raise ImportFailure(number, f"{name} precisa ser uma data ISO 8601 em UTC")
    return instant


def import_accounts(
    session: Session, accounts: Sequence[ImportedAccount], *, now: datetime
) -> ImportSummary:
    """Grava as contas, ou nenhuma se um id ou email já existe no imago (`ImportFailure`).

    Exige `write_transaction`: a conferência e a gravação ficam protegidas pela mesma trava, e o
    erro desfaz tudo.
    """
    require_write_transaction(session)
    by_id = {account.id: account for account in accounts}
    by_email = {account.email: account for account in accounts}
    for chunk in _chunks(list(by_id)):
        taken = session.scalars(select(User.id).where(User.id.in_(chunk))).first()
        if taken is not None:
            raise ImportFailure(by_id[taken].line, f"o id {taken} já existe no imago")
    for chunk in _chunks(list(by_email)):
        row = session.execute(select(User.id, User.email).where(User.email.in_(chunk))).first()
        if row is not None:
            # O id da conta do imago (nunca o email), para quem roda poder resolver
            raise ImportFailure(
                by_email[row.email].line, f"o email já tem a conta {row.id} no imago"
            )
    session.add_all(
        User(
            id=account.id,
            email=account.email,
            status=UserStatus.ACTIVE.value,
            is_active=account.is_active,
            is_admin=account.is_admin,
            timezone=account.timezone,
            locale=account.locale,
            # Sem aceite: os termos do imago são pedidos no primeiro acesso
            terms_version=None,
            terms_accepted_at=None,
            created_at=account.created_at,
            updated_at=now,
            last_login_at=account.last_login_at,
        )
        for account in accounts
    )
    return ImportSummary(
        total=len(accounts),
        active=sum(account.is_active for account in accounts),
        blocked=sum(not account.is_active for account in accounts),
        admins=sum(account.is_admin for account in accounts),
    )


def _chunks[T](values: list[T]) -> Iterable[list[T]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]
