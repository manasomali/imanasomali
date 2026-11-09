"""Cliente da API interna do imago (ETH-14): envio de email e busca de usuário por email.

O ethos não fala com o SMTP: todo email sai pelo imago (`POST /internal/mail`, tipo
`notification`), que põe o endereço atual da pessoa e aplica o teto de envio compartilhado entre
as aplicações (`imago-plan.md`, "envio de email e limite compartilhado"). O convite só vai para
quem já tem conta no imago (`POST /internal/users/lookup`, com o email no corpo, nunca na URL).

As chamadas vão direto ao `IMAGO_INTERNAL_URL` (loopback, nunca pelo nginx), com
`Authorization: Bearer <INTERNAL_API_TOKEN>` e timeout curto (`TIMEOUT`). O cliente ignora as
variáveis de proxy do ambiente (`trust_env=False`): o token nunca vai para outro host. Um cliente
só (`ImagoClient`) é criado na subida do app e usado por todas as threads (o pool de conexões do
httpx2 é seguro entre threads).

Log: o tipo do email e o resultado, nunca o destinatário (id ou email), o token, o corpo ou a
mensagem da exceção (que pode trazer a URL); de um erro de rede, só o tipo dele.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

import httpx2
from fastapi import Depends, Request
from pydantic import SecretStr

from app.mail.language import Locale
from app.models import MAX_USER_ID

logger = logging.getLogger(__name__)

# Segundos para conectar, mandar e receber cada chamada
TIMEOUT = 5.0
MAIL_PATH = "/internal/mail"
LOOKUP_PATH = "/internal/users/lookup"


class MailOutcome(StrEnum):
    """O que o imago fez com um email."""

    # 202: aceito (contado no teto; o SMTP sai em segundo plano no imago)
    ACCEPTED = "accepted"
    # 204: destinatário inativo ou em exclusão; nada sai e nada conta no teto
    SKIPPED = "skipped"
    # 429: o teto compartilhado não deixou; quem chama decide se tenta de novo depois
    REFUSED = "refused"
    # Rede, timeout, 5xx ou qualquer outra resposta: não saiu
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ImagoUser:
    """Resposta do `lookup`: o id da conta no imago e o idioma dela (para o email do convite)."""

    id: int
    locale: Locale


class ImagoUnavailableError(RuntimeError):
    """O `lookup` não teve resposta válida (rede, timeout, 5xx, corpo inesperado)."""


class ImagoClient:
    """Chamadas à API interna do imago. `transport` é para os testes (imago falso)."""

    def __init__(
        self,
        base_url: str,
        token: SecretStr,
        *,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._token = token
        self._client = httpx2.Client(
            base_url=base_url,
            timeout=TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _post(self, path: str, payload: dict[str, Any]) -> httpx2.Response:
        return self._client.post(
            path,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._token.get_secret_value()}",
                "Accept": "application/json",
            },
        )

    def send_mail(
        self, user_id: int, kind: str, *, subject: str, text: str, html: str
    ) -> MailOutcome:
        """Manda um email `notification` para o usuário `user_id`. Nunca levanta.

        `kind` (o tipo do email no catálogo) só vai para o log.
        """
        payload = {
            "kind": "notification",
            "user_id": user_id,
            "subject": subject,
            "text": text,
            "html": html,
        }
        try:
            response = self._post(MAIL_PATH, payload)
        except httpx2.HTTPError as exc:
            logger.error("email %s não enviado (%s)", kind, type(exc).__name__)
            return MailOutcome.FAILED
        status = response.status_code
        if status == 202:
            logger.info("email %s aceito pelo imago", kind)
            return MailOutcome.ACCEPTED
        if status == 204:
            logger.info("email %s não enviado: destinatário inativo no imago", kind)
            return MailOutcome.SKIPPED
        if status == 429:
            logger.warning("email %s recusado pelo teto de envio do imago", kind)
            return MailOutcome.REFUSED
        logger.error("email %s não enviado (imago respondeu %d)", kind, status)
        return MailOutcome.FAILED

    def lookup_user(self, email: str) -> ImagoUser | None:
        """A conta ativa do imago com esse email (já normalizado), ou None (404).

        Levanta `ImagoUnavailableError` sem resposta válida: o convite não pode decidir sem ela.
        """
        try:
            response = self._post(LOOKUP_PATH, {"email": email})
        except httpx2.HTTPError as exc:
            logger.error("busca de usuário no imago falhou (%s)", type(exc).__name__)
            raise ImagoUnavailableError from None
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.error(
                "busca de usuário no imago falhou (imago respondeu %d)", response.status_code
            )
            raise ImagoUnavailableError
        user = _parse_user(response)
        if user is None:
            logger.error("busca de usuário no imago falhou (resposta inválida)")
            raise ImagoUnavailableError
        return user


def _parse_user(response: httpx2.Response) -> ImagoUser | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    user_id, locale = body.get("id"), body.get("locale")
    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or not 1 <= user_id <= MAX_USER_ID
        or locale not in tuple(Locale)
    ):
        return None
    return ImagoUser(id=user_id, locale=Locale(locale))


def get_imago(request: Request) -> ImagoClient:
    """Dependência do FastAPI: o cliente criado na subida do app."""
    return request.app.state.imago


ImagoDep = Annotated[ImagoClient, Depends(get_imago)]
