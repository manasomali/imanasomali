import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, load_settings
from app.db import SessionDep, create_db_engine, create_session_factory
from app.errors import ApiError, ErrorCode, install_error_handlers
from app.logs import RequestLogMiddleware, configure_logging

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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Monta o app. Sem `settings`, a configuração é lida do ambiente na subida.

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
        try:
            yield
        finally:
            engine.dispose()

    # O nginx tira o prefixo /api/ethos antes de repassar a request, então as rotas ficam na raiz
    # (/health). O prefixo público é passado ao servidor com `uvicorn --root-path /api/ethos`: o
    # parâmetro root_path do FastAPI() está obsoleto desde o FastAPI 0.162
    api = FastAPI(title="ethos", lifespan=lifespan)
    api.add_middleware(RequestLogMiddleware)
    install_error_handlers(api)
    api.include_router(router)
    return api


app = create_app()
