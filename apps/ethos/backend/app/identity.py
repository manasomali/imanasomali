"""Quem é o usuário: os headers `X-User-*` que o nginx põe a partir do imago (ETH-60).

O login é do imago (`imago-plan.md`, "como as aplicações sabem quem é o usuário"). Em cada request
de `/api/ethos/`, o nginx pergunta ao imago (`auth_request`) e repassa a resposta em headers:

- `X-User-Id`: o id do usuário no imago, em decimal (1 a 2^53 - 1);
- `X-User-Email`: o email, ASCII e minúsculo;
- `X-User-Locale`: `pt` ou `en`;
- `X-User-Timezone`: fuso IANA;
- `X-User-Admin`: `1`, só para admin.

O nginx sempre define os cinco a partir da resposta do imago (vazios no `/health`), o que apaga
qualquer `X-User-*` mandado pelo navegador. Isso só é seguro porque o ethos escuta em 127.0.0.1 e
só o nginx chega nele. Sem sessão válida, conta ativa e termos aceitos, o imago não manda nenhum:
as rotas públicas (o banner ativo) continuam funcionando, e as que exigem login respondem 401
`not_authenticated` (o front manda para `/imago/entrar?next=<caminho>`).

Header malformado (id fora do formato, email que não é ASCII minúsculo, idioma desconhecido, fuso
que não existe, `X-User-Admin` diferente de `1`, header repetido, ou o id sem algum dos outros):
401 `not_authenticated` e uma linha de aviso no log com o nome do header, nunca o valor. Header
vazio conta como ausente (o nginx não manda header com valor vazio).

`app_users`: a cada request com login, a linha do usuário é criada (primeiro acesso) ou
atualizada quando email, idioma ou fuso mudaram; senão nada é gravado. A conferência é uma
leitura; a escrita abre um `write_transaction` (BEGIN IMMEDIATE) e relê a linha dentro dele, então
dois requests ao mesmo tempo no primeiro acesso não colidem.

Dependências dos endpoints:

- `CurrentUser` (`require_user`): o usuário do request (`Identity`), com a linha de `app_users`
  em dia; sem login, 401. Os dados vêm dos headers deste request: o admin e o fuso valem na hora.
- `AdminUser` (`require_admin`): `CurrentUser` com `X-User-Admin: 1`; senão 403 `forbidden`.

Middlewares, que rodam antes de ler o corpo ou abrir o banco:

- `RequestGuardMiddleware`: proteção contra CSRF e o token da API interna. Toda request que não
  seja GET, HEAD ou OPTIONS precisa de exatamente um header `Origin` igual à origem do `APP_URL`
  (`settings.app_origin`: esquema + host + porta, se não for a padrão; o navegador manda a
  origem normalizada, sem caminho), senão 403 `forbidden`. A exceção é `/internal/*`, que não
  vem do navegador (o imago chama direto em 127.0.0.1; o nginx responde 404 para
  `/api/ethos/internal/`): ali vale o `Authorization: Bearer <INTERNAL_API_TOKEN>`, em qualquer
  método, comparado com `hmac.compare_digest` (sem ou errado: 401 `unauthorized`).
- `LegacySessionCookieMiddleware`: o cookie do login próprio de antes do imago
  (`__Host-ethos_session`), quando chega, é apagado na resposta (`Max-Age=0`).
"""

import hmac
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cache
from typing import Annotated
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import is_email
from app.db import SessionDep, write_transaction
from app.errors import ApiError, ErrorCode, error_response
from app.mail.language import Locale
from app.models import MAX_USER_ID, TIMEZONE_MAX_LENGTH, AppUser, utcnow

logger = logging.getLogger(__name__)

USER_ID_HEADER = "x-user-id"
USER_EMAIL_HEADER = "x-user-email"
USER_LOCALE_HEADER = "x-user-locale"
USER_TIMEZONE_HEADER = "x-user-timezone"
USER_ADMIN_HEADER = "x-user-admin"
IDENTITY_HEADERS = (
    USER_ID_HEADER,
    USER_EMAIL_HEADER,
    USER_LOCALE_HEADER,
    USER_TIMEZONE_HEADER,
    USER_ADMIN_HEADER,
)
# Métodos que não mudam nada e por isso não passam pela checagem de Origin
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Rotas da API interna (sem o root_path), chamadas pelo imago com o token
INTERNAL_PREFIX = "/internal/"
# Cookie de sessão do login próprio do ethos, de antes do imago
LEGACY_SESSION_COOKIE = "__Host-ethos_session"
# Os mesmos atributos da gravação (sem `Secure` e `Path=/`, o navegador recusaria apagar um
# cookie `__Host-`)
_CLEAR_LEGACY_COOKIE = (
    b"set-cookie",
    (
        f'{LEGACY_SESSION_COOKIE}=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; '
        "Max-Age=0; Path=/; SameSite=lax; Secure"
    ).encode("latin-1"),
)
# Decimal sem zero à esquerda; o teto (2^53 - 1) é conferido depois
_USER_ID_RE = re.compile(r"[1-9][0-9]{0,15}")


@dataclass(frozen=True, slots=True)
class Identity:
    """O usuário do request, como o imago o mandou."""

    id: int
    email: str = field(repr=False)
    locale: Locale
    timezone: str
    is_admin: bool


class MalformedIdentityError(ValueError):
    """Header `X-User-*` fora do formato. A mensagem é só o nome do header, nunca o valor."""


# Arquivos da base de fusos do sistema que o available_timezones() lista, mas não são fusos
NOT_TIMEZONES = frozenset({"localtime"})


@cache
def _timezones() -> frozenset[str]:
    # Lê a base de fusos uma vez por processo (a do sistema e a do pacote tzdata). No
    # Debian/Ubuntu, a do sistema tem o `localtime`, link para o /etc/localtime, que não é fuso
    # IANA (o navegador não conhece). A mesma regra do imago, que manda o X-User-Timezone
    return frozenset(available_timezones() - NOT_TIMEZONES)


def is_valid_timezone(name: str) -> bool:
    """Diz se `name` é um fuso IANA conhecido, escrito como na base (ex.: America/Sao_Paulo).

    Consulta a lista de fusos em vez de tentar `ZoneInfo(name)`, que aceitaria nomes de arquivos
    da base que não são fusos.
    """
    return len(name) <= TIMEZONE_MAX_LENGTH and name in _timezones()


def is_valid_user_id(value: int) -> bool:
    """Id de usuário do imago: inteiro de 1 a 2^53 - 1 (nunca bool)."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_USER_ID


def is_identity_email(value: str) -> bool:
    """Email como o imago guarda: ASCII, minúsculo, sem espaço nas pontas, na forma simples."""
    return value.isascii() and value == value.strip().lower() and is_email(value)


def _single(headers: Headers, name: str) -> str | None:
    values = [value for value in headers.getlist(name) if value]
    if len(values) > 1:
        # Dois headers iguais não vêm do nginx: recusa em vez de escolher um
        raise MalformedIdentityError(name)
    return values[0] if values else None


def read_identity(headers: Headers) -> Identity | None:
    """O usuário dos headers, ou None sem `X-User-Id`. Levanta `MalformedIdentityError`."""
    values = {name: _single(headers, name) for name in IDENTITY_HEADERS}
    raw_id = values[USER_ID_HEADER]
    if raw_id is None:
        others = [name for name in IDENTITY_HEADERS if values[name] is not None]
        if others:
            # Os outros sem o id: o imago manda todos ou nenhum
            raise MalformedIdentityError(USER_ID_HEADER)
        return None
    if _USER_ID_RE.fullmatch(raw_id) is None or not is_valid_user_id(int(raw_id)):
        raise MalformedIdentityError(USER_ID_HEADER)
    email = values[USER_EMAIL_HEADER]
    if email is None or not is_identity_email(email):
        raise MalformedIdentityError(USER_EMAIL_HEADER)
    locale = values[USER_LOCALE_HEADER]
    if locale not in tuple(Locale):
        raise MalformedIdentityError(USER_LOCALE_HEADER)
    timezone = values[USER_TIMEZONE_HEADER]
    if timezone is None or not is_valid_timezone(timezone):
        raise MalformedIdentityError(USER_TIMEZONE_HEADER)
    admin = values[USER_ADMIN_HEADER]
    if admin not in (None, "1"):
        raise MalformedIdentityError(USER_ADMIN_HEADER)
    return Identity(
        id=int(raw_id),
        email=email,
        locale=Locale(locale),
        timezone=timezone,
        is_admin=admin == "1",
    )


def _not_authenticated() -> ApiError:
    return ApiError(401, ErrorCode.NOT_AUTHENTICATED)


def sync_app_user(session: Session, identity: Identity) -> None:
    """Cria ou atualiza a linha de `app_users` do usuário; nada é gravado se ela já está em dia."""
    current = session.execute(
        select(AppUser.email, AppUser.locale, AppUser.timezone).where(AppUser.id == identity.id)
    ).one_or_none()
    wanted = (identity.email, identity.locale.value, identity.timezone)
    if current is not None and tuple(current) == wanted:
        return
    with write_transaction(session):
        # Relê com a trava: outro request pode ter criado ou mudado a linha no meio
        user = session.get(AppUser, identity.id, populate_existing=True)
        if user is None:
            now = utcnow()
            session.add(
                AppUser(
                    id=identity.id,
                    email=identity.email,
                    locale=identity.locale.value,
                    timezone=identity.timezone,
                    first_seen_at=now,
                    updated_at=now,
                )
            )
        elif (user.email, user.locale, user.timezone) != wanted:
            user.email, user.locale, user.timezone = wanted


def require_user(request: Request, session: SessionDep) -> Identity:
    """O usuário do request, com `app_users` em dia; 401 `not_authenticated` sem login."""
    try:
        identity = read_identity(request.headers)
    except MalformedIdentityError as exc:
        # Só o nome do header: o valor pode ser o email
        logger.warning("header %s inválido; request recusado com 401", exc)
        raise _not_authenticated() from None
    if identity is None:
        raise _not_authenticated()
    sync_app_user(session, identity)
    return identity


CurrentUser = Annotated[Identity, Depends(require_user)]


def require_admin(user: CurrentUser) -> Identity:
    """`CurrentUser` com `X-User-Admin: 1`; senão 403 `forbidden`."""
    if not user.is_admin:
        raise ApiError(403, ErrorCode.FORBIDDEN)
    return user


AdminUser = Annotated[Identity, Depends(require_admin)]


# --- GET /me ---

router = APIRouter(tags=["me"])


class MeOut(BaseModel):
    id: int
    email: str
    locale: Locale
    timezone: str
    is_admin: bool


@router.get("/me")
def get_me(user: CurrentUser) -> MeOut:
    """O usuário do request, como o imago o mandou (o front mostra e usa o fuso dele)."""
    return MeOut(
        id=user.id,
        email=user.email,
        locale=user.locale,
        timezone=user.timezone,
        is_admin=user.is_admin,
    )


# --- middlewares ---


def route_path(scope: Scope) -> str:
    """O caminho do request sem o `root_path` (/api/ethos), como o roteador o vê."""
    path: str = scope["path"]
    root: str = scope.get("root_path", "")
    if root and path.startswith(root) and path[len(root) : len(root) + 1] in ("", "/"):
        return path[len(root) :] or "/"
    return path


def is_internal(scope: Scope) -> bool:
    return route_path(scope).startswith(INTERNAL_PREFIX)


def _header_values(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> list[bytes]:
    # O ASGI entrega os nomes em minúsculas e os valores em bytes
    return [value for header, value in headers if header == name]


def origin_allowed(headers: Iterable[tuple[bytes, bytes]], expected: str) -> bool:
    """Diz se há exatamente um header `Origin` e ele é igual a `expected`."""
    values = _header_values(headers, b"origin")
    # latin-1 decodifica qualquer valor. Dois headers Origin não vêm de um navegador: recusa
    return len(values) == 1 and values[0].decode("latin-1") == expected


def internal_token_valid(headers: Iterable[tuple[bytes, bytes]], expected: str) -> bool:
    """Diz se há exatamente um `Authorization: Bearer <token>` e o token é `expected`.

    Compara com `hmac.compare_digest` (tempo constante), em bytes: um valor fora do ASCII não
    levanta exceção, só não confere.
    """
    values = _header_values(headers, b"authorization")
    if len(values) != 1:
        return False
    scheme, _, token = values[0].partition(b" ")
    if scheme.lower() != b"bearer" or not token:
        return False
    return hmac.compare_digest(token, expected.encode("ascii"))


class RequestGuardMiddleware:
    """Middleware ASGI: Origin nas escritas do navegador e o token em `/internal/*`.

    Lê a config de `app.state` (carregada no lifespan). Responde antes de ler o corpo.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = scope["app"].state.settings
        if is_internal(scope):
            token = settings.internal_api_token.get_secret_value()
            if not internal_token_valid(scope["headers"], token):
                response = error_response(
                    401, ErrorCode.UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
                )
                await response(scope, receive, send)
                return
        elif scope["method"] not in SAFE_METHODS and not origin_allowed(
            scope["headers"], settings.app_origin
        ):
            response = error_response(403, ErrorCode.FORBIDDEN)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def has_legacy_cookie(headers: Iterable[tuple[bytes, bytes]]) -> bool:
    return any(
        LEGACY_SESSION_COOKIE in cookie_parser(value.decode("latin-1"))
        for value in _header_values(headers, b"cookie")
    )


class LegacySessionCookieMiddleware:
    """Middleware ASGI: apaga o cookie `__Host-ethos_session` de quem ainda o manda."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not has_legacy_cookie(scope["headers"]):
            await self.app(scope, receive, send)
            return

        async def send_clearing(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message["headers"], _CLEAR_LEGACY_COOKIE]}
            await send(message)

        await self.app(scope, receive, send_clearing)
