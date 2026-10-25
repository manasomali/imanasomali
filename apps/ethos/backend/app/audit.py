"""Auditoria: grava eventos no `audit_log` dentro da transação de escrita corrente.

Uso, sempre dentro do `write_transaction` que faz a mudança auditada:

    with write_transaction(session):
        session.add(mark)
        session.flush()  # para ter o mark.id
        audit.record(
            session,
            AuditEvent.MARK_CREATED,
            user_id=user.id,
            ip=client_ip,
            habit_id=habit.id,
            details={"mark_id": mark.id},
        )

O `record` não faz commit nem flush: o evento entra no commit do bloco junto com a mudança, e um
rollback desfaz os dois. Fora do `write_transaction`, levanta RuntimeError.

Regras:

- `event`: só os da lista fechada `AuditEvent`. Evento novo entra aqui, decidindo se é de auth
  (`AUTH_EVENTS`), porque é isso que define a retenção (`app/retention.py`).
- `user_id`: quem fez. `None` em evento sem autor (sistema) ou quando o autor não existe mais.
- `ip`: o IP do cliente (já validado e normalizado aqui). Some depois de 90 dias (cleanup).
- `details`: dicionário JSON com o que mudou, pequeno (`MAX_DETAILS_LENGTH`). São recusados:
  valores que não são JSON (datetime, set, bytes, float infinito...), chaves que não são texto e
  qualquer chave, em qualquer nível, cujo nome contém code, token, cookie, password, secret etc.
  (`code`, `login_code`, `codeHash`, `Set-Cookie`, `session_token`...). Só os nomes das chaves são
  conferidos: nunca ponha código, token ou cookie num valor. Para registrar a mudança de um campo
  com nome sensível (ex.: a sigla `habits.code`), use o nome como valor:
  `{"changes": [{"field": "code", "old": "AB", "new": "CD"}]}`.
- `habit_id`: hábito a que o evento se refere. A coluna tem ON DELETE CASCADE: apagar o hábito
  apaga a auditoria dele (decisão do plano). Por isso o evento que precisa sobreviver ao hábito,
  como `habit_deleted`, vai com `habit_id=None` e o id em `details` (`{"habit_id": 7}`). O mesmo
  vale para `account_deleted`: `user_id` é quem apagou (`None` quando foi o próprio usuário, cuja
  linha já não existe) e o id da conta vai em `details` (`{"account_id": 7, "by_admin": false}`),
  sem email. A exclusão reaplicada depois de um restore (`reapply-deletions`) vai com `user_id`
  `None` e `{"account_id": 7, "reapplied": true}`: quem apagou não se sabe mais.

Nunca ponha no `details` código, token, cookie nem senha, e evite email: a exclusão de conta
(`app/auth/deletion.py`) tira todo texto com "@" do `details` das linhas que ficam e citam a
conta. Evento sobre outra conta (de admin) leva o id dela em `details.target_user_id`, que é
como a exclusão acha a linha; ids de conta em eventos de hábito vão em `author_id` ou
`member_id`, que a exclusão troca por `null`.
"""

import ipaddress
import json
import math
from datetime import timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.db import require_write_transaction
from app.models import IP_MAX_LENGTH, AuditLog


class AuditEvent(StrEnum):
    """Lista fechada de eventos. Comentário: quem grava e o que vai em `details`."""

    # --- Auth: apagados depois de 90 dias (AUTH_EVENTS) ---
    # Pedido de código de login para uma conta existente (ETH-17)
    CODE_REQUESTED = "code_requested"
    # Código verificado e sessão criada; {"new_account": bool} (ETH-17)
    LOGIN = "login"
    # Código errado, vencido ou esgotado para uma conta existente (ETH-17)
    LOGIN_FAILED = "login_failed"
    # Sessão atual encerrada (ETH-18)
    LOGOUT = "logout"
    # Todas as sessões do usuário encerradas; {"sessions": n} (ETH-18)
    LOGOUT_ALL = "logout_all"
    # Pedido de código para excluir a conta (ETH-27)
    DELETE_CODE_REQUESTED = "delete_code_requested"
    # Teto global de envio de códigos atingido e aviso mandado ao SUPPORT_EMAIL; evento do
    # sistema (user_id=None), {"window": "hour" | "day", "limit": n}. A última linha dele é o que
    # segura o aviso em no máximo 1 por hora (ETH-17)
    SEND_CAP_REACHED = "send_cap_reached"

    # --- Conta: ficam enquanto a conta existe ---
    # Aceite de uma versão nova dos termos; {"terms_version": "..."} (ETH-18)
    TERMS_ACCEPTED = "terms_accepted"
    # Fuso ou idioma alterado; o que mudou (ETH-18)
    PROFILE_UPDATED = "profile_updated"
    # Conta apagada; user_id = quem apagou (None se o próprio),
    # {"account_id": n, "by_admin": bool} (ETH-27/28) ou {"account_id": n, "reapplied": true}
    ACCOUNT_DELETED = "account_deleted"

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

    # --- Admin (ETH-19, ETH-28): ficam ---
    # is_admin ligado pelo CLI create-admin; user_id = a conta promovida (ETH-19)
    ADMIN_CREATED = "admin_created"
    # Admin abriu o conteúdo dos hábitos de um usuário; {"target_user_id": n, "habit_id"?: n}
    # (ETH-28; sem habit_id na coluna)
    ADMIN_VIEWED_HABITS = "admin_viewed_habits"
    # {"target_user_id": n, "sessions": n apagadas} (ETH-28)
    USER_BLOCKED = "user_blocked"
    # {"target_user_id": n} (ETH-28)
    USER_UNBLOCKED = "user_unblocked"
    # Troca de email pelo suporte; user_id = o admin,
    # {"target_user_id", "old_email", "new_email", "sessions"} (ETH-28)
    EMAIL_CHANGED = "email_changed"
    # {"banner_id", "text_pt", "text_en", "starts_at", "ends_at"} (ETH-28)
    BANNER_CREATED = "banner_created"
    # {"banner_id", "changes": [{field, old, new}]} (ETH-28)
    BANNER_UPDATED = "banner_updated"
    BANNER_ENDED = "banner_ended"


# Eventos de auth: apagados pelo cleanup depois de AUTH_EVENT_RETENTION. Os outros (conta,
# hábitos, marcações, compartilhamento, alertas e admin) ficam; só o IP deles some
AUTH_EVENTS: frozenset[AuditEvent] = frozenset(
    {
        AuditEvent.CODE_REQUESTED,
        AuditEvent.LOGIN,
        AuditEvent.LOGIN_FAILED,
        AuditEvent.LOGOUT,
        AuditEvent.LOGOUT_ALL,
        AuditEvent.DELETE_CODE_REQUESTED,
        AuditEvent.SEND_CAP_REACHED,
    }
)

# Retenção do plano ("retenção de dados")
AUTH_EVENT_RETENTION = timedelta(days=90)
IP_RETENTION = timedelta(days=90)

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
    """Evento fora da lista ou details/ip inválido. A mensagem nunca traz valores."""


def record(
    session: Session,
    event: AuditEvent | str,
    *,
    user_id: int | None,
    ip: str | None = None,
    habit_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Adiciona o evento à transação de escrita corrente e devolve a linha (ainda sem flush).

    Levanta RuntimeError fora de `write_transaction` e AuditError com evento desconhecido, IP
    inválido ou `details` recusado (ver o docstring do módulo). `created_at` é a hora atual.
    """
    require_write_transaction(session)
    entry = AuditLog(
        event=_check_event(event).value,
        user_id=_check_id("user_id", user_id),
        habit_id=_check_id("habit_id", habit_id),
        ip=_check_ip(ip),
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


def _check_ip(ip: str | None) -> str | None:
    if ip is None:
        return None
    if not isinstance(ip, str):
        # ip_address aceita int (1 -> 0.0.0.1), o que esconderia um engano de quem chama
        raise AuditError(f"ip precisa ser texto, recebeu {type(ip).__name__}")
    try:
        normalized = str(ipaddress.ip_address(ip))
    except ValueError:
        raise AuditError("ip inválido") from None
    if len(normalized) > IP_MAX_LENGTH:
        raise AuditError("ip longo demais")
    return normalized


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
