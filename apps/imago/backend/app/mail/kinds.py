"""Tipos de email do teto de envio (`mail_log.kind`, `app/mail/quota.py`)."""

from enum import StrEnum


class MailKind(StrEnum):
    # Código de login e de exclusão de conta: usam a reserva do fim de cada janela
    CODE = "code"
    # Emails de conta (conta excluída, troca de email): também usam a reserva
    ACCOUNT = "account"
    # Convites, alertas e avisos das aplicações (POST /internal/mail): param antes da reserva
    NOTIFICATION = "notification"
