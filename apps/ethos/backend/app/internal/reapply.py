"""Reaplicar, depois de restaurar um backup do ethos, as exclusões de antes do imago.

Até a passagem do login para o imago (ETH-64), cada exclusão de conta no ethos gravava no log do
serviço (journald) só o id da conta, nesta linha do `journalctl -u app-ethos -o cat`:

    INFO app.auth.deletion: conta 42 excluída

Um backup restaurado de antes de uma dessas exclusões traz a conta de volta (como linha de
`app_users`, depois das migrações). `read_account_ids` lê essas linhas, misturadas com as outras do
serviço (que são ignoradas), e aceita também ids soltos, um por linha (`42`). `reapply_deletions`
apaga de novo os dados de cada id (`app/internal/service.py`, `delete_user_data`), **sem email**:
os membros já foram avisados na exclusão original.

Depois da passagem, quem coordena a exclusão é o imago, e o `reapply-deletions` dele (journal do
`app-imago`) refaz as exclusões chamando o `POST /internal/users/{id}/delete` de cada aplicação.
Este fica só para as exclusões de antes da passagem (`infra/RESTORE.md`).
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.identity import is_valid_user_id
from app.internal.service import delete_user_data

# Logger e mensagem das exclusões do login próprio: as linhas antigas do journald têm este texto,
# que não muda mais
LEGACY_LOGGER = "app.auth.deletion"
_BEFORE_ID, _AFTER_ID = "conta ", " excluída"

_ID = r"([1-9][0-9]{0,18})"
# O começo da mensagem, logo depois do nome do logger: a linha que fala de uma exclusão
_MARKER = re.compile(re.escape(f"{LEGACY_LOGGER}: {_BEFORE_ID}"))
# A linha inteira, no formato do app/logs.py ("%(levelname)s %(name)s: %(message)s")
_DELETION_LINE = re.compile(
    re.escape(f"INFO {LEGACY_LOGGER}: {_BEFORE_ID}") + _ID + re.escape(_AFTER_ID)
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
    # Contas que ainda tinham linha em app_users e foram apagadas de novo
    deleted: tuple[int, ...]
    # Sem linha em app_users (já apagadas): só os convites recebidos que sobrassem
    missing: tuple[int, ...]


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
        if not is_valid_user_id(account_id):
            raise InputError(number, "id grande demais")
        if account_id in seen:
            repeated += 1
        else:
            seen[account_id] = None
    return AccountIds(ids=tuple(seen), lines=total, repeated=repeated)


def reapply_deletions(session: Session, account_ids: Sequence[int]) -> ReapplyResult:
    """Apaga de novo os dados de cada id, cada um na sua transação, sem email.

    Idempotente: rodar de novo com a mesma lista não muda nada. Se falhar no meio (banco), as
    contas já apagadas ficam apagadas, e rodar de novo termina o resto.
    """
    deleted: list[int] = []
    missing: list[int] = []
    for account_id in account_ids:
        # Os avisos que a exclusão devolve são descartados: nada é mandado
        result = delete_user_data(session, user_id=account_id)
        (deleted if result.existed else missing).append(account_id)
    return ReapplyResult(deleted=tuple(deleted), missing=tuple(missing))
