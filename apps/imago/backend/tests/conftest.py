"""Fixtures compartilhadas pelos testes do backend.

- `make_settings(**campos)`: Settings validada, com valores de teste e banco em arquivo temporário.
  Por padrão, `IMAGO_APPS` com ethos e engrafi e os tokens de `tests/internal_helpers.py`;
- `settings`: `make_settings()` sem alterações;
- `migrated_template`: banco com todas as migrações aplicadas (`alembic upgrade head`), criado uma
  vez por sessão do pytest. Não escreva nele: os testes usam cópias;
- `database`: cópia do `migrated_template` em `settings.database_path`, em WAL como em produção.
  Todo teste que usa `engine`, `db_session`, `app` ou `client` já recebe o schema completo;
- `engine`: engine desse banco, descartada no fim;
- `db_session`: sessão desse banco, da mesma fábrica do app (escrita só em `write_transaction`);
- `outbox`: backend de email em memória (`tests/mail_helpers.py`), sem rede: o que o app mandou
  fica em `outbox.messages`;
- `apps`: as aplicações falsas (`tests/apps_helpers.py`), que recebem as tarefas `delete` e
  `refresh` do imago. Nenhum teste chama a rede: uma chamada que escape delas falha o teste;
- `task_context`: o `TaskContext` das tarefas (banco do teste e `apps`), para chamar
  `app/internal/tasks.py` e `app/deletion.py` direto;
- `app`: app montado com `settings`, o `outbox` e as `apps`, sobre o `database`;
- `make_alembic_config(path)`: Config do Alembic apontando para o banco em `path`;
- `make_client(app, *, origin=True, **kwargs)`: TestClient com o lifespan rodando e o root_path
  de produção, fechado no fim do teste (kwargs vão para o TestClient). Como um navegador na página
  do imago, manda em todo request o header `Origin` igual ao `settings.app_origin` do app, que a
  checagem de CSRF exige nos métodos de escrita. `origin="https://..."` manda esse valor;
  `origin=False` não manda. Um `headers={"Origin": ...}` no request troca o valor só nele;
- `client`: `make_client(app)`;
- `make_smtp_server(starttls=True)` / `smtp_server`: servidor SMTP falso (`tests/fake_smtp.py`)
  em 127.0.0.1, com STARTTLS e login obrigatórios. Para o app enviar por ele:
  `create_app(settings, mail_backend=smtp_server.backend())`;
- `make_account(email, **campos)`: usuário salvo, com os termos atuais aceitos e uma sessão
  aberta: `Account(user, headers)`, com o cookie em `headers`.
"""

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

import httpx2
import pytest
import trustme
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import create_db_engine, create_session_factory
from app.internal.tasks import TaskContext
from app.main import create_app
from app.terms import TERMS_VERSION
from tests.apps_helpers import FakeApps
from tests.auth_helpers import Account, cookie, open_session
from tests.factories import new_user, save
from tests.fake_smtp import FakeSmtpServer, start_fake_smtp
from tests.internal_helpers import ENGRAFI_TOKEN, ETHOS_TOKEN
from tests.mail_helpers import Outbox

# Mesmo prefixo que o uvicorn recebe em produção (--root-path /api/imago)
ROOT_PATH = "/api/imago"
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_config(database_path: Path) -> Config:
    config = Config(BACKEND_DIR / "alembic.ini")
    # O env.py lê o caminho daqui (fora dos testes, da variável DATABASE_PATH)
    config.attributes["database_path"] = database_path
    # Sem o fileConfig do alembic.ini, que trocaria os handlers de log no meio dos testes
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
def make_settings(tmp_path) -> Callable[..., Settings]:
    def build(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "app_env": "dev",
            "app_url": "http://localhost:8080/imago",
            "database_path": tmp_path / "app.db",
            "email_backend": "console",
            "mail_from_address": "no-reply@example.com",
            "support_email": "suporte@example.com",
            "imago_apps": "ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002",
            "imago_app_tokens": f"ethos:{ETHOS_TOKEN},engrafi:{ENGRAFI_TOKEN}",
        }
        values.update(overrides)
        # model_validate (e não model_copy) para os overrides passarem pela validação
        return Settings.model_validate(values)

    return build


@pytest.fixture
def settings(make_settings) -> Settings:
    return make_settings()


@pytest.fixture
def make_alembic_config() -> Callable[[Path], Config]:
    return _alembic_config


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("migrated") / "app.db"
    command.upgrade(_alembic_config(path), "head")
    return path


@pytest.fixture
def database(settings, migrated_template) -> Path:
    path = settings.database_path
    # O modelo fica em journal_mode=DELETE (padrão), então o arquivo sozinho é o banco inteiro
    shutil.copyfile(migrated_template, path)
    # Fica gravado no arquivo, como o provision faz no banco de produção
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA journal_mode=WAL").close()
    return path


@pytest.fixture
def engine(database) -> Iterator[Engine]:
    engine = create_db_engine(database)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session


@pytest.fixture
def outbox() -> Outbox:
    return Outbox()


@pytest.fixture(autouse=True)
def _no_network_calls_to_apps(monkeypatch) -> None:
    # As tarefas das aplicações só chegam às aplicações falsas (fixture `apps`): um app montado
    # sem elas tentaria a rede de verdade (e acharia, em dev, o ethos rodando na porta 3001)
    def refuse(_transport: Any, request: httpx2.Request) -> httpx2.Response:
        pytest.fail(f"chamada de rede fora das aplicações falsas: {request.url}")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse)


@pytest.fixture
def apps() -> FakeApps:
    return FakeApps()


@pytest.fixture
def task_context(settings, engine, apps) -> TaskContext:
    return TaskContext(settings, create_session_factory(engine), apps.transport)


@pytest.fixture
def app(settings, database, outbox, apps) -> FastAPI:
    return create_app(settings, mail_backend=outbox, app_transport=apps.transport)


@pytest.fixture
def make_client() -> Iterator[Callable[..., TestClient]]:
    with ExitStack() as stack:

        def build(app: Any, *, origin: str | bool = True, **kwargs: Any) -> TestClient:
            client = stack.enter_context(TestClient(app, root_path=ROOT_PATH, **kwargs))
            if origin is True:
                # A config só fica no app.state depois do lifespan (que o enter_context rodou)
                origin = app.state.settings.app_origin
            if origin:
                client.headers["Origin"] = origin
            return client

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


@pytest.fixture
def make_account(db_session) -> Callable[..., Account]:
    def build(email: str, **fields: Any) -> Account:
        user = new_user(email, **({"terms_version": TERMS_VERSION} | fields))
        save(db_session, user)
        return Account(user, cookie(open_session(db_session, user)))

    return build
