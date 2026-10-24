import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.admin.routes import public_router as banners_router
from app.admin.routes import router as admin_router
from app.alerts.routes import router as alerts_router
from app.auth.origin import OriginCheckMiddleware
from app.auth.routes import router as auth_router
from app.config import Settings, load_settings
from app.db import SessionDep, create_db_engine, create_session_factory
from app.errors import ApiError, ErrorCode, install_error_handlers
from app.habits.routes import router as habits_router
from app.history.routes import router as history_router
from app.logs import RequestLogMiddleware, configure_logging
from app.mail.backends import MailBackend
from app.mail.sender import Mailer, build_backend
from app.marks.routes import router as marks_router
from app.progress.routes import router as progress_router
from app.sharing.routes import router as sharing_router

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


def create_app(
    settings: Settings | None = None, mail_backend: MailBackend | None = None
) -> FastAPI:
    """Monta o app. Sem `settings`, a configuração é lida do ambiente na subida.

    Sem `mail_backend`, o envio de email segue o `EMAIL_BACKEND` da config; os testes passam um
    backend apontado para o servidor SMTP falso.

    A leitura fica no lifespan, não no import: config inválida derruba o servidor na subida com
    a lista das variáveis erradas, e os testes importam o módulo sem precisar do ambiente.
    """

    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        current = load_settings() if settings is None else settings
        configure_logging(current.app_env)
        engine = create_db_engine(current.database_path)
        api.state.settings = current
        api.state.session_factory = create_session_factory(engine)
        backend = build_backend(current) if mail_backend is None else mail_backend
        api.state.mailer = Mailer(current, backend)
        try:
            yield
        finally:
            engine.dispose()

    # O nginx tira o prefixo /api/ethos antes de repassar a request, então as rotas ficam na raiz
    # (/health). O prefixo público é passado ao servidor com `uvicorn --root-path /api/ethos`: o
    # parâmetro root_path do FastAPI() está obsoleto desde o FastAPI 0.162
    api = FastAPI(title="ethos", lifespan=lifespan)
    # O último adicionado fica por fora: o log registra também o 403 da checagem de Origin
    api.add_middleware(OriginCheckMiddleware)
    api.add_middleware(RequestLogMiddleware)
    install_error_handlers(api)
    api.include_router(router)
    api.include_router(auth_router)
    # Antes do de /habits: lá, /habits/{habit_id} pegaria /habits/progress (e daria 422)
    api.include_router(progress_router)
    api.include_router(habits_router)
    api.include_router(marks_router)
    api.include_router(sharing_router)
    api.include_router(history_router)
    api.include_router(alerts_router)
    api.include_router(admin_router)
    api.include_router(banners_router)
    return api


app = create_app()
