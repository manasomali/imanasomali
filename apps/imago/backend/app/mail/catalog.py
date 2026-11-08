"""Catálogo fechado dos emails do próprio imago: um tipo por email, com os dados que o texto usa.

Só emails de conta e de segurança. Nada de email em massa: o catálogo não tem aviso para grupos
nem link de descadastro. Os emails das aplicações (convites, alertas, avisos) não passam por aqui:
chegam prontos pelo `POST /internal/mail` (`app/internal/router.py`). Email novo do imago entra
aqui, em `Email` e nos textos de `templates.py` (pt e en).

Cada tipo diz em `mail_kind` como conta no teto de envio (`app/mail/quota.py`): `code` (códigos)
ou `account` (avisos da conta). O aviso de teto ao suporte (`SendCapReached`) fica fora da
contagem (`mail_kind = None`).

Os dados chegam prontos de quem chama. O módulo não lê o banco. Campos com email ou código ficam
fora do `repr`, para não vazarem num traceback.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, Literal

from app.mail.kinds import MailKind

type CapWindow = Literal["hour", "day"]

_CODE_RE = re.compile(r"[0-9]{6}")


class EmailKind(StrEnum):
    LOGIN_CODE = "login_code"
    DELETE_CODE = "delete_code"
    ACCOUNT_DELETED = "account_deleted"
    EMAIL_CHANGED_OLD = "email_changed_old"
    EMAIL_CHANGED_NEW = "email_changed_new"
    SEND_CAP_REACHED = "send_cap_reached"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _require_code(code: str) -> None:
    # Só o valor que generate_code() produz; nunca o hash nem outra coisa por engano
    _require(_CODE_RE.fullmatch(code) is not None, "o código precisa ter 6 dígitos")


@dataclass(frozen=True, slots=True, kw_only=True)
class LoginCode:
    """Código de login (ETH-17)."""

    kind: ClassVar[EmailKind] = EmailKind.LOGIN_CODE
    mail_kind: ClassVar[MailKind | None] = MailKind.CODE
    code: str = field(repr=False)
    valid_minutes: int = 10

    def __post_init__(self) -> None:
        _require_code(self.code)
        _require(self.valid_minutes >= 1, "a validade precisa ser de pelo menos 1 minuto")


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteCode:
    """Código para confirmar a exclusão da conta (ETH-61)."""

    kind: ClassVar[EmailKind] = EmailKind.DELETE_CODE
    mail_kind: ClassVar[MailKind | None] = MailKind.CODE
    code: str = field(repr=False)
    valid_minutes: int = 10

    def __post_init__(self) -> None:
        _require_code(self.code)
        _require(self.valid_minutes >= 1, "a validade precisa ser de pelo menos 1 minuto")


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountDeleted:
    """Aviso de conta excluída, pela própria pessoa ou pelo admin (ETH-61, ETH-62)."""

    kind: ClassVar[EmailKind] = EmailKind.ACCOUNT_DELETED
    mail_kind: ClassVar[MailKind | None] = MailKind.ACCOUNT


@dataclass(frozen=True, slots=True, kw_only=True)
class EmailChangedOld:
    """Aviso ao email antigo depois da troca feita pelo suporte (ETH-62)."""

    kind: ClassVar[EmailKind] = EmailKind.EMAIL_CHANGED_OLD
    mail_kind: ClassVar[MailKind | None] = MailKind.ACCOUNT
    new_email: str = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class EmailChangedNew:
    """Aviso ao email novo depois da troca feita pelo suporte (ETH-62)."""

    kind: ClassVar[EmailKind] = EmailKind.EMAIL_CHANGED_NEW
    mail_kind: ClassVar[MailKind | None] = MailKind.ACCOUNT


@dataclass(frozen=True, slots=True, kw_only=True)
class SendCapReached:
    """Aviso ao SUPPORT_EMAIL: o teto de envio bateu para um código ou email de conta (ETH-58).

    Fica fora da contagem do teto e sai no máximo uma vez por hora (`app/mail/quota.py`).
    """

    kind: ClassVar[EmailKind] = EmailKind.SEND_CAP_REACHED
    mail_kind: ClassVar[MailKind | None] = None
    window: CapWindow
    limit: int

    def __post_init__(self) -> None:
        _require(self.window in ("hour", "day"), "janela inválida")


type Email = (
    LoginCode | DeleteCode | AccountDeleted | EmailChangedOld | EmailChangedNew | SendCapReached
)
