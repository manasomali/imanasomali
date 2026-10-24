"""Comandos de operação do ethos: `python -m app.cli <comando>` (lista no apps/ethos/README.md).

Cada comando lê a mesma configuração do servidor (variáveis de ambiente, `load_settings`) e abre o
banco de `DATABASE_PATH`, que precisa já existir (migrado com `alembic upgrade head`). Em produção
roda como `app-ethos`: o `cleanup` pelo timer de hora em hora, os outros à mão. O `create-admin` é
o único jeito de ligar o `is_admin`: não existe endpoint para isso.

Para acrescentar um comando:

1. escreva o handler `def _nome(context: CommandContext, args: argparse.Namespace) -> int`, que
   devolve o código de saída (0 = sucesso). Escrita no banco vai dentro de `write_transaction`;
2. registre-o em `build_parser`, com `commands.add_parser("nome", ...)` e
   `.set_defaults(handler=_nome)`.

Saída e erros: o resultado vai para o stdout (journald, quando roda pelo systemd). Um erro esperado
(ex.: conta inexistente) é `raise CommandError("mensagem")`: sai no stderr como "erro: mensagem",
com código 1. Qualquer outra exceção sai com código 1 e só com o tipo e o lugar do erro, sem a
mensagem nem o stack trace, que podem trazer dados. Uso errado (comando ou argumento inválido) sai
com código 2, pelo argparse. Nunca escreva código, token, cookie nem IP na saída.
"""

import argparse
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app import audit
from app.audit import AuditEvent
from app.auth.service import normalize_email
from app.config import ConfigError, Settings, load_settings
from app.db import create_db_engine, create_session_factory, write_transaction
from app.logs import configure_logging
from app.models import User, utcnow
from app.retention import run_cleanup
from app.seed import seed

EXIT_OK = 0
EXIT_ERROR = 1


class CommandError(Exception):
    """Erro esperado de um comando. A mensagem vai para o stderr: nada de dado sensível."""


@dataclass(frozen=True)
class CommandContext:
    """O que todo comando recebe: a configuração e a fábrica de sessões do banco."""

    settings: Settings
    session_factory: sessionmaker[Session]


Handler = Callable[[CommandContext, argparse.Namespace], int]


def _cleanup(context: CommandContext, _args: argparse.Namespace) -> int:
    with context.session_factory() as session, write_transaction(session):
        result = run_cleanup(session, utcnow())
    print(
        "cleanup: "
        f"{result.auth_events_deleted} eventos de auth apagados, "
        f"{result.audit_ips_cleared} IPs apagados na auditoria, "
        f"{result.sessions_deleted} sessões vencidas apagadas, "
        f"{result.session_ips_cleared} IPs apagados nas sessões, "
        f"{result.login_codes_deleted} códigos vencidos apagados"
    )
    return EXIT_OK


def _create_admin(context: CommandContext, args: argparse.Namespace) -> int:
    """Liga o `is_admin` de uma conta que já existe e grava `admin_created` no `audit_log`.

    O email é normalizado como no login (strip + lower). A saída identifica a conta pelo id, nunca
    pelo email. Conta bloqueada (`is_active=false`) é recusada: promover quem não pode entrar não
    serve para nada e deixaria um admin pronto para quem desbloquear a conta. Rodar de novo numa
    conta que já é admin não grava nada.
    """
    # Mesma normalização e validação do login: o email é salvo em `users` com strip + lower
    email = normalize_email(args.email)
    if email is None:
        raise CommandError("email inválido")
    # A leitura vai dentro da transação de escrita: duas execuções ao mesmo tempo não gravam dois
    # eventos, porque a segunda só lê depois do commit da primeira (BEGIN IMMEDIATE)
    with context.session_factory() as session, write_transaction(session):
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            raise CommandError(
                "nenhuma conta com esse email. A pessoa precisa entrar no app uma vez antes"
            )
        if not user.is_active:
            raise CommandError(f"a conta {user.id} está bloqueada (is_active=false); nada mudou")
        user_id, already_admin = user.id, user.is_admin
        if not already_admin:
            user.is_admin = True
            audit.record(session, AuditEvent.ADMIN_CREATED, user_id=user_id, details={"via": "cli"})
    if already_admin:
        print(f"create-admin: a conta {user_id} já é admin; nada mudou")
    else:
        print(f"create-admin: a conta {user_id} agora é admin")
    return EXIT_OK


def _seed(context: CommandContext, _args: argparse.Namespace) -> int:
    """Cria os dados de exemplo de `app/seed.py`. Só com `APP_ENV=dev`.

    Fora de dev, recusa antes de abrir qualquer transação: nada é gravado. Se as contas de
    exemplo já existem, avisa e não grava nada (sai com 0).
    """
    if not context.settings.is_dev:
        raise CommandError("seed só roda com APP_ENV=dev; nada foi gravado")
    with context.session_factory() as session, write_transaction(session):
        result = seed(session, context.settings, now=utcnow())
    if result is None:
        print(
            "seed: as contas de exemplo já existem; nada mudou "
            "(para recriar, apague o banco de dev e rode as migrações)"
        )
    else:
        print(
            f"seed: {result.users} contas, {result.habits} hábitos e "
            f"{result.marks} marcações criados"
        )
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Comandos de operação do ethos. A config vem das variáveis de ambiente.",
    )
    commands = parser.add_subparsers(title="comandos", dest="command", required=True)

    commands.add_parser(
        "cleanup",
        help="aplica a retenção de dados (auditoria de auth, IPs, sessões e códigos vencidos)",
        description=(
            "Apaga eventos de auth com mais de 90 dias, apaga os IPs com mais de 90 dias da "
            "auditoria e das sessões e apaga sessões e códigos de login vencidos. Não toca na "
            "auditoria de hábitos e marcações. Pode rodar quantas vezes quiser."
        ),
    ).set_defaults(handler=_cleanup)

    create_admin = commands.add_parser(
        "create-admin",
        help="torna admin uma conta que já existe (único jeito de criar admin)",
        description=(
            "Liga o is_admin da conta com esse email e grava admin_created na auditoria. A conta "
            "precisa existir (a pessoa entra no app uma vez antes) e não pode estar bloqueada. "
            "Rodar de novo numa conta que já é admin não muda nada."
        ),
    )
    create_admin.add_argument("email", help="email da conta (maiúsculas e espaços não importam)")
    create_admin.set_defaults(handler=_create_admin)

    commands.add_parser(
        "seed",
        help="cria contas, hábitos e marcações de exemplo (só com APP_ENV=dev)",
        description=(
            "Cria as contas ana@, bia@ e caio@example.com, hábitos de vários tipos e marcações "
            "dos últimos 60 dias, numa transação só. Recusa rodar fora de APP_ENV=dev. Se as "
            "contas de exemplo já existem, não muda nada."
        ),
    ).set_defaults(handler=_seed)

    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Roda o comando de `argv` (padrão: sys.argv) e devolve o código de saída."""
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        settings = load_settings(environ)
    except ConfigError as exc:
        return _fail(str(exc))
    if not settings.database_path.is_file():
        # Sem isso, o SQLite criaria um arquivo vazio no lugar do banco
        return _fail("DATABASE_PATH não aponta para um banco existente (alembic upgrade head)")
    configure_logging(settings.app_env)

    engine = create_db_engine(settings.database_path)
    try:
        return handler(CommandContext(settings, create_session_factory(engine)), args)
    except CommandError as exc:
        return _fail(str(exc))
    except SQLAlchemyError as exc:
        # A mensagem do driver pode trazer o caminho do banco e trechos de SQL
        return _fail(f"falha no banco de dados ({type(exc).__name__}{_where(exc)})")
    except Exception as exc:
        return _fail(f"erro inesperado ({type(exc).__name__}{_where(exc)})")
    finally:
        engine.dispose()


def _fail(message: str) -> int:
    print(f"erro: {message}", file=sys.stderr)
    return EXIT_ERROR


def _where(exc: BaseException) -> str:
    """Arquivo e linha do app onde a exceção nasceu (sem a mensagem, que pode trazer dados)."""
    app_dir = Path(__file__).resolve().parent
    # O traceback começa no main, neste arquivo: sempre há pelo menos um quadro do app
    frame = [
        frame
        for frame in traceback.extract_tb(exc.__traceback__)
        if Path(frame.filename).resolve().is_relative_to(app_dir)
    ][-1]
    path = Path(frame.filename).resolve().relative_to(app_dir.parent).as_posix()
    return f" em {path}:{frame.lineno}"


if __name__ == "__main__":  # pragma: no cover (testado por subprocesso, fora da cobertura)
    sys.exit(main())
