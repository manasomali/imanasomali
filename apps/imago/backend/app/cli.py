"""Comandos de operação do imago: `python -m app.cli <comando>` (lista no apps/imago/README.md).

Cada comando lê a mesma configuração do servidor (variáveis de ambiente, `load_settings`) e abre o
banco de `DATABASE_PATH`, que precisa já existir (migrado com `alembic upgrade head`). Em produção
roda como `app-imago`: o `run-tasks` e o `cleanup` pelo `imago-cleanup.timer`, de hora em hora, os
outros à mão. O `create-admin` é o único jeito de ligar o `is_admin`: não existe endpoint para isso.
O `import-users` só existe para a passagem do login do ethos (uma vez só).

Para acrescentar um comando:

1. escreva o handler `def _nome(context: CommandContext, args: argparse.Namespace) -> int`, que
   devolve o código de saída (0 = sucesso). Escrita no banco vai dentro de `write_transaction`;
2. registre-o em `build_parser`, com `commands.add_parser("nome", ...)` e
   `.set_defaults(handler=_nome)`.

Saída e erros: o resultado vai para o stdout (journald, quando roda pelo systemd). Um erro esperado
(ex.: conta inexistente) é `raise CommandError("mensagem")`: sai no stderr como "erro: mensagem",
com código 1. Qualquer outra exceção sai com código 1 e só com o tipo e o lugar do erro, sem a
mensagem nem o stack trace, que podem trazer dados. Uso errado (comando ou argumento inválido) sai
com código 2, pelo argparse. Nunca escreva email, código, token, cookie nem IP na saída: as contas
aparecem pelo id.
"""

import argparse
import sys
import traceback
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx2
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app import audit, deletion
from app.audit import AuditEvent
from app.auth.service import can_sign_in, normalize_email
from app.config import ConfigError, Settings, load_settings
from app.db import create_db_engine, create_session_factory, write_transaction
from app.import_users import ImportFailure, import_accounts, parse_accounts
from app.internal.tasks import TaskContext, run_pending
from app.logs import configure_logging
from app.mail.backends import MailBackend
from app.mail.sender import Mailer, build_backend
from app.models import User, utcnow
from app.reapply import InputError, parse_account_id, read_account_ids, reapply_deletions
from app.retention import run_cleanup
from app.seed import seed

EXIT_OK = 0
EXIT_ERROR = 1


class CommandError(Exception):
    """Erro esperado de um comando. A mensagem vai para o stderr: nada de dado sensível."""


@dataclass(frozen=True)
class CommandContext:
    """O que todo comando recebe: a configuração e a fábrica de sessões do banco.

    `app_transport` e `mail_backend` só existem para os testes (aplicações falsas e email em
    memória); em produção são None, e as chamadas e os emails saem de verdade.
    """

    settings: Settings
    session_factory: sessionmaker[Session]
    app_transport: httpx2.BaseTransport | None = None
    mail_backend: MailBackend | None = None

    def task_context(self) -> TaskContext:
        return TaskContext(self.settings, self.session_factory, self.app_transport)

    def mailer(self) -> Mailer:
        backend = build_backend(self.settings) if self.mail_backend is None else self.mail_backend
        return Mailer(self.settings, backend)


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
        f"{result.login_codes_deleted} códigos apagados, "
        f"{result.mail_log_deleted} envios apagados do mail_log, "
        f"{result.app_tasks_deleted} tarefas concluídas apagadas"
    )
    return EXIT_OK


def _run_tasks(context: CommandContext, _args: argparse.Namespace) -> int:
    """Tenta de novo as tarefas pendentes para as aplicações (`app/internal/tasks.py`) e termina
    as exclusões de conta que não têm mais tarefa pendente (passo 3, `app/deletion.py`).

    Sai com 0 mesmo que alguma tarefa falhe (aplicação fora do ar): a falha fica gravada na
    tarefa, vira uma linha de log e é tentada de novo na próxima execução, e o `cleanup` que vem
    depois no `imago-cleanup.service` roda assim mesmo. Só um erro geral (config, banco
    inacessível) sai com 1, e aí o `OnFailure=` da unit registra.
    """
    task_context = context.task_context()
    summary = run_pending(task_context)
    finished = deletion.finish_ready_deletions(task_context, context.mailer())
    print(
        f"run-tasks: {summary.tried} tarefas tentadas, {summary.done} concluídas, "
        f"{summary.failed} falhas, {summary.busy + summary.pending} ficaram para depois; "
        f"{finished} exclusões de conta concluídas"
    )
    return EXIT_OK


def _reapply_deletions(context: CommandContext, args: argparse.Namespace) -> int:
    """Refaz, depois de restaurar um backup, as exclusões de conta que o journald lista.

    Lê as linhas do `journalctl -u app-imago -o cat` (ou ids soltos, um por linha) do stdin, ou
    recebe os ids como argumentos, e chama `app/reapply.py`. Sem email. Entrada ilegível, vazia ou
    com uma linha de exclusão fora do formato: erro, antes de mexer no banco. Sai com 1 também se
    o `delete` de uma conta que já não existe no imago falhou numa aplicação (essa falha não fica
    gravada: rode de novo); as que ficaram como tarefa pendente são do `run-tasks`.
    """
    if args.ids:
        account_ids: tuple[int, ...] = tuple(dict.fromkeys(args.ids))
        print(f"reapply-deletions: {len(account_ids)} contas nos argumentos")
    else:
        account_ids = _read_ids_from_stdin()
    result = reapply_deletions(context.task_context(), account_ids)
    for account_id in result.last_admin:
        print(
            f"aviso: a conta {account_id} é o último admin ativo e não foi apagada. Torne outra "
            "conta admin (create-admin) e rode o reapply-deletions de novo",
            file=sys.stderr,
        )
    for account_id, app, reason in result.failed_calls:
        print(f"aviso: {app} não apagou a conta {account_id} ({reason})", file=sys.stderr)
    print(
        f"reapply-deletions: {len(result.deleted)} contas apagadas de novo no imago "
        f"({len(result.pending)} esperando uma aplicação: rode o run-tasks), "
        f"{len(result.missing)} que já não existiam no imago, "
        f"{len(result.last_admin)} puladas (último admin); "
        f"{len(result.failed_calls)} chamadas às aplicações falharam"
    )
    if result.failed_calls:
        raise CommandError(
            "o delete falhou em alguma aplicação para contas que já não existem no imago; "
            "confira a aplicação e rode o reapply-deletions de novo"
        )
    return EXIT_OK


def _read_ids_from_stdin() -> tuple[int, ...]:
    if sys.stdin.isatty():
        raise CommandError(
            "mande as linhas pelo stdin (journalctl -u app-imago -o cat | ...) "
            "ou passe os ids como argumentos"
        )
    try:
        parsed = read_account_ids(_decoded_lines(sys.stdin.buffer))
    except OSError as exc:
        raise CommandError(f"não consegui ler a entrada ({type(exc).__name__})") from None
    except InputError as exc:
        raise CommandError(f"{exc}; nada foi apagado") from None
    if parsed.lines == 0:
        # journalctl sem sudo, unit errada: melhor parar do que dizer que não havia nada
        raise CommandError("entrada vazia; confira o journalctl (precisa de sudo)")
    print(
        f"reapply-deletions: {parsed.lines} linhas lidas, {len(parsed.ids)} contas no log "
        f"({parsed.repeated} repetições ignoradas)"
    )
    return parsed.ids


def _import_users(context: CommandContext, _args: argparse.Namespace) -> int:
    """Importa as contas do ethos, uma linha JSON por conta no stdin (`app/import_users.py`).

    Só pelo stdin, ligado por um pipe ao `export-users` do ethos: as contas (com os emails) não
    passam por arquivo. Recusa um terminal no stdin. Tudo ou nada, numa transação só; a saída tem
    só contagens, nunca email.
    """
    if sys.stdin.isatty():
        raise CommandError(
            "mande as contas pelo stdin, num pipe com o export-users do ethos "
            "(roteiro no apps/imago/README.md)"
        )
    try:
        accounts = parse_accounts(_decoded_lines(sys.stdin.buffer))
        if not accounts:
            raise CommandError("entrada vazia; nada foi gravado (o export-users rodou?)")
        with context.session_factory() as session, write_transaction(session):
            summary = import_accounts(session, accounts, now=utcnow())
    except OSError as exc:
        raise CommandError(f"não consegui ler a entrada ({type(exc).__name__})") from None
    except ImportFailure as exc:
        raise CommandError(f"{exc}; nada foi gravado") from None
    print(
        f"import-users: {summary.total} contas importadas ({summary.active} ativas, "
        f"{summary.blocked} bloqueadas, {summary.admins} admins)"
    )
    return EXIT_OK


def _decoded_lines(stream: Iterable[bytes]) -> Iterator[str]:
    # Bytes, e não o texto do stdin: o journald grava UTF-8, qualquer que seja o locale da sessão
    for raw in stream:
        yield raw.decode("utf-8", errors="replace")


def _account_id_argument(value: str) -> int:
    try:
        return parse_account_id(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _create_admin(context: CommandContext, args: argparse.Namespace) -> int:
    """Liga o `is_admin` de uma conta que já existe e grava `admin_created` no `audit_log`.

    O email é normalizado como no login (strip + lower). A saída identifica a conta pelo id, nunca
    pelo email. Conta bloqueada (`is_active=false`) ou em exclusão é recusada: promover quem não
    pode entrar não serve para nada e deixaria um admin pronto para quem desbloquear a conta.
    Rodar de novo numa conta que já é admin não grava nada.
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
                "nenhuma conta com esse email. A pessoa precisa entrar no imago uma vez antes"
            )
        if not can_sign_in(user):
            raise CommandError(f"a conta {user.id} está bloqueada ou em exclusão; nada mudou")
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
    """Cria as contas de exemplo de `app/seed.py`. Só com `APP_ENV=dev`.

    Fora de dev, recusa antes de abrir qualquer transação: nada é gravado. Se alguma conta de
    exemplo já existe, avisa e não grava nada (sai com 0).
    """
    if not context.settings.is_dev:
        raise CommandError("seed só roda com APP_ENV=dev; nada foi gravado")
    with context.session_factory() as session, write_transaction(session):
        created = seed(session, now=utcnow())
    if created is None:
        print(
            "seed: as contas de exemplo já existem; nada mudou "
            "(para recriar, apague o banco de dev e rode as migrações)"
        )
    else:
        print(f"seed: {created} contas criadas (ids 101, 102 e 103)")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Comandos de operação do imago. A config vem das variáveis de ambiente.",
    )
    commands = parser.add_subparsers(title="comandos", dest="command", required=True)

    commands.add_parser(
        "cleanup",
        help="aplica a retenção de dados (auditoria de auth, IPs, sessões, códigos, envios)",
        description=(
            "Apaga eventos de auth com mais de 90 dias, apaga os IPs com mais de 90 dias da "
            "auditoria e das sessões, apaga sessões vencidas, códigos criados há mais de 1 dia, "
            "linhas do mail_log com mais de 48 h e tarefas concluídas há mais de 7 dias. Pode "
            "rodar quantas vezes quiser."
        ),
    ).set_defaults(handler=_cleanup)

    commands.add_parser(
        "run-tasks",
        help="tenta de novo as tarefas pendentes para as aplicações (delete e refresh)",
        description=(
            "Chama a API interna de cada aplicação do IMAGO_APPS para as tarefas pendentes "
            "(apagar os dados de uma conta, atualizar a cópia da conta). Uma aplicação fora do "
            "ar não para as outras: a falha fica na tarefa e é tentada de novo na próxima "
            "execução. Sai com 0 mesmo com falhas; só um erro geral (banco, config) sai com 1."
        ),
    ).set_defaults(handler=_run_tasks)

    reapply = commands.add_parser(
        "reapply-deletions",
        help="depois de restaurar um backup, refaz as exclusões de conta que o log lista",
        description=(
            "Lê do stdin as linhas do journalctl -u app-imago -o cat (as de 'conta <id> "
            "excluída'; as outras são ignoradas) ou ids soltos, um por linha, ou recebe os ids "
            "como argumentos, e refaz cada exclusão sem mandar email: a conta que ainda existe no "
            "imago é apagada de novo, com o delete de todas as aplicações do IMAGO_APPS, e a que "
            "já não existe recebe o delete em cada aplicação. O último admin ativo é pulado com "
            "um aviso. Pode rodar quantas vezes quiser."
        ),
    )
    reapply.add_argument(
        "ids",
        nargs="*",
        type=_account_id_argument,
        metavar="id",
        help="ids das contas (de 1 a 2^53 - 1); sem eles, lê do stdin",
    )
    reapply.set_defaults(handler=_reapply_deletions)

    import_users = commands.add_parser(
        "import-users",
        help="importa as contas do ethos (export-users), uma vez só, pelo stdin",
        description=(
            "Passagem do login do ethos para o imago: lê do stdin uma linha JSON por conta, no "
            "formato do export-users do ethos, e grava todas numa transação só, com os mesmos "
            "ids e sem o aceite dos termos. Não grava nada se uma linha for inválida, se um id ou "
            "email se repetir na entrada ou já existir no imago. Imprime só as contagens."
        ),
    )
    import_users.add_argument(
        "source", choices=["-"], help="- (o stdin; as contas nunca passam por arquivo)"
    )
    import_users.set_defaults(handler=_import_users)

    create_admin = commands.add_parser(
        "create-admin",
        help="torna admin uma conta que já existe (único jeito de criar admin)",
        description=(
            "Liga o is_admin da conta com esse email e grava admin_created na auditoria. A conta "
            "precisa existir (a pessoa entra no imago uma vez antes) e não pode estar bloqueada "
            "nem em exclusão. Rodar de novo numa conta que já é admin não muda nada."
        ),
    )
    create_admin.add_argument("email", help="email da conta (maiúsculas e espaços não importam)")
    create_admin.set_defaults(handler=_create_admin)

    commands.add_parser(
        "seed",
        help="cria as contas de exemplo 101, 102 e 103 (só com APP_ENV=dev)",
        description=(
            "Cria as contas ana@ (admin), bia@ e caio@example.com, com os ids fixos 101, 102 e "
            "103 que os seeds das aplicações usam, numa transação só. Recusa rodar fora de "
            "APP_ENV=dev. Se alguma das contas já existe, não muda nada."
        ),
    ).set_defaults(handler=_seed)

    return parser


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    app_transport: httpx2.BaseTransport | None = None,
    mail_backend: MailBackend | None = None,
) -> int:
    """Roda o comando de `argv` (padrão: sys.argv) e devolve o código de saída.

    `app_transport` e `mail_backend`: só para os testes (ver `CommandContext`).
    """
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
        context = CommandContext(
            settings, create_session_factory(engine), app_transport, mail_backend
        )
        return handler(context, args)
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
