"""Reaplicar as exclusões de conta depois de restaurar um backup (`reapply-deletions`, ETH-61).

Um backup restaurado (do imago ou de uma aplicação) traz de volta as contas apagadas depois dele.
O passo 1 de cada exclusão grava no log do `app-imago` (journald) só o id da conta
(`DELETED_LOG_FORMAT` em `app/deletion.py`), que o `app/logs.py` formata assim, como sai no
`journalctl -u app-imago -o cat`:

    INFO app.deletion: conta 42 excluída

`read_account_ids` lê essas linhas, misturadas com as outras do serviço (que são ignoradas), e
aceita também ids soltos, um por linha (`42`), para os testes e o ensaio. `reapply_deletions`
refaz cada exclusão, sem mandar email:

- conta que ainda existe no imago (backup do imago): a exclusão inteira de novo, com
  `account_deletion_started` `{"reapplied": true}` e as tarefas `delete` de todas as aplicações,
  tentadas na hora. A que falhar fica pendente para o `run-tasks`, e o passo 3 roda quando a última
  terminar, também sem email. Nenhuma linha nova no log: a da exclusão original continua lá;
- conta que já não existe no imago (backup de uma aplicação, ou o imago já reaplicou): o `delete`
  de cada aplicação do `IMAGO_APPS`, na hora, sem tarefa (não há conta a que ligar uma). Uma falha
  aqui não fica gravada: quem roda vê a contagem e roda de novo;
- o último admin ativo não é apagado (`LAST_ADMIN`), como na API: depois de um restore, o admin
  que ficou pode ainda não ser admin no banco restaurado. Quem roda é avisado; rodar de novo depois
  de um `create-admin` apaga.

Idempotente: as aplicações aceitam o `delete` de um id que não conhecem, e o imago ignora o que já
apagou. Com o `IMAGO_APPS` vazio (o ensaio numa cópia), só o banco do imago muda.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app import deletion
from app.db import write_transaction
from app.deletion import DELETED_LOG_FORMAT, DeletionMode
from app.internal.tasks import TaskContext, call_app, request_tasks, run_pending
from app.models import MAX_ACCOUNT_ID, TaskAction, UserStatus

_ID = r"([1-9][0-9]*)"
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


def parse_account_id(value: str) -> int:
    """Um id de conta (1 a 2^53 - 1) escrito em decimal, sem sinal nem zero à esquerda."""
    if _LOOSE_ID.fullmatch(value) is None or int(value) > MAX_ACCOUNT_ID:
        raise ValueError("id de conta inválido (precisa ser um inteiro de 1 a 2^53 - 1)")
    return int(value)


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
        try:
            account_id = parse_account_id(match[1])
        except ValueError:
            raise InputError(number, "id maior que 2^53 - 1") from None
        if account_id in seen:
            repeated += 1
        else:
            seen[account_id] = None
    return AccountIds(ids=tuple(seen), lines=total, repeated=repeated)


class Reapplied(StrEnum):
    """O que o `reapply_deletion` fez com uma conta."""

    # A conta existia no imago: a exclusão recomeçou (e terminou, se as aplicações responderam)
    DELETED = "deleted"
    # A conta já não existia no imago: só as aplicações foram chamadas
    MISSING = "missing"
    # Último admin ativo: nada foi feito
    LAST_ADMIN = "last_admin"


@dataclass(frozen=True, slots=True)
class ReapplyResult:
    deleted: tuple[int, ...] = ()
    missing: tuple[int, ...] = ()
    last_admin: tuple[int, ...] = ()
    # Exclusões que ainda esperam uma aplicação: tarefas pendentes, para o run-tasks
    pending: tuple[int, ...] = ()
    # Chamadas que falharam para contas que já não existem no imago: (conta, aplicação, motivo).
    # Não ficam gravadas em lugar nenhum: rode o reapply-deletions de novo
    failed_calls: tuple[tuple[int, str, str], ...] = ()


def reapply_deletions(context: TaskContext, account_ids: Sequence[int]) -> ReapplyResult:
    """Refaz a exclusão de cada conta de `account_ids` (ver o docstring do módulo).

    Cada conta na sua transação: se falhar no meio (banco), as já feitas ficam, e rodar de novo
    termina o resto.
    """
    outcomes: dict[Reapplied, list[int]] = {outcome: [] for outcome in Reapplied}
    pending: list[int] = []
    failed_calls: list[tuple[int, str, str]] = []
    for account_id in account_ids:
        outcome = _restart(context, account_id)
        outcomes[outcome].append(account_id)
        if outcome is Reapplied.MISSING:
            failed_calls.extend(_delete_in_apps(context, account_id))
        elif outcome is Reapplied.DELETED:
            run_pending(context, user_id=account_id, action=TaskAction.DELETE)
            with context.session_factory() as session:
                if deletion.finish_deletion(session, context.settings, account_id) is None:
                    pending.append(account_id)
    return ReapplyResult(
        deleted=tuple(outcomes[Reapplied.DELETED]),
        missing=tuple(outcomes[Reapplied.MISSING]),
        last_admin=tuple(outcomes[Reapplied.LAST_ADMIN]),
        pending=tuple(pending),
        failed_calls=tuple(failed_calls),
    )


def _restart(context: TaskContext, account_id: int) -> Reapplied:
    """Recomeça a exclusão no imago (passo 1, sem email e sem linha no log), se a conta existe."""
    with context.session_factory() as session, write_transaction(session):
        user = deletion.reload_user(session, account_id)
        if user is None:
            return Reapplied.MISSING
        if deletion.is_last_admin(session, user):
            return Reapplied.LAST_ADMIN
        if user.status == UserStatus.DELETING.value:
            # Exclusão em andamento no backup: o passo 3 vai sem email, e as aplicações que já
            # tinham apagado recebem o delete de novo (o banco delas pode ser o restaurado)
            request_tasks(session, context.settings, user_id=account_id, action=TaskAction.DELETE)
            deletion.record_started(session, account_id, actor_id=None, mode=DeletionMode.REAPPLIED)
        else:
            deletion.start_deletion(
                session, context.settings, user, actor_id=None, mode=DeletionMode.REAPPLIED
            )
    return Reapplied.DELETED


def _delete_in_apps(context: TaskContext, account_id: int) -> list[tuple[int, str, str]]:
    """O `delete` da conta em cada aplicação, na hora. Devolve as falhas."""
    if not context.settings.imago_apps:
        return []
    with context.http_client() as client:
        failures = []
        for name in context.settings.app_names:
            error = call_app(client, context.settings, name, account_id, TaskAction.DELETE)
            if error is not None:
                failures.append((account_id, name, error))
    return failures
