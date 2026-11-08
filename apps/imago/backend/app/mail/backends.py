"""Como o email sai: SMTP com STARTTLS (produção) ou console (só dev).

A escolha vem do `EMAIL_BACKEND` e a config recusa `console` fora de `APP_ENV=dev`, então o app
não sobe em produção com ele.
"""

import smtplib
import ssl
import sys
from email.message import EmailMessage
from typing import Protocol, TextIO

from pydantic import SecretStr

# Conexão, STARTTLS, login e envio: cada operação de rede espera no máximo isto
SMTP_TIMEOUT_SECONDS = 15.0


class MailBackend(Protocol):
    def send(self, message: EmailMessage) -> None:
        """Entrega a mensagem ou levanta exceção."""
        ...


class SmtpBackend:
    """Envio pelo provedor (Brevo, porta 587): STARTTLS obrigatório antes do login.

    Uma conexão por email. Se o servidor não oferecer STARTTLS, o `starttls()` levanta
    `SMTPNotSupportedError` e nada é enviado em texto claro. O certificado é verificado com o
    contexto padrão do Python (cadeia confiável e nome do host); `ssl_context` só existe para os
    testes confiarem na CA de teste do servidor falso.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: SecretStr,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float = SMTP_TIMEOUT_SECONDS,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._ssl_context = ssl.create_default_context() if ssl_context is None else ssl_context
        self._timeout = timeout

    def send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            smtp.starttls(context=self._ssl_context)
            smtp.login(self._user, self._password.get_secret_value())
            smtp.send_message(message)


class ConsoleBackend:
    """Só para desenvolvimento: escreve destinatário, assunto e texto no stderr.

    É o único lugar em que email e código aparecem fora da caixa de entrada, de propósito: em dev
    não há SMTP e quem desenvolve precisa do código para entrar. Escreve direto no stream, fora
    do logging, para não virar linha de log. A config proíbe este backend fora de dev.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def send(self, message: EmailMessage) -> None:
        body = message.get_body(preferencelist=("plain",))
        text = "" if body is None else body.get_content()
        stream = sys.stderr if self._stream is None else self._stream
        # Uma escrita só, para dois envios em paralelo não se misturarem
        stream.write(
            "----- email (console) -----\n"
            f"Para: {message['To']}\n"
            f"Assunto: {message['Subject']}\n\n"
            f"{text.rstrip()}\n"
            "----- fim do email -----\n"
        )
        stream.flush()
