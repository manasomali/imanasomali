"""Auditoria: grava eventos no `audit_log` dentro da transação de escrita corrente.

Uso, sempre dentro do `write_transaction` que faz a mudança auditada:

    with write_transaction(session):
        session.add(mark)
        session.flush()  # para ter o mark.id
        audit.record(
            session,
            AuditEvent.MARK_CREATED,
            user_id=user.id,
            habit_id=habit.id,
            details={"mark_id": mark.id},
        )

O `record` não faz commit nem flush: o evento entra no commit do bloco junto com a mudança, e um
rollback desfaz os dois. Fora do `write_transaction`, levanta RuntimeError.

Regras:

- `event`: só os da lista fechada `AuditEvent`. Os eventos de login e de conta são do imago: o
  ethos guarda a auditoria dos hábitos, das marcações, do compartilhamento, dos alertas e do admin.
- `user_id`: quem fez. `None` em evento sem autor (sistema) ou quando o autor não existe mais.
- Sem IP: o ethos não grava IP (a coluna `audit_log.ip` é legado, vazia, e sai na migração 0007).
- `details`: dicionário JSON com o que mudou, pequeno (`MAX_DETAILS_LENGTH`). São recusados:
  valores que não são JSON (datetime, set, bytes, float infinito...), chaves que não são texto e
  qualquer chave, em qualquer nível, cujo nome contém code, token, cookie, password, secret etc.
  (`code`, `login_code`, `codeHash`, `Set-Cookie`, `session_token`...). Só os nomes das chaves são
  conferidos: nunca ponha código, token ou cookie num valor. Para registrar a mudança de um campo
  com nome sensível (ex.: a sigla `habits.code`), use o nome como valor:
  `{"changes": [{"field": "code", "old": "AB", "new": "CD"}]}`.
- `habit_id`: hábito a que o evento se refere. A coluna tem ON DELETE CASCADE: apagar o hábito
  apaga a auditoria dele (decisão do plano). Por isso o evento que precisa sobreviver ao hábito,
  como `habit_deleted`, vai com `habit_id=None` e o id em `details` (`{"habit_id": 7}`).

Nunca ponha no `details` código, token, cookie nem senha, e evite email: a exclusão dos dados de
uma conta (`app/internal/deletion.py`) tira todo texto com "@" do `details` das linhas que ficam e
citam a conta. Evento sobre outra conta (de admin) leva o id dela em `details.target_user_id`, que
é como a exclusão acha a linha; ids de conta em eventos de hábito vão em `author_id` ou
`member_id`, que a exclusão troca por `null`.
"""

import json
import math
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.db import require_write_transaction
from app.models import AuditLog


class AuditEvent(StrEnum):
    """Lista fechada de eventos. Comentário: quem grava e o que vai em `details`."""

    # --- Hábitos: ficam enquanto o hábito existe (habit_id preenchido) ---
    HABIT_CREATED = "habit_created"  # ETH-20
    # O que mudou na configuração (ETH-20)
    HABIT_UPDATED = "habit_updated"
    # habit_id=None e {"habit_id": n}: precisa sobreviver ao CASCADE (ETH-20)
    HABIT_DELETED = "habit_deleted"
    HABIT_PAUSED = "habit_paused"  # ETH-21
    HABIT_RESUMED = "habit_resumed"  # ETH-21
    HABIT_ARCHIVED = "habit_archived"  # ETH-21
    HABIT_UNARCHIVED = "habit_unarchived"  # ETH-21

    # --- Marcações (ETH-22): ficam enquanto o hábito existe ---
    MARK_CREATED = "mark_created"
    MARK_UPDATED = "mark_updated"
    MARK_DELETED = "mark_deleted"

    # --- Compartilhamento (ETH-24): ficam enquanto o hábito existe ---
    INVITE_CREATED = "invite_created"
    INVITE_CANCELED = "invite_canceled"
    INVITE_ACCEPTED = "invite_accepted"
    INVITE_DECLINED = "invite_declined"
    MEMBER_LEFT = "member_left"
    MEMBER_REMOVED = "member_removed"
    MEMBER_ROLE_CHANGED = "member_role_changed"

    # --- Alertas (ETH-26) ---
    # Configuração de alerta do membro salva (habit_id preenchido); {"changes": [...]}
    ALERT_UPDATED = "alert_updated"

    # --- Admin (ETH-28): ficam. As contas (bloquear, trocar email, excluir) são do imago ---
    # Admin abriu o conteúdo dos hábitos de um usuário; {"target_user_id": n, "habit_id"?: n}
    # (sem habit_id na coluna)
    ADMIN_VIEWED_HABITS = "admin_viewed_habits"
    # {"banner_id", "text_pt", "text_en", "starts_at", "ends_at"} (ETH-28)
    BANNER_CREATED = "banner_created"
    # {"banner_id", "changes": [{field, old, new}]} (ETH-28)
    BANNER_UPDATED = "banner_updated"
    BANNER_ENDED = "banner_ended"


# Tamanho máximo do details serializado (caracteres) e profundidade máxima de aninhamento
MAX_DETAILS_LENGTH = 16_384
MAX_DETAILS_DEPTH = 8

# Trechos de nome de chave recusados no details, procurados no nome em minúsculas e só com
# letras e números ("Set-Cookie" -> "setcookie", "codeHash" -> "codehash")
_SENSITIVE_KEY_PARTS = (
    "code",
    "token",
    "cookie",
    "password",
    "passwd",
    "pwd",
    "secret",
    "authorization",
    "credential",
)
# Tamanho máximo do nome de chave citado na mensagem de erro
_KEY_IN_MESSAGE = 64


class AuditError(ValueError):
    """Evento fora da lista ou details inválido. A mensagem nunca traz valores."""


def record(
    session: Session,
    event: AuditEvent | str,
    *,
    user_id: int | None,
    habit_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Adiciona o evento à transação de escrita corrente e devolve a linha (ainda sem flush).

    Levanta RuntimeError fora de `write_transaction` e AuditError com evento desconhecido ou
    `details` recusado (ver o docstring do módulo). `created_at` é a hora atual.
    """
    require_write_transaction(session)
    entry = AuditLog(
        event=_check_event(event).value,
        user_id=_check_id("user_id", user_id),
        habit_id=_check_id("habit_id", habit_id),
        details=_check_details(details),
    )
    session.add(entry)
    return entry


def _check_event(event: AuditEvent | str) -> AuditEvent:
    try:
        return AuditEvent(event)
    except ValueError:
        raise AuditError(f"evento de auditoria desconhecido: {str(event)[:64]!r}") from None


def _check_id(name: str, value: int | None) -> int | None:
    # bool é int no Python, mas True como id é sempre engano
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise TypeError(f"{name} precisa ser int ou None, recebeu {type(value).__name__}")
    return value


def _check_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if details is None:
        return {}
    if not isinstance(details, dict):
        raise AuditError(f"details precisa ser dict, recebeu {type(details).__name__}")
    _check_value(details, "details", 0)
    # Mesmo formato que o tipo JSON do SQLAlchemy grava (ensure_ascii): o tamanho é o do banco
    serialized = json.dumps(details, allow_nan=False)
    if len(serialized) > MAX_DETAILS_LENGTH:
        raise AuditError(f"details grande demais ({len(serialized)} caracteres)")
    # Cópia independente: mudar o dict de quem chamou depois não muda o evento, e tuplas e enums
    # viram listas e valores simples, como vão ficar no banco
    return json.loads(serialized)


def _check_value(value: Any, path: str, depth: int) -> None:
    # A profundidade máxima também barra dict que contém a si mesmo (recursão infinita)
    if depth > MAX_DETAILS_DEPTH:
        raise AuditError(f"details aninhado demais em {path}")
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        # NaN e infinito não são JSON válido (o CHECK json_valid recusaria)
        if not math.isfinite(value):
            raise AuditError(f"número não finito em {path}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AuditError(f"chave que não é texto em {path} ({type(key).__name__})")
            child = f"{path}.{key[:_KEY_IN_MESSAGE]}"
            if _is_sensitive_key(key):
                raise AuditError(f"chave sensível em details: {child}")
            _check_value(item, child, depth + 1)
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _check_value(item, f"{path}[{index}]", depth + 1)
        return
    raise AuditError(f"valor não serializável em {path} ({type(value).__name__})")


def _is_sensitive_key(key: str) -> bool:
    normalized = "".join(char for char in key.casefold() if char.isalnum())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)
