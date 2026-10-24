"""Fixtures compartilhadas pelos testes do backend.

- `make_settings(**campos)`: Settings validada, com valores de teste e banco em arquivo temporário;
- `settings`: `make_settings()` sem alterações;
- `engine`: engine do banco de teste (em WAL, como em produção), descartada no fim;
- `db_session`: sessão desse banco, da mesma fábrica do app;
- `app`: app montado com `settings`;
- `make_client(app, **kwargs)`: TestClient com o lifespan rodando e o root_path de produção,
  fechado no fim do teste (kwargs vão para o TestClient, ex.: raise_server_exceptions=False);
- `client`: `make_client(app)`;
- `make_smtp_server(starttls=True)`: servidor SMTP falso (`tests/fake_smtp.py`) em 127.0.0.1,
  com STARTTLS e login obrigatórios, parado no fim do teste. Guarda em `.received` cada email
  recebido; `.backend()` devolve um `SmtpBackend` apontado para ele. Com `starttls=False`, o
  servidor não oferece STARTTLS;
- `smtp_server`: `make_smtp_server()`. Para o app enviar por ele:
  `create_app(settings, mail_backend=smtp_server.backend())`.
"""

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any

import pytest
import trustme
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import create_db_engine, create_session_factory
from app.main import create_app
from tests.fake_smtp import FakeSmtpServer, start_fake_smtp

# Mesmo prefixo que o uvicorn recebe em produção (--root-path /api/ethos)
ROOT_PATH = "/api/ethos"


@pytest.fixture
def make_settings(tmp_path) -> Callable[..., Settings]:
    def build(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "app_env": "dev",
            "app_url": "http://localhost:5174/ethos",
            "database_path": tmp_path / "app.db",
            "email_backend": "console",
            "mail_from": "ethos <no-reply@example.com>",
            "support_email": "suporte@example.com",
            "max_code_emails_per_hour": 50,
            "max_code_emails_per_day": 200,
        }
        values.update(overrides)
        # model_validate (e não model_copy) para os overrides passarem pela validação
        return Settings.model_validate(values)

    return build


@pytest.fixture
def settings(make_settings) -> Settings:
    return make_settings()


@pytest.fixture
def engine(settings) -> Iterator[Engine]:
    engine = create_db_engine(settings.database_path)
    # Fica gravado no arquivo, como o provision faz no banco de produção. Pela conexão do driver,
    # porque o journal_mode não muda dentro de transação (e a do SQLAlchemy abriria uma)
    connection = engine.raw_connection()
    try:
        connection.driver_connection.execute("PRAGMA journal_mode=WAL").close()
    finally:
        connection.close()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session


@pytest.fixture
def app(settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def make_client() -> Iterator[Callable[..., TestClient]]:
    with ExitStack() as stack:

        def build(app: FastAPI, **kwargs: Any) -> TestClient:
            return stack.enter_context(TestClient(app, root_path=ROOT_PATH, **kwargs))

        yield build


@pytest.fixture
def client(app, make_client) -> TestClient:
    return make_client(app)


@pytest.fixture(scope="session")
def smtp_ca() -> trustme.CA:
    return trustme.CA()


@pytest.fixture
def make_smtp_server(smtp_ca) -> Iterator[Callable[..., FakeSmtpServer]]:
    with ExitStack() as stack:

        def build(*, starttls: bool = True) -> FakeSmtpServer:
            server, stop = start_fake_smtp(smtp_ca, starttls=starttls)
            stack.callback(stop)
            return server

        yield build


@pytest.fixture
def smtp_server(make_smtp_server) -> FakeSmtpServer:
    return make_smtp_server()
