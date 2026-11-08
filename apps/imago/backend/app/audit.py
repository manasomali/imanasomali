"""Auditoria: grava eventos no `audit_log` dentro da transação de escrita corrente.

Uso, sempre dentro do `write_transaction` que faz a mudança auditada:

    with write_transaction(session):
        user.timezone = "Europe/Lisbon"
        audit.record(
            session,
            AuditEvent.PROFILE_UPDATED,
            user_id=user.id,
            ip=client_ip,
            details={"changes": [{"field": "timezone", "old": "UTC", "new": "Europe/Lisbon"}]},
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
  conferidos: nunca ponha código, token ou cookie num valor.
- Evento sobre outra conta (ações do admin) leva o id dela em `details.target_user_id`: é por
  ele que a exclusão da conta (ETH-61) acha as linhas que citam a conta, para tirar o IP e os
  emails delas. `account_deletion_started` (passo 1 da exclusão) leva a conta em
  `target_user_id`; `account_deleted` vai com `user_id` = quem apagou (`None` quando foi a própria
  pessoa, cuja linha já não existe) e o id da conta em `details` (`{"account_id": 7,
  "by_admin": false}`), sem email nem IP.

Nunca ponha no `details` código, token, cookie nem senha, e evite email (só a troca de email pelo
admin leva os dois endereços, que a exclusão da conta apaga).
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
    # Pedido de código para excluir a conta (ETH-61)
    DELETE_CODE_REQUESTED = "delete_code_requested"
    # Teto de envio atingido por um código ou email de conta e aviso mandado ao SUPPORT_EMAIL;
    # evento do sistema (user_id=None), {"window": "hour" | "day", "limit": n, "kind": "..."}.
    # A última linha dele segura o aviso em no máximo 1 por hora (ETH-58)
    SEND_CAP_REACHED = "send_cap_reached"

    # --- Conta: ficam enquanto a conta existe ---
    # Aceite de uma versão nova dos termos; {"terms_version": "..."} (ETH-18)
    TERMS_ACCEPTED = "terms_accepted"
    # Fuso ou idioma alterado; {"changes": [{"field", "old", "new"}]} (ETH-18)
    PROFILE_UPDATED = "profile_updated"
    # Passo 1 da exclusão da conta (app/deletion.py); user_id = quem pediu (a própria conta, o
    # admin, ou None no reapply-deletions), {"target_user_id": n, "by_admin": bool} ou
    # {"target_user_id": n, "reapplied": true}. É por ele que o passo 3, que pode rodar depois
    # (no run-tasks), sabe quem apagou e se manda o email; o passo 3 o apaga (ETH-61)
    ACCOUNT_DELETION_STARTED = "account_deletion_started"
    # Conta apagada (fica depois da exclusão); user_id = quem apagou (None se a própria pessoa),
    # {"account_id": n, "by_admin": bool} ou {"account_id": n, "reapplied": true} (ETH-61)
    ACCOUNT_DELETED = "account_deleted"

    # --- Admin: ficam ---
    # is_admin ligado pelo CLI create-admin; user_id = a conta promovida, {"via": "cli"} (ETH-19)
    ADMIN_CREATED = "admin_created"
    # user_id = o admin; {"target_user_id": n, "sessions": n apagadas} (ETH-62)
    USER_BLOCKED = "user_blocked"
    # user_id = o admin; {"target_user_id": n} (ETH-62)
    USER_UNBLOCKED = "user_unblocked"
    # Troca de email pelo suporte; user_id = o admin,
    # {"target_user_id", "old_email", "new_email", "sessions"} (ETH-62)
    EMAIL_CHANGED = "email_changed"


# Eventos de auth: apagados pelo cleanup depois de AUTH_EVENT_RETENTION. Os outros (conta e admin)
# ficam; só o IP deles some
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
