"""Acesso ao SQLite: engine síncrona, PRAGMAs em toda conexão, sessão por request e transação de
escrita com BEGIN IMMEDIATE.

O driver sqlite3 abre transações sozinho e só antes de INSERT/UPDATE/DELETE, sempre DEFERRED. Aqui
ele fica sem controle de transação (isolation_level=None) e o BEGIN sai do SQLAlchemy (evento
"begin"), como na documentação do dialeto SQLite do SQLAlchemy:

- leitura: BEGIN DEFERRED, aberto pela sessão no primeiro comando;
- escrita: BEGIN IMMEDIATE, pelo `write_transaction`. A trava de escrita é pega já no BEGIN,
  esperando até o busy_timeout. Uma transação DEFERRED que lê e depois tenta escrever pode receber
  "database is locked" no meio, sem esperar, se outra conexão escreveu nesse intervalo.

Toda escrita do ORM fora do `write_transaction` é recusada (evento before_flush), para essa
regra não depender de memória.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# Executados em cada conexão nova do pool. Nenhum deles fica gravado no arquivo do banco
PRAGMAS = (
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA secure_delete=ON",
)

# Opção de execução da conexão que escolhe o BEGIN emitido pelo evento "begin"
_BEGIN_OPTION = "ethos_begin"
_BEGIN_STATEMENTS = {
    "DEFERRED": "BEGIN DEFERRED",
    "IMMEDIATE": "BEGIN IMMEDIATE",
}
# Marca, em Session.info, a sessão que está dentro de um write_transaction
_IN_WRITE = "ethos_in_write_transaction"


def create_db_engine(database_path: Path) -> Engine:
    """Engine do banco em `database_path`, com os PRAGMAs e o BEGIN controlado aqui."""
    # URL.create não interpreta o caminho: um "?" no nome não vira parâmetro do driver
    url = URL.create("sqlite+pysqlite", database=str(database_path))
    # hide_parameters: erros e logs do SQLAlchemy não mostram os valores (email, hash de código)
    engine = create_engine(url, hide_parameters=True)
    event.listen(engine, "connect", _on_connect)
    event.listen(engine, "begin", _on_begin)
    return engine


def _on_connect(dbapi_connection: Any, _connection_record: Any) -> None:
    # Desliga o BEGIN implícito do sqlite3; quem emite o BEGIN é o _on_begin
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        for pragma in PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def _on_begin(connection: Connection) -> None:
    mode = connection.get_execution_options().get(_BEGIN_OPTION, "DEFERRED")
    statement = _BEGIN_STATEMENTS.get(mode)
    if statement is None:
        raise ValueError(f"modo de BEGIN desconhecido: {mode!r}")
    connection.exec_driver_sql(statement)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Fábrica de sessões que só deixa o ORM escrever dentro de `write_transaction`."""
    # expire_on_commit=False: depois do commit, os objetos continuam legíveis para a resposta
    # sem outra ida ao banco
    factory = sessionmaker(engine, expire_on_commit=False)
    event.listen(factory, "before_flush", _refuse_write_outside_transaction)
    return factory


def _refuse_write_outside_transaction(
    session: Session, _flush_context: Any, _instances: Any
) -> None:
    if not session.info.get(_IN_WRITE):
        raise RuntimeError("escrita no banco fora de write_transaction")


@contextmanager
def write_transaction(session: Session) -> Iterator[Session]:
    """Transação de escrita com BEGIN IMMEDIATE: commit no fim do bloco, rollback se der erro.

    Se a sessão já tem uma transação de leitura aberta (ex.: a dependência que carregou o
    usuário), ela é encerrada antes, e os objetos carregados são relidos dentro da escrita. Faça
    as leituras que decidem a escrita dentro do bloco: só ali elas estão protegidas da escrita de
    outra conexão.
    """
    if session.info.get(_IN_WRITE):
        raise RuntimeError("write_transaction aninhada: use a transação já aberta")
    if session.in_transaction():
        if session.new or session.dirty or session.deleted:
            raise RuntimeError("alterações pendentes antes de write_transaction")
        session.rollback()
    session.info[_IN_WRITE] = True
    try:
        with session.begin():
            # Pega a conexão já com a opção: o evento "begin" emite o BEGIN IMMEDIATE
            session.connection(execution_options={_BEGIN_OPTION: "IMMEDIATE"})
            yield session
    finally:
        del session.info[_IN_WRITE]


def get_session(request: Request) -> Iterator[Session]:
    """Dependência do FastAPI: uma sessão por request, fechada no fim (rollback do que sobrou)."""
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
