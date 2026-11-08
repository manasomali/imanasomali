"""Montagem do app do imago: config, banco, email, middlewares e rotas."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import APIRouter, FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.admin.router import router as admin_router
from app.auth.origin import OriginCheckMiddleware
from app.auth.router import router as auth_router
from app.body_limit import BodyLimitMiddleware
from app.config import Settings, load_settings
from app.db import SessionDep, create_db_engine, create_session_factory
from app.errors import ApiError, ErrorCode, install_error_handlers
from app.internal.router import router as internal_router
from app.internal.router import session_router as internal_session_router
from app.internal.tasks import TaskContext
from app.logs import RequestLogMiddleware, configure_logging
from app.mail.backends import MailBackend
from app.mail.sender import Mailer, build_backend

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Só o tipo do erro: a mensagem do driver pode trazer o caminho do banco
        logger.warning("health: banco indisponível (%s)", type(exc).__name__)
        raise ApiError(503, ErrorCode.DATABASE_UNAVAILABLE) from exc
    return {"status": "ok"}


def _enable_docs(api: FastAPI) -> None:
    """Liga `/openapi.json`, `/docs` e `/redoc` (só em dev; chamada no lifespan).

    O app nasce sem eles, porque a config só é lida na subida: aqui as URLs ganham os valores
    padrão do FastAPI e o `setup()` registra as rotas delas. O `app.openapi()` (usado pelos
    testes) funciona em qualquer ambiente; só as rotas HTTP dependem disto. Um lifespan que roda
    de novo no mesmo app (nos testes) não duplica as rotas.
    """
    if api.openapi_url is not None:
        return
    api.openapi_url, api.docs_url, api.redoc_url = "/openapi.json", "/docs", "/redoc"
    api.setup()


def create_app(
    settings: Settings | None = None,
    mail_backend: MailBackend | None = None,
    app_transport: httpx2.BaseTransport | None = None,
) -> FastAPI:
    """Monta o app. Sem `settings`, a configuração é lida do ambiente na subida.

    Sem `mail_backend`, o envio de email segue o `EMAIL_BACKEND` da config; os testes passam um
    backend apontado para o servidor SMTP falso (ou um em memória). Sem `app_transport`, as
    tarefas das aplicações (`app/internal/tasks.py`) saem pela rede; os testes passam as
    aplicações falsas.

    A leitura fica no lifespan, não no import: config inválida (inclusive um `IMAGO_APPS` sem o
    token de alguma aplicação) derruba o servidor na subida com a lista das variáveis erradas, e
    os testes importam o módulo sem precisar do ambiente.

    `/openapi.json`, `/docs` e `/redoc` só existem com `APP_ENV=dev` (`_enable_docs`): fora de
    dev, o schema listaria para qualquer um todas as rotas, inclusive as internas e as de admin.
    """

    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        current = load_settings() if settings is None else settings
        configure_logging(current.app_env)
        if current.is_dev:
            _enable_docs(api)
        engine = create_db_engine(current.database_path)
        api.state.settings = current
        api.state.session_factory = create_session_factory(engine)
        api.state.task_context = TaskContext(current, api.state.session_factory, app_transport)
        backend = build_backend(current) if mail_backend is None else mail_backend
        api.state.mailer = Mailer(current, backend)
        try:
            yield
        finally:
            engine.dispose()

    # O nginx tira o prefixo /api/imago antes de repassar a request, então as rotas ficam na raiz
    # (/health). O prefixo público é passado ao servidor com `uvicorn --root-path /api/imago`: o
    # parâmetro root_path do FastAPI() está obsoleto desde o FastAPI 0.162. A API interna
    # (/internal/*) é chamada direto em 127.0.0.1:3003, sem o nginx. Nasce sem as rotas dos docs e
    # do schema, que só o lifespan liga, em dev, depois de ler a config (`_enable_docs`)
    api = FastAPI(title="imago", lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None)
    # O último adicionado fica por fora: o log registra também o 422 do tamanho do corpo e o 403
    # da checagem de Origin
    api.add_middleware(OriginCheckMiddleware)
    api.add_middleware(BodyLimitMiddleware)
    api.add_middleware(RequestLogMiddleware)
    install_error_handlers(api)
    api.include_router(router)
    api.include_router(auth_router)
    api.include_router(admin_router)
    api.include_router(internal_session_router)
    api.include_router(internal_router)
    return api


app = create_app()
