"""Token da API interna: quem chama `/internal/*` (menos `/internal/session`) e qual aplicação é.

Cada aplicação do `IMAGO_APPS` tem o seu token (`IMAGO_APP_TOKENS`, gerado na VM pelo provision,
nunca no GitHub), mandado em `Authorization: Bearer <token>`. O token diz qual aplicação chamou:
é esse nome que vai no `mail_log` e no remetente dos emails, nunca um nome que venha no corpo.
O mesmo token vale nos dois sentidos (o imago o manda quando chama a aplicação), e uma aplicação
não tem como chamar a API interna de outra.

Sem o header, com outro esquema, com mais de um `Authorization` ou com um token que não é de
nenhuma aplicação do `IMAGO_APPS`: 401 `unauthorized`, sempre igual. A comparação é em tempo
constante (`Settings.app_for_token`). O token nunca vai para o log.

O `router` de `app/internal/router.py` põe `caller_app` em todas as rotas dele, então rota nova
em `/internal/` já nasce exigindo o token; o endpoint que precisa do nome da aplicação recebe
`app: CallerApp` (o FastAPI roda a dependência uma vez só por request).
"""

from typing import Annotated

from fastapi import Depends, Request

from app.config import SettingsDep
from app.errors import ApiError, ErrorCode

_BEARER = "bearer"


def caller_app(request: Request, settings: SettingsDep) -> str:
    """Nome da aplicação dona do token do request; senão 401."""
    values = request.headers.getlist("authorization")
    if len(values) != 1:
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    scheme, _, token = values[0].partition(" ")
    if scheme.lower() != _BEARER or not token:
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    app = settings.app_for_token(token)
    if app is None:
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    return app


CallerApp = Annotated[str, Depends(caller_app)]
