"""Ambiente do Alembic do ethos.

- Banco: o caminho vem da variável DATABASE_PATH, a mesma do app (nunca fixo no alembic.ini). Os
  testes passam o caminho em `config.attributes["database_path"]`.
- Conexão: a engine do app (`create_db_engine`, com os mesmos PRAGMAs), aberta por
  `migration_connection`, que desliga as chaves estrangeiras durante a migração (senão o modo
  batch dispararia os ON DELETE ao recriar uma tabela) e usa BEGIN IMMEDIATE.
- Transação: uma só para todas as migrações da execução, aberta aqui. O Alembic marca o SQLite
  como sem DDL transacional e faria um commit por migração; o SQLite desfaz DDL num rollback, então
  um `upgrade head` aplica tudo ou nada. Antes do commit, `check_foreign_keys` confere as chaves.
- `render_as_batch=True`: alteração de tabela sai como recriação, o único jeito no SQLite.
- Só modo online: `--sql` (offline) é recusado.
"""

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context

from app.db import check_foreign_keys, create_db_engine, migration_connection
from app.models import Base

config = context.config

# Os testes desligam (configure_logger=False): o fileConfig troca os handlers do logger raiz
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_path() -> Path:
    value = config.attributes.get("database_path") or os.environ.get("DATABASE_PATH", "").strip()
    if not value:
        raise RuntimeError(
            "DATABASE_PATH não definida: rode com o ambiente do app "
            "(ex.: uv run --env-file .env alembic upgrade head)"
        )
    if str(value) == ":memory:":
        raise RuntimeError("DATABASE_PATH precisa ser um arquivo")
    return Path(value)


def run_migrations_online() -> None:
    engine = create_db_engine(database_path())
    try:
        with migration_connection(engine) as connection, connection.begin():
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                # A transação já está aberta acima; isto só corrige o que o Alembic assume (e
                # loga) para o SQLite
                transactional_ddl=True,
            )
            context.run_migrations()
            check_foreign_keys(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("modo offline (--sql) não é suportado: rode as migrações contra o banco")

run_migrations_online()
