"""Dependências de autenticação: quem é o usuário do request, termos aceitos e admin.

Para os endpoints:

- `CurrentUser`: o padrão de todo endpoint do app. Exige sessão válida e a versão atual dos
  termos aceita (`app/terms.py`); sem aceite, 403 `terms_not_accepted`.
- `AdminUser`: `CurrentUser` com `is_admin`; usuário comum recebe 403 `forbidden`.
- `CurrentUserAnyTerms`: sessão válida, com ou sem os termos atuais. Só para `GET/PATCH /auth/me`
  e `POST /auth/me/terms`, que precisam funcionar antes do aceite.
- `CurrentSession`: sessão válida, sem renovar. Só para o logout, que apaga a sessão.

Sessão (`sessions`): o cookie `__Host-ethos_session` traz o token, e a linha é achada por
`hash_secret(token)`. Sem cookie, token desconhecido, sessão vencida (`expires_at <= agora`) ou
usuário inativo: 401 `unauthorized`, sempre igual. Nada é escrito nesses casos (a limpeza das
vencidas é do `cleanup`).

Renovação: a sessão dura `SESSION_LIFETIME` (60 dias) desde o último uso, mas `last_seen_at` e
`expires_at` só são gravados quando o último registro tem pelo menos `RENEWAL_INTERVAL` (1 dia):
no máximo uma escrita por sessão por dia. A conferência normal é uma leitura só (BEGIN DEFERRED);
a escrita abre um `write_transaction` (BEGIN IMMEDIATE), que encerra essa leitura, e repete a
leitura e a conferência dentro dele: outro request pode ter renovado, apagado a sessão ou
bloqueado o usuário no meio. Ao renovar, o cookie sai de novo com o `Max-Age` cheio. O cookie
renovado só chega ao navegador se o endpoint devolver dados (não um `Response` pronto) e não der
erro; senão a próxima renovação, no dia seguinte, manda de novo.

`is_admin`, `is_active` e `terms_version` são lidos do banco em todo request (nada fica em
cache), então bloquear, tirar o admin ou trocar a versão dos termos vale no request seguinte.

Os objetos devolvidos são da sessão do banco do request: um `write_transaction` no endpoint
encerra a leitura e os expira (o próximo acesso relê a linha). Releia o usuário dentro da
transação de escrita quando a decisão depender dele.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.cookies import SESSION_COOKIE_NAME, set_session_cookie
from app.auth.security import hash_secret
from app.auth.service import SESSION_LIFETIME
from app.db import SessionDep, write_transaction
from app.errors import ApiError, ErrorCode
from app.models import User, UserSession, utcnow
from app.terms import TERMS_VERSION

# Intervalo mínimo entre duas gravações de last_seen_at/expires_at da mesma sessão
RENEWAL_INTERVAL = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class Authenticated:
    """Usuário do request e o hash do token da sessão dele (para o logout)."""

    user: User
    token_hash: str = field(repr=False)


def _unauthorized() -> ApiError:
    return ApiError(401, ErrorCode.UNAUTHORIZED)


def _session_token(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise _unauthorized()
    return token


def _load(session: Session, token_hash: str, now: datetime) -> tuple[UserSession, User]:
    """Sessão válida e o usuário dela, ou 401."""
    row = session.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == token_hash)
        # Relê as linhas mesmo que a sessão do banco já tenha os objetos de outra transação
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise _unauthorized()
    user_session, user = row
    if user_session.expires_at <= now or not user.is_active:
        raise _unauthorized()
    return user_session, user


def _needs_renewal(user_session: UserSession, now: datetime) -> bool:
    return now - user_session.last_seen_at >= RENEWAL_INTERVAL


def authenticate(session: Session, token_hash: str, *, renew: bool) -> tuple[Authenticated, bool]:
    """Confere a sessão pelo hash do token e, se `renew`, renova quando passou um dia.

    Devolve o usuário autenticado e se a sessão foi renovada agora. Levanta 401 (`ApiError`).
    """
    now = utcnow()
    user_session, user = _load(session, token_hash, now)
    if not renew or not _needs_renewal(user_session, now):
        return Authenticated(user=user, token_hash=token_hash), False
    with write_transaction(session):
        # A hora é lida de novo já com a trava de escrita
        now = utcnow()
        user_session, user = _load(session, token_hash, now)
        renewed = _needs_renewal(user_session, now)
        if renewed:
            user_session.last_seen_at = now
            user_session.expires_at = now + SESSION_LIFETIME
    return Authenticated(user=user, token_hash=token_hash), renewed


def current_session(request: Request, session: SessionDep) -> Authenticated:
    """Sessão válida, sem renovar e sem conferir os termos (logout)."""
    token_hash = hash_secret(_session_token(request))
    authenticated, _ = authenticate(session, token_hash, renew=False)
    return authenticated


CurrentSession = Annotated[Authenticated, Depends(current_session)]


def current_user_any_terms(request: Request, response: Response, session: SessionDep) -> User:
    """Usuário da sessão, renovando a sessão (e o cookie) uma vez por dia. Não confere termos."""
    token = _session_token(request)
    authenticated, renewed = authenticate(session, hash_secret(token), renew=True)
    if renewed:
        set_session_cookie(response, token)
    return authenticated.user


CurrentUserAnyTerms = Annotated[User, Depends(current_user_any_terms)]


def terms_pending(user: User) -> bool:
    """Diz se o usuário ainda não aceitou a versão atual dos termos."""
    return user.terms_version != TERMS_VERSION


def current_user(user: CurrentUserAnyTerms) -> User:
    """Usuário da sessão com a versão atual dos termos aceita; senão 403 `terms_not_accepted`."""
    if terms_pending(user):
        raise ApiError(403, ErrorCode.TERMS_NOT_ACCEPTED)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_admin(user: CurrentUser) -> User:
    """`CurrentUser` com `is_admin` (lido do banco neste request); senão 403 `forbidden`."""
    if not user.is_admin:
        raise ApiError(403, ErrorCode.FORBIDDEN)
    return user


AdminUser = Annotated[User, Depends(require_admin)]
