"""Tarefas do imago para as aplicações (`app_tasks`, ETH-59).

Duas ações, cada uma um `POST` na API interna da aplicação (`http://127.0.0.1:<porta>`, do
`IMAGO_APPS`), com o token dela (`IMAGO_APP_TOKENS`) em `Authorization: Bearer`:

- `delete`: `POST /internal/users/{id}/delete`, sem corpo. A aplicação apaga os dados da pessoa
  (exclusão de conta, `app/deletion.py`);
- `refresh`: `POST /internal/users/{id}/refresh` com `{email, locale, timezone}`. A aplicação
  atualiza a cópia da conta em `app_users` (`PATCH /me`, troca de email pelo admin).

Só a resposta 200 conta como sucesso; qualquer outro status, erro de conexão ou o timeout de
`CALL_TIMEOUT_SECONDS` é falha. Cada chamada é independente: uma aplicação fora do ar não impede
as outras de receberem as delas.

Ciclo de uma tarefa:

1. `request_tasks`, dentro do `write_transaction` da mudança: uma tarefa por aplicação do
   `IMAGO_APPS`, no máximo uma pendente por (conta, aplicação, ação) (índice único parcial
   `uq_app_tasks_pending`). Pedir de novo com uma pendente não cria linha nova;
2. depois do commit, `schedule` a tenta em `BackgroundTasks`; se falhar, o `run-tasks` do
   `imago-cleanup.timer` tenta de novo de hora em hora (`run_pending`);
3. sucesso grava `done_at`; falha soma 1 em `attempts` e grava `last_attempt_at`. A partir da
   `ERROR_AFTER_FAILURES`ª falha seguida, cada tentativa grava uma linha de erro no log (journald),
   com o id da conta, nunca o email.

O `refresh` leva os valores da conta na hora da chamada, nunca os do momento em que a tarefa foi
criada: uma tarefa que falhou e roda depois não desfaz uma mudança mais nova. E, se a conta mudou
durante a chamada (a mudança nova achou esta tarefa pendente e não criou outra), a tarefa não é
concluída: a chamada se repete com os valores novos, até `MAX_REFRESH_ROUNDS` vezes.

Concorrência: dentro do processo, uma tarefa roda numa execução por vez (`_claim`); outra que a
encontre em andamento desiste (`BUSY`), e a que está rodando vê a mudança no fim da chamada. Entre
processos (o servidor e o `run-tasks`), as leituras e escritas de cada passo vão em
`write_transaction` (BEGIN IMMEDIATE): no pior caso a mesma tarefa é chamada duas vezes, o que as
aplicações aceitam (as duas rotas são idempotentes).
"""

import logging
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

import httpx2
from fastapi import BackgroundTasks, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import ImagoApp, Settings
from app.db import require_write_transaction, write_transaction
from app.models import AppTask, TaskAction, User, UserStatus, utcnow

logger = logging.getLogger(__name__)

# Timeout de cada chamada a uma aplicação (conexão, envio, leitura e espera no pool)
CALL_TIMEOUT_SECONDS = 10.0
# A partir de quantas falhas seguidas cada tentativa grava uma linha de erro no log
ERROR_AFTER_FAILURES = 5
# Quantas vezes um refresh se repete numa execução quando a conta muda durante a chamada
MAX_REFRESH_ROUNDS = 3


class TaskOutcome(StrEnum):
    """Resultado de uma execução de tarefa (`run_task`)."""

    # A aplicação respondeu 200: `done_at` gravado
    DONE = "done"
    # A chamada falhou: `attempts` e `last_attempt_at` gravados; fica para a próxima execução
    FAILED = "failed"
    # Outra execução deste processo está com ela agora
    BUSY = "busy"
    # A conta mudou a cada chamada, `MAX_REFRESH_ROUNDS` vezes: fica pendente, sem contar falha
    PENDING = "pending"
    # Já concluída ou apagada (conta excluída, exclusão começou): nada a fazer
    GONE = "gone"


@dataclass(frozen=True, slots=True)
class TaskContext:
    """O que roda as tarefas precisa: a config, o banco e o transporte HTTP.

    `transport` só existe para os testes (aplicações falsas, `httpx2.MockTransport`); em produção
    é None e as chamadas saem pela rede (127.0.0.1).
    """

    settings: Settings
    session_factory: sessionmaker[Session]
    transport: httpx2.BaseTransport | None = None

    def http_client(self) -> httpx2.Client:
        # trust_env=False: nenhum HTTP_PROXY do ambiente desvia as chamadas a 127.0.0.1.
        # Redirecionamento não é seguido: 3xx conta como falha
        return httpx2.Client(
            transport=self.transport,
            timeout=CALL_TIMEOUT_SECONDS,
            trust_env=False,
            follow_redirects=False,
        )


def get_task_context(request: Request) -> TaskContext:
    """Dependência do FastAPI: o TaskContext montado na subida do app."""
    return request.app.state.task_context


TaskContextDep = Annotated[TaskContext, Depends(get_task_context)]


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Quantas tarefas cada resultado teve numa execução de `run_pending`."""

    done: int = 0
    failed: int = 0
    busy: int = 0
    pending: int = 0
    gone: int = 0

    @property
    def tried(self) -> int:
        return self.done + self.failed + self.busy + self.pending + self.gone


def refresh_payload(user: User) -> dict[str, str]:
    """Corpo do `refresh`: os valores atuais da conta."""
    return {"email": user.email, "locale": user.locale, "timezone": user.timezone}


def _pending(user_id: int, action: TaskAction) -> list[Any]:
    return [
        AppTask.user_id == user_id,
        AppTask.action == action.value,
        AppTask.done_at.is_(None),
    ]


def request_tasks(session: Session, settings: Settings, *, user_id: int, action: TaskAction) -> int:
    """Garante uma tarefa pendente de `action` para cada aplicação do `IMAGO_APPS`.

    Aplicação que já tem uma pendente para a conta não ganha outra. Devolve quantas criou. Exige
    `write_transaction`: a leitura das pendentes e a criação ficam protegidas pela mesma trava.
    """
    require_write_transaction(session)
    pending = set(session.scalars(select(AppTask.app).where(*_pending(user_id, action))))
    now = utcnow()
    created = 0
    for name in settings.app_names:
        if name not in pending:
            session.add(AppTask(user_id=user_id, app=name, action=action.value, created_at=now))
            created += 1
    return created


def cancel_tasks(session: Session, *, user_id: int, action: TaskAction) -> int:
    """Apaga as tarefas pendentes de `action` da conta e devolve quantas.

    Exige `write_transaction`.
    """
    require_write_transaction(session)
    result = session.execute(
        delete(AppTask).where(*_pending(user_id, action)),
        execution_options={"synchronize_session": False},
    )
    return result.rowcount


def schedule(
    background_tasks: BackgroundTasks, context: TaskContext, *, user_id: int, action: TaskAction
) -> None:
    """Tenta as tarefas pendentes de `action` da conta depois da resposta.

    Chame depois do `write_transaction` que as criou fechar. Sem aplicações no `IMAGO_APPS`, não
    há o que tentar.
    """
    if context.settings.imago_apps:
        background_tasks.add_task(run_in_background, context, user_id=user_id, action=action)


def run_in_background(context: TaskContext, *, user_id: int, action: TaskAction) -> None:
    """`run_pending` de uma conta, para `BackgroundTasks`: nunca levanta.

    Um erro inesperado (banco travado, por exemplo) vira uma linha de log com o tipo do erro; as
    tarefas continuam pendentes para o `run-tasks`.
    """
    try:
        run_pending(context, user_id=user_id, action=action)
    except Exception as exc:
        logger.error(
            "tarefas %s da conta %d não rodaram (%s); ficam para o run-tasks",
            action.value,
            user_id,
            type(exc).__name__,
        )


def run_pending(
    context: TaskContext, *, user_id: int | None = None, action: TaskAction | None = None
) -> RunSummary:
    """Tenta as tarefas pendentes (de uma conta e de uma ação, se dadas), em ordem de criação.

    Cada tarefa roda na sua transação; uma falha não para as outras. Erros do banco propagam.
    """
    conditions: list[Any] = [AppTask.done_at.is_(None)]
    if user_id is not None:
        conditions.append(AppTask.user_id == user_id)
    if action is not None:
        conditions.append(AppTask.action == action.value)
    with context.session_factory() as session:
        task_ids = list(session.scalars(select(AppTask.id).where(*conditions).order_by(AppTask.id)))
    if not task_ids:
        return RunSummary()
    with context.http_client() as client:
        outcomes = Counter(run_task(context, client, task_id) for task_id in task_ids)
    return RunSummary(**{outcome.value: total for outcome, total in outcomes.items()})


# Tarefas em andamento neste processo (ids), para a mesma tarefa não rodar em duas threads
_running: set[int] = set()
_running_lock = threading.Lock()


def _claim(task_id: int) -> bool:
    with _running_lock:
        if task_id in _running:
            return False
        _running.add(task_id)
        return True


def _release(task_id: int) -> None:
    with _running_lock:
        _running.discard(task_id)


def run_task(context: TaskContext, client: httpx2.Client, task_id: int) -> TaskOutcome:
    """Chama a aplicação da tarefa e grava o resultado (ver o docstring do módulo)."""
    if not _claim(task_id):
        return TaskOutcome.BUSY
    try:
        with context.session_factory() as session:
            return _run(session, context.settings, client, task_id)
    finally:
        _release(task_id)


@dataclass(frozen=True, slots=True)
class _Attempt:
    """Uma chamada a fazer: a tarefa, a aplicação e o corpo (no refresh)."""

    task_id: int
    user_id: int
    action: TaskAction
    app: ImagoApp
    token: str = field(repr=False)
    payload: dict[str, str] | None = field(default=None, repr=False)


def _run(session: Session, settings: Settings, client: httpx2.Client, task_id: int) -> TaskOutcome:
    attempt = _begin(session, settings, task_id)
    rounds = 0
    while isinstance(attempt, _Attempt):
        if rounds == MAX_REFRESH_ROUNDS:
            return TaskOutcome.PENDING
        rounds += 1
        attempt = _finish(session, attempt, _call(client, attempt))
    return attempt


def _load(session: Session, task_id: int) -> tuple[AppTask, User] | None:
    """A tarefa e a conta dela (sempre existe: a tarefa sai junto, por ON DELETE CASCADE)."""
    row = session.execute(
        select(AppTask, User)
        .join(User, User.id == AppTask.user_id)
        .where(AppTask.id == task_id)
        # Relê as linhas mesmo que a sessão já tenha os objetos de outra transação
        .execution_options(populate_existing=True)
    ).one_or_none()
    return None if row is None else (row[0], row[1])


def _begin(session: Session, settings: Settings, task_id: int) -> _Attempt | TaskOutcome:
    """Lê a tarefa e monta a chamada; ou o resultado, se não há o que chamar."""
    with write_transaction(session):
        loaded = _load(session, task_id)
        if loaded is None or loaded[0].done_at is not None:
            return TaskOutcome.GONE
        task, user = loaded
        app, token = settings.app(task.app), settings.app_token(task.app)
        if app is None or token is None:
            # A aplicação saiu do IMAGO_APPS com a tarefa pendente: fica pendente (e com erro no
            # log a cada tentativa, a partir da 5ª), até ela voltar ou alguém resolver à mão
            return _failed(task, "aplicação fora do IMAGO_APPS", utcnow())
        action = TaskAction(task.action)
        payload = None
        if action is TaskAction.REFRESH:
            if user.status != UserStatus.ACTIVE.value:
                # A exclusão já começou: as aplicações vão apagar a cópia, não atualizar
                task.done_at = utcnow()
                return TaskOutcome.GONE
            payload = refresh_payload(user)
        return _Attempt(
            task_id=task.id,
            user_id=task.user_id,
            action=action,
            app=app,
            token=token.get_secret_value(),
            payload=payload,
        )


def _call(client: httpx2.Client, attempt: _Attempt) -> str | None:
    """Faz a chamada. None quando a aplicação respondeu 200; senão, o motivo da falha.

    O motivo é o status HTTP ou o tipo do erro: nunca a mensagem, a URL nem o token.
    """
    url = f"{attempt.app.url}/internal/users/{attempt.user_id}/{attempt.action.value}"
    try:
        # stream: o corpo da resposta não é lido (só o status importa)
        with client.stream(
            "POST",
            url,
            headers={"Authorization": f"Bearer {attempt.token}"},
            json=attempt.payload,
        ) as response:
            status = response.status_code
    except httpx2.HTTPError as exc:
        return type(exc).__name__
    return None if status == 200 else f"HTTP {status}"


def _finish(session: Session, attempt: _Attempt, error: str | None) -> _Attempt | TaskOutcome:
    """Grava o resultado da chamada; ou devolve a próxima chamada, se a conta mudou no meio."""
    with write_transaction(session):
        now = utcnow()
        loaded = _load(session, attempt.task_id)
        if loaded is None or loaded[0].done_at is not None:
            # Apagada no meio (a exclusão da conta apaga os refresh pendentes) ou concluída por
            # outro processo
            return TaskOutcome.GONE
        task, user = loaded
        if error is not None:
            return _failed(task, error, now)
        if attempt.action is TaskAction.REFRESH:
            current = refresh_payload(user)
            if current != attempt.payload:
                return replace(attempt, payload=current)
        task.done_at = now
        task.last_attempt_at = now
        return TaskOutcome.DONE


def _failed(task: AppTask, reason: str, now: datetime) -> TaskOutcome:
    task.attempts += 1
    task.last_attempt_at = now
    level = logging.ERROR if task.attempts >= ERROR_AFTER_FAILURES else logging.WARNING
    logger.log(
        level,
        "tarefa %s de %s para a conta %d falhou (%s); %d falhas seguidas",
        task.action,
        task.app,
        task.user_id,
        reason,
        task.attempts,
    )
    return TaskOutcome.FAILED
