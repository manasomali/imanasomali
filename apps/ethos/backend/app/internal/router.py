"""API interna do ethos, chamada pelo imago (ETH-60, ETH-27).

Só direto em `127.0.0.1:3001`: o nginx responde 404 para `/api/ethos/internal/`. Toda rota
exige `Authorization: Bearer <INTERNAL_API_TOKEN>` (o token do ethos, o mesmo que ele usa para
chamar o imago), comparado com `hmac.compare_digest`: sem ele ou errado, 401 `unauthorized`. A
conferência acontece no `RequestGuardMiddleware` (`app/identity.py`), antes de ler o corpo, e de
novo na dependência deste router, para uma rota nova nunca ficar aberta. Sem checagem de `Origin`
(não vem do navegador).

- `POST /internal/users/{id}/refresh` com `{email, locale, timezone}`: atualiza a cópia da conta
  em `app_users` (só se mudou). 200 `{"status": "ok"}`, inclusive para id que o ethos não
  conhece (nada é criado). Valor inválido: 422.
- `POST /internal/users/{id}/delete` (sem corpo): apaga os dados da pessoa no ethos
  (`app/internal/service.py`) e manda pelo imago, depois do commit, os avisos "você perdeu acesso"
  aos membros dos hábitos dela. 200 `{"status": "deleted"}`; idempotente, e id desconhecido
  também é 200.

`id`: de 1 a 2^53 - 1 (fora disso, 422). O imago chama com timeout de 10 s e repete a tarefa
quando a resposta não é 200.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Request
from pydantic import AfterValidator, BaseModel

from app.config import SettingsDep
from app.db import SessionDep
from app.errors import ApiError, ErrorCode
from app.identity import internal_token_valid, is_identity_email, is_valid_timezone
from app.internal import service
from app.mail.language import Locale
from app.mail.sender import MailerDep, schedule_email
from app.models import MAX_USER_ID


def require_internal_token(request: Request, settings: SettingsDep) -> None:
    """401 `unauthorized` sem `Authorization: Bearer <INTERNAL_API_TOKEN>` (ou com outro)."""
    expected = settings.internal_api_token.get_secret_value()
    if not internal_token_valid(request.scope["headers"], expected):
        raise ApiError(401, ErrorCode.UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
    include_in_schema=False,
)

UserId = Annotated[int, Path(ge=1, le=MAX_USER_ID)]


def _email(value: str) -> str:
    if not is_identity_email(value):
        raise ValueError("email inválido")
    return value


def _timezone(value: str) -> str:
    if not is_valid_timezone(value):
        raise ValueError("fuso desconhecido")
    return value


class RefreshIn(BaseModel):
    """Os valores atuais da conta no imago. Campos a mais são ignorados."""

    email: Annotated[str, AfterValidator(_email)]
    locale: Locale
    timezone: Annotated[str, AfterValidator(_timezone)]


class Status(BaseModel):
    status: str


@router.post("/users/{user_id}/refresh")
def refresh_user(user_id: UserId, body: RefreshIn, session: SessionDep) -> Status:
    service.refresh_app_user(
        session, user_id=user_id, email=body.email, locale=body.locale, timezone=body.timezone
    )
    return Status(status="ok")


@router.post("/users/{user_id}/delete")
def delete_user(
    user_id: UserId,
    session: SessionDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> Status:
    result = service.delete_user_data(session, user_id=user_id)
    # Depois do commit: uma exclusão que falhou não avisa ninguém
    for notice in result.notices:
        schedule_email(background_tasks, mailer, notice.user_id, notice.locale, notice.email)
    return Status(status="deleted")
