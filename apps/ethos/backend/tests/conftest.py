"""Fixtures compartilhadas pelos testes do backend.

- `make_settings(**campos)`: Settings validada, com valores de teste e banco em arquivo temporário
  (o `INTERNAL_API_TOKEN` é o `INTERNAL_TOKEN` do imago falso);
- `settings`: `make_settings()` sem alterações;
- `migrated_template`: banco com todas as migrações aplicadas (`alembic upgrade head`), criado uma
  vez por sessão do pytest. Não escreva nele: os testes usam cópias;
- `database`: cópia do `migrated_template` em `settings.database_path`, em WAL como em produção.
  Todo teste que usa `engine`, `db_session`, `app` ou `client` já recebe o schema completo;
- `engine`: engine desse banco, descartada no fim;
- `db_session`: sessão desse banco, da mesma fábrica do app (escrita só em `write_transaction`);
- `imago`: o imago falso (`tests/fake_imago.py`): contas do `lookup` (`imago.add_account`),
  resposta do `/internal/mail` (`imago.mail_status`) e os emails aceitos (`imago.mails`);
- `app`: app montado com `settings`, sobre o `database`, falando com o `imago`;
- `make_alembic_config(path)`: Config do Alembic apontando para o banco em `path` (para
  `alembic.command.upgrade(config, "head")` etc.);
- `make_client(app, *, origin=True, **kwargs)`: TestClient com o lifespan rodando e o root_path
  de produção, fechado no fim do teste (kwargs vão para o TestClient, ex.:
  raise_server_exceptions=False). Como um navegador na página do app, manda em todo request o
  header `Origin` igual ao `settings.app_origin` do app, que a checagem de CSRF exige nos métodos
  de escrita (`app/identity.py`). `origin="https://..."` manda esse valor (necessário quando
  `app` é um middleware em volta do app, sem `.state`); `origin=False` não manda. Um
  `headers={"Origin": ...}` no request troca o valor só nele;
- `client`: `make_client(app)`;
- `smtp_server`: servidor SMTP falso (`tests/fake_smtp.py`) em 127.0.0.1, com STARTTLS e login
  obrigatórios, parado no fim do teste. Só o backend do E2E (`tests/e2e_stack.py`) o usa: o app
  não fala com SMTP (os emails saem pelo imago);
- `make_account(email, admin=False, **campos)`: usuário salvo em `app_users` e registrado no
  imago falso (o `lookup` o encontra): `Account(user, headers)` (`tests/habit_helpers.py`), com os
  headers `X-User-*` que o nginx põe a partir do imago (`tests/identity_helpers.py`), e
  `X-User-Admin: 1` com `admin=True`;
- `selects`: função que devolve quantos SELECT rodaram (em qualquer engine) desde a última
  chamada, para os testes de N+1.
"""

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

import pytest
import trustme
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import create_db_engine, create_session_factory
from app.main import create_app
from tests.factories import new_user, save
from tests.fake_imago import INTERNAL_TOKEN, FakeImago
from tests.fake_smtp import FakeSmtpServer, start_fake_smtp
from tests.habit_helpers import Account
from tests.identity_helpers import identity_headers

# Mesmo prefixo que o uvicorn recebe em produção (--root-path /api/ethos)
ROOT_PATH = "/api/ethos"
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
            "app_url": "http://localhost:5174/ethos",
            "database_path": tmp_path / "app.db",
            "imago_internal_url": "http://127.0.0.1:3003",
            "internal_api_token": INTERNAL_TOKEN,
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
def imago() -> FakeImago:
    return FakeImago()


@pytest.fixture
def app(settings, database, imago) -> FastAPI:
    return create_app(settings, imago_transport=imago.transport)


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
def smtp_server(smtp_ca) -> Iterator[FakeSmtpServer]:
    server, stop = start_fake_smtp(smtp_ca)
    try:
        yield server
    finally:
        stop()


@pytest.fixture
def make_account(db_session, imago) -> Callable[..., Account]:
    def build(email: str, *, admin: bool = False, **fields: Any) -> Account:
        user = new_user(email, **fields)
        save(db_session, user)
        # A conta existe também no imago falso: o lookup dos convites a encontra
        imago.add_account(user.id, user.email, user.locale)
        return Account(user, identity_headers(user, admin=admin))

    return build


@pytest.fixture
def selects() -> Iterator[Callable[[], int]]:
    """Quantos SELECT foram executados (em qualquer engine) desde a última chamada."""
    statements: list[str] = []

    def listener(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", listener)

    def take() -> int:
        total = sum(1 for statement in statements if statement.lstrip().startswith("SELECT"))
        statements.clear()
        return total

    try:
        yield take
    finally:
        event.remove(Engine, "before_cursor_execute", listener)
