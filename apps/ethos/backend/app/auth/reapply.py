"""Reaplicar as exclusões de conta depois de restaurar um backup (`reapply-deletions`).

Um backup restaurado traz de volta as contas apagadas depois dele. Cada exclusão grava no log do
serviço (journald) só o id da conta (`DELETED_LOG_FORMAT` em `app/auth/deletion.py`), que o
`app/logs.py` formata assim, como sai no `journalctl -u app-ethos -o cat`:

    INFO app.auth.deletion: conta 42 excluída

`read_account_ids` lê essas linhas, misturadas com as outras do serviço (que são ignoradas), e
aceita também ids soltos, um por linha (`42`). `reapply_deletions` apaga de novo cada conta que
ainda existe (`deletion.reapply_deletion`: sem email e sem duplicar o `account_deleted`).

Ids que não se repetem: a tabela `users` usa AUTOINCREMENT, mas o contador (`sqlite_sequence`)
volta junto com o backup. Sem cuidado, uma conta nova depois do restore poderia ganhar o id de
uma conta apagada, e um restore seguinte apagaria a conta nova ao reaplicar o mesmo log. Por
isso o contador de `users` avança até o maior id lido, antes de qualquer exclusão.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import deletion
from app.auth.deletion import DELETED_LOG_FORMAT, Reapplied
from app.db import write_transaction
from app.models import User

# Teto de sanidade para um id lido. Nenhuma conta real chega perto, e o contador do AUTOINCREMENT
# avançado até ele (`protect_account_ids`) ainda deixa espaço de sobra: um id digitado errado não
# esgota os ids do SQLite (2^63 - 1), o que impediria qualquer cadastro novo
MAX_ACCOUNT_ID = 10**12 - 1

_ID = r"([1-9][0-9]{0,18})"
_BEFORE_ID, _AFTER_ID = DELETED_LOG_FORMAT.split("%d")
# O começo da mensagem, logo depois do nome do logger: a linha que fala de uma exclusão
_MARKER = re.compile(re.escape(f"{deletion.logger.name}: {_BEFORE_ID}"))
# A linha inteira, no formato do app/logs.py ("%(levelname)s %(name)s: %(message)s")
_DELETION_LINE = re.compile(
    re.escape(f"INFO {deletion.logger.name}: {_BEFORE_ID}") + _ID + re.escape(_AFTER_ID)
)
_LOOSE_ID = re.compile(_ID)
_DIGITS = re.compile(r"[+-]?[0-9]+")


class InputError(ValueError):
    """Linha que parece uma exclusão (ou um id) mas não está no formato esperado."""

    def __init__(self, line_number: int, reason: str) -> None:
        super().__init__(f"linha {line_number}: {reason}")


@dataclass(frozen=True, slots=True)
class AccountIds:
    """Ids lidos: cada um uma vez só, na ordem em que apareceram."""

    ids: tuple[int, ...]
    lines: int
    # Ocorrências a mais de um id já lido (contadas uma vez em `ids`)
    repeated: int


@dataclass(frozen=True, slots=True)
class ReapplyResult:
    deleted: tuple[int, ...]
    # Contas que não existem no banco (já apagadas): nada a fazer
    missing: tuple[int, ...]
    # Último admin ativo: não foi apagada (ver `deletion.reapply_deletion`)
    last_admin: tuple[int, ...]


def read_account_ids(lines: Iterable[str]) -> AccountIds:
    """Os ids das linhas de exclusão do journald e dos ids soltos, sem repetir.

    Outras linhas (requests, subida do uvicorn, migrações) são ignoradas. Levanta `InputError`
    se uma linha cita a exclusão fora do formato do `-o cat` (ex.: `journalctl` sem `-o cat`,
    com data e host na frente) ou se uma linha só de dígitos não é um id válido: nos dois casos,
    seguir em frente apagaria menos contas do que o log manda, sem ninguém perceber.
    """
    seen: dict[int, None] = {}
    total = repeated = 0
    for number, raw in enumerate(lines, start=1):
        total = number
        line = raw.strip()
        match = _DELETION_LINE.fullmatch(line) or _LOOSE_ID.fullmatch(line)
        if match is None:
            if _MARKER.search(line):
                raise InputError(number, "linha de exclusão fora do formato do journalctl -o cat")
            if _DIGITS.fullmatch(line):
                raise InputError(number, "id inválido (precisa ser um inteiro positivo)")
            continue
        account_id = int(match[1])
        if account_id > MAX_ACCOUNT_ID:
            raise InputError(number, "id grande demais")
        if account_id in seen:
            repeated += 1
        else:
            seen[account_id] = None
    return AccountIds(ids=tuple(seen), lines=total, repeated=repeated)


def reapply_deletions(session: Session, account_ids: Sequence[int]) -> ReapplyResult:
    """Apaga de novo as contas de `account_ids` que ainda existem, cada uma na sua transação.

    Antes, avança o contador de ids de `users` até o maior id da lista (ver o docstring do
    módulo). Idempotente: rodar de novo com a mesma lista não muda nada. Se falhar no meio
    (banco), as contas já apagadas ficam apagadas, e rodar de novo termina o resto.
    """
    if account_ids:
        protect_account_ids(session, max(account_ids))
    outcomes: dict[Reapplied, list[int]] = {outcome: [] for outcome in Reapplied}
    for account_id in account_ids:
        outcomes[deletion.reapply_deletion(session, account_id=account_id)].append(account_id)
    return ReapplyResult(
        deleted=tuple(outcomes[Reapplied.DELETED]),
        missing=tuple(outcomes[Reapplied.MISSING]),
        last_admin=tuple(outcomes[Reapplied.LAST_ADMIN]),
    )


def protect_account_ids(session: Session, highest: int) -> None:
    """Garante que uma conta nova nunca receba um id menor ou igual a `highest`.

    O AUTOINCREMENT do SQLite dá ao próximo id o maior entre o `seq` de `sqlite_sequence` e o
    maior id da tabela, mais 1. Só aumenta o `seq`, nunca diminui.
    """
    if not 1 <= highest <= MAX_ACCOUNT_ID:
        raise ValueError("id fora do intervalo")
    params = {"name": User.__tablename__, "highest": highest}
    with write_transaction(session):
        session.execute(
            text("UPDATE sqlite_sequence SET seq = :highest WHERE name = :name AND seq < :highest"),
            params,
        )
        # Tabela que nunca recebeu linha ainda não tem a sua linha no sqlite_sequence
        session.execute(
            text(
                "INSERT INTO sqlite_sequence (name, seq) SELECT :name, :highest "
                "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = :name)"
            ),
            params,
        )
