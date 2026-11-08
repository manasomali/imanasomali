"""Stack do E2E (Playwright, `apps/ethos/frontend/e2e/`): imago, ethos, nginx de dev e SMTP falso.

O E2E roda contra o caminho de produção, numa origem só (`ORIGIN`, http://127.0.0.1:8080), como
na VM: o nginx da VM (`nginx:1.24`, em container) com as rotas de produção de `infra/apps/*/`, o
`auth_request` que pergunta ao imago quem é o usuário e repassa os `X-User-*` ao ethos, os
backends do imago e do ethos nas portas de produção (o `PORT` de `infra/apps/<nome>/app.conf`) e
o build de produção dos dois fronts. Este processo (o supervisor) sobe, nesta ordem:

1. o servidor SMTP falso (`tests/fake_smtp.py`), com STARTTLS e login obrigatórios, como o
   provedor. O certificado vem de uma CA de teste (`trustme`) gravada em `--data-dir`;
2. o backend do imago (`apps/imago/backend`, com a `.venv` dele), num banco novo migrado pelo
   Alembic, com `EMAIL_BACKEND=smtp` no SMTP falso. O processo confia na CA de teste por
   `SSL_CERT_FILE` (a variável do OpenSSL, lida pelo `ssl.create_default_context()` do
   `SmtpBackend`): o email sai pelo caminho de produção inteiro (STARTTLS com o certificado
   verificado, login, envio), sem ajuste no código do imago. Antes de ele subir, o
   `import-users -` grava as contas de `--imported-admin`: admins vindas do ethos, sem os termos
   aceitos, como na passagem do login (ETH-64);
3. o backend do ethos, num banco novo migrado, chamando o imago em `IMAGO_INTERNAL_URL` com o
   `INTERNAL_API_TOKEN` de dev (o mesmo do `IMAGO_APP_TOKENS` do imago);
4. o nginx de dev (a config do `apps/imago/dev/nginx.sh render`) em container, com o `dist/` dos
   dois fronts (o `npm run build` de cada um vem antes, no `playwright.config.js`). Uma diferença
   da config gerada: o rate limit do login do imago (10 por minuto por IP) sobe para `LOGIN_RATE`,
   porque a suíte faz dezenas de logins do mesmo IP em poucos minutos (o de produção é conferido
   em produção, ETH-43). Com `--host-network` (Linux, como no CI) o container usa a rede da
   máquina, porque lá o `host.docker.internal` não alcança um serviço em 127.0.0.1; sem ela, o
   `host.docker.internal` do Docker Desktop;
5. a caixa de entrada do SMTP falso por HTTP, só em 127.0.0.1: `GET /emails?to=<endereço>`
   devolve `[{"to": [...], "subject": "...", "text": "..."}]`, na ordem de chegada, e
   `GET /health` responde 200. Ela sobe por último: quando responde, o resto está no ar (é a URL
   que o Playwright espera).

Nenhum atalho de login: o E2E lê o código no email, como a pessoa.

Tudo para junto com SIGTERM ou SIGINT (o Playwright manda SIGTERM no fim, também quando a suíte
falha) ou quando um dos processos cai: o container sai com `docker rm --force`, os backends
recebem SIGTERM e a pasta de dados é apagada. O container de uma execução morta com SIGKILL sai
na subida seguinte (o nome é fixo).

Uso, na pasta do backend (o `playwright.config.js` do front faz isso, depois dos builds):

    uv run --frozen python -m tests.e2e_stack --mail-port 47832 \\
        --data-dir ../frontend/e2e/.stack --host-network --imported-admin ana@example.com

`--data-dir` é apagado e recriado a cada subida (só se estiver vazio ou tiver sido criado por este
script, com o arquivo `.ethos-e2e`). Nada disso vai para produção: `tests/` não sobe para a VM.
"""

import argparse
import http.client
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import trustme
from alembic import command
from alembic.config import Config

from app.config import ENV_VARS as ETHOS_ENV_VARS
from app.config import is_email
from tests.fake_smtp import (
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_USER,
    FakeSmtpServer,
    ReceivedEmail,
    start_fake_smtp,
)

HOST = "127.0.0.1"
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parents[2]
IMAGO_BACKEND_DIR = REPO_DIR / "apps" / "imago" / "backend"
INFRA_APPS_DIR = REPO_DIR / "infra" / "apps"
NGINX_SCRIPT = REPO_DIR / "apps" / "imago" / "dev" / "nginx.sh"
# Build de produção de cada front, servido pelo nginx em /var/www/<nome>, como na VM
FRONT_DISTS = {name: REPO_DIR / "apps" / name / "frontend" / "dist" for name in ("imago", "ethos")}
# O `listen=` do apps/imago/dev/nginx.sh (um teste confere): a origem única do E2E. 127.0.0.1, e
# não localhost: o Chromium trata os dois como origem segura (guarda o cookie `Secure` em http),
# e o endereço não depende de o nome resolver para IPv4 ou IPv6
NGINX_PORT = 8080
ORIGIN = f"http://{HOST}:{NGINX_PORT}"
NGINX_IMAGE = "nginx:1.24"
NGINX_CONTAINER = "ethos-e2e-nginx"
# O mesmo prefixo de produção (o nginx tira, o uvicorn recebe no --root-path)
ROOT_PATHS = {"imago": "/api/imago", "ethos": "/api/ethos"}
# Marca a pasta como criada por este script: só ela pode ser apagada na subida seguinte
MARKER = ".ethos-e2e"
# Token do ethos na API interna do imago: o de dev dos `.env.example` das duas aplicações
INTERNAL_API_TOKEN = "dev-only-ethos-token-not-a-secret-0000"  # noqa: S105 (só dev)
# Teto de envio do imago bem acima do que uma execução da suíte manda (dezenas de códigos e
# convites em poucos minutos). Os limites por email (1 código por minuto, 5 por hora) continuam
MAX_EMAILS = 10_000
# Rate limit do login do imago no E2E (ver o item 4 do docstring)
LOGIN_RATE = "100r/s"
_LOGIN_RATE_RE = re.compile(r"(zone=imago_auth:\S+\s+rate=)\d+r/[sm];")
# Contas importadas: ids fixos, num banco novo; fuso e idioma do navegador do E2E
IMPORTED_ID_BASE = 7_000_000_000_000
IMPORTED_TIMEZONE = "America/Sao_Paulo"
IMPORTED_LOCALE = "pt"
# Variáveis que não passam do ambiente deste processo para os backends: as do venv do ethos (o
# imago roda com o dele) e as de config das duas aplicações (uma exportada no shell de quem roda o
# E2E mudaria o comportamento). As de cada backend vêm só de `*_environment`
_INHERITED_BLOCKLIST = frozenset({"VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"})
STARTUP_TIMEOUT = 60.0
POLL_SECONDS = 0.2
STOP_TIMEOUT = 10.0


class StackError(RuntimeError):
    """Algo impede o stack de subir ou de continuar; a mensagem diz o quê."""


class StackStopped(Exception):
    """SIGTERM ou SIGINT no meio da subida: não é erro, é o fim pedido."""


# --- caixa de entrada ---


def describe(email: ReceivedEmail) -> dict[str, object]:
    return {"to": email.rcpt_tos, "subject": email.message["Subject"], "text": email.body("plain")}


def emails_to(smtp: FakeSmtpServer, address: str) -> list[dict[str, object]]:
    """Emails recebidos para `address` (sem diferença de maiúsculas), na ordem de chegada."""
    wanted = address.strip().lower()
    # Cópia da lista: o aiosmtpd acrescenta noutra thread
    received = list(smtp.received)
    return [
        describe(email)
        for email in received
        if any(rcpt.lower() == wanted for rcpt in email.rcpt_tos)
    ]


def mailbox_server(smtp: FakeSmtpServer, port: int) -> ThreadingHTTPServer:
    """Caixa de entrada por HTTP em 127.0.0.1 (porta 0: qualquer livre). Ainda não atende."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            if parts.path == "/health":
                self._reply(HTTPStatus.OK, {"status": "ok"})
                return
            to = parse_qs(parts.query).get("to", [])
            if parts.path != "/emails" or len(to) != 1 or not to[0].strip():
                self._reply(HTTPStatus.NOT_FOUND, {"error": "use GET /emails?to=<endereço>"})
                return
            self._reply(HTTPStatus.OK, emails_to(smtp, to[0]))

        def _reply(self, status: HTTPStatus, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            # Sem uma linha por request: o E2E consulta a caixa várias vezes por teste
            pass

    return ThreadingHTTPServer((HOST, port), Handler)


# --- config das aplicações ---


def prepare_data_dir(path: Path) -> Path:
    """Apaga e recria a pasta, se ela não existe, está vazia ou foi criada por este script."""
    path = path.resolve()
    if path.exists():
        if not path.is_dir():
            raise StackError(f"--data-dir {path} não é uma pasta")
        if any(path.iterdir()) and not (path / MARKER).is_file():
            raise StackError(f"--data-dir {path} tem arquivos e não foi criada pelo E2E")
        shutil.rmtree(path)
    path.mkdir(parents=True)
    (path / MARKER).touch()
    return path


def app_port(name: str, infra_apps_dir: Path = INFRA_APPS_DIR) -> int:
    """O `PORT` de `infra/apps/<name>/app.conf`, o mesmo que o nginx.sh põe na config do nginx."""
    conf = infra_apps_dir / name / "app.conf"
    try:
        lines = conf.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise StackError(f"não consegui ler {conf}") from None
    ports = [line.removeprefix("PORT=") for line in lines if line.startswith("PORT=")]
    if not ports or not re.fullmatch(r"[1-9][0-9]{3,4}", ports[-1]):
        raise StackError(f"{conf} sem um PORT válido")
    return int(ports[-1])


def env_file_names(path: Path) -> frozenset[str]:
    """Os nomes das variáveis de um arquivo `NOME=valor` (o `.env.example` de uma aplicação)."""
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            names.add(line.split("=", 1)[0].strip())
    return frozenset(names)


def imago_variable_names() -> frozenset[str]:
    """As variáveis do imago: as do `.env.example` dele (um teste do imago confere com a config)."""
    return env_file_names(IMAGO_BACKEND_DIR / ".env.example")


def ethos_environment(*, data_dir: Path, imago_port: int) -> dict[str, str]:
    """As variáveis do ethos (as de produção, com os valores do E2E)."""
    return {
        "APP_ENV": "dev",
        "APP_URL": f"{ORIGIN}/ethos",
        "DATABASE_PATH": str(data_dir / "ethos.db"),
        "IMAGO_INTERNAL_URL": f"http://{HOST}:{imago_port}",
        "INTERNAL_API_TOKEN": INTERNAL_API_TOKEN,
    }


def imago_environment(*, data_dir: Path, ethos_port: int, smtp_port: int) -> dict[str, str]:
    """As variáveis do imago (as de produção, com os valores do E2E e o SMTP falso)."""
    return {
        "APP_ENV": "dev",
        "APP_URL": f"{ORIGIN}/imago",
        "DATABASE_PATH": str(data_dir / "imago.db"),
        "SUPPORT_EMAIL": "suporte@example.com",
        "MAIL_FROM_ADDRESS": "no-reply@example.com",
        "EMAIL_BACKEND": "smtp",
        "IMAGO_APPS": f"ethos=http://{HOST}:{ethos_port}",
        "IMAGO_APP_TOKENS": f"ethos:{INTERNAL_API_TOKEN}",
        "MAX_EMAILS_PER_DAY": str(MAX_EMAILS),
        "MAX_EMAILS_PER_HOUR": str(MAX_EMAILS),
        "SMTP_HOST": SMTP_HOST,
        "SMTP_PORT": str(smtp_port),
        "SMTP_USER": SMTP_USER,
        "SMTP_PASSWORD": SMTP_PASSWORD,
    }


def child_environment(
    app_environment: Mapping[str, str], inherited: Mapping[str, str] | None = None
) -> dict[str, str]:
    """O ambiente de um backend: o deste processo (`inherited`) sem as variáveis que não passam
    (`_INHERITED_BLOCKLIST` e as de config das duas aplicações), mais `app_environment`."""
    source = os.environ if inherited is None else inherited
    blocked = _INHERITED_BLOCKLIST | set(ETHOS_ENV_VARS) | imago_variable_names()
    environment = {name: value for name, value in source.items() if name not in blocked}
    environment.update(app_environment)
    return environment


def imported_accounts_input(emails: Sequence[str]) -> str:
    """A entrada do `import-users -` do imago: uma linha JSON por conta e a linha final com o
    total, no formato do `export-users` do ethos de antes da passagem. Contas ativas, admins, que
    nunca entraram. O import recusa a entrada inteira sem a linha final."""
    if len(set(emails)) != len(emails):
        raise StackError("--imported-admin repetido")
    lines = []
    for index, email in enumerate(emails):
        if not is_email(email) or email != email.strip().lower():
            raise StackError(
                f"--imported-admin inválido (item {index + 1}): use um email minúsculo"
            )
        record = {
            "id": IMPORTED_ID_BASE + index,
            "email": email,
            "is_active": True,
            "is_admin": True,
            "timezone": IMPORTED_TIMEZONE,
            "locale": IMPORTED_LOCALE,
            "created_at": "2026-01-01T12:00:00.000000Z",
            "last_login_at": None,
        }
        lines.append(json.dumps(record) + "\n")
    lines.append(json.dumps({"end": True, "count": len(emails)}) + "\n")
    return "".join(lines)


def raise_login_rate(conf: Path) -> None:
    """Troca o `rate=` da zona `imago_auth` (o rate limit do login) por `LOGIN_RATE`."""
    text = conf.read_text(encoding="utf-8")
    changed, count = _LOGIN_RATE_RE.subn(rf"\g<1>{LOGIN_RATE};", text)
    if count != 1:
        raise StackError(
            f"{conf}: esperava uma zona imago_auth com um rate= (achei {count}); "
            "o limit_req_zone do infra/apps/imago/nginx-http.conf mudou de forma?"
        )
    conf.write_text(changed, encoding="utf-8", newline="\n")


def _mount(source: Path, target: str) -> str:
    # A vírgula separa as opções do --mount: um caminho com ela seria lido errado
    if "," in str(source):
        raise StackError(f"caminho com vírgula não pode ser montado no container: {source}")
    return f"--mount=type=bind,source={source.as_posix()},target={target},readonly"


def docker_run_args(conf_dir: Path, *, host_network: bool) -> list[str]:
    """O `docker run` do nginx, em primeiro plano (os logs saem junto com os do stack)."""
    args = [
        "docker",
        "run",
        "--rm",
        "--name",
        NGINX_CONTAINER,
        _mount(conf_dir / "conf.d", "/etc/nginx/conf.d"),
        _mount(conf_dir / "apps.d", "/etc/nginx/apps.d"),
    ]
    args += [_mount(dist, f"/var/www/{name}") for name, dist in FRONT_DISTS.items()]
    if host_network:
        args += ["--network", "host"]
    else:
        # Só na interface local da máquina; os backends pela máquina (host.docker.internal)
        args += [
            "--add-host=host.docker.internal:host-gateway",
            "--publish",
            f"{HOST}:{NGINX_PORT}:{NGINX_PORT}",
        ]
    args.append(NGINX_IMAGE)
    return args


def venv_python(project_dir: Path) -> Path:
    """O Python da `.venv` de um projeto do uv."""
    if sys.platform == "win32":
        return project_dir / ".venv" / "Scripts" / "python.exe"
    return project_dir / ".venv" / "bin" / "python"


def uvicorn_args(python: Path | str, name: str, port: int) -> list[str]:
    return [
        str(python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        str(port),
        "--root-path",
        ROOT_PATHS[name],
        # Como na unit de produção (infra/apps/<nome>/app-<nome>.service), sem o log de acesso:
        # o app já registra uma linha por request
        "--proxy-headers",
        "--forwarded-allow-ips=127.0.0.1",
        "--no-access-log",
    ]


def migrate(database_path: Path) -> None:
    """`alembic upgrade head` no banco do ethos, como o `ExecStartPre` da unit em produção."""
    config = Config(BACKEND_DIR / "alembic.ini")
    config.attributes["database_path"] = database_path
    command.upgrade(config, "head")


# --- processos ---


@dataclass(frozen=True, slots=True)
class Service:
    """Um processo filho que fica no ar enquanto o stack roda."""

    name: str
    process: subprocess.Popen[bytes]


def start_service(
    name: str, args: Sequence[str], *, cwd: Path, env: Mapping[str, str] | None
) -> Service:
    # stdout e stderr são os deste processo: os logs aparecem na saída do Playwright
    process = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL)  # noqa: S603
    return Service(name, process)


def stop_service(service: Service, timeout: float = STOP_TIMEOUT) -> None:
    """SIGTERM e espera; SIGKILL se não sair em `timeout` segundos."""
    process = service.process
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_step(
    name: str,
    args: Sequence[str],
    *,
    stop: threading.Event,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    stdin: str | None = None,
) -> None:
    """Roda um comando até o fim; código diferente de 0 é `StackError` (ou `StackStopped`, se um
    sinal chegou no meio: o comando recebeu o mesmo sinal e o código não diz nada)."""
    # Sem `stdin`, o comando não lê nada (nem o terminal de quem rodou o E2E)
    if stdin is None:
        result = subprocess.run(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, check=False)  # noqa: S603
    else:
        result = subprocess.run(args, cwd=cwd, env=env, input=stdin, text=True, check=False)  # noqa: S603
    if stop.is_set():
        raise StackStopped
    if result.returncode != 0:
        raise StackError(f"{name} falhou (código {result.returncode})")


# Sem proxy: tudo é local, e um HTTP_PROXY do ambiente desviaria as requests
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_status(url: str, timeout: float = 2.0) -> int | None:
    """O status de um GET em `url`, ou None se não houve resposta."""
    try:
        with _opener.open(url, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        # O erro carrega a resposta aberta
        exc.close()
        return exc.code
    except OSError, http.client.HTTPException:
        # Conexão recusada, timeout, resposta que não é HTTP
        return None


def wait_for(
    url: str,
    expected: int,
    *,
    watch: Iterable[Service],
    stop: threading.Event,
    timeout: float = STARTUP_TIMEOUT,
) -> None:
    """Espera um GET em `url` responder `expected`. Um processo de `watch` que sai antes é
    `StackError`, como o prazo vencido; um sinal no meio, `StackStopped`."""
    deadline = time.monotonic() + timeout
    watched = list(watch)
    while True:
        for service in watched:
            code = service.process.poll()
            if code is not None:
                raise StackError(f"{service.name} parou antes de {url} responder (código {code})")
        status = http_status(url)
        if status == expected:
            return
        if time.monotonic() >= deadline:
            raise StackError(f"{url} não respondeu {expected} em {timeout:.0f} s ({status})")
        if stop.wait(POLL_SECONDS):
            raise StackStopped


def supervise(services: Iterable[Service], stop: threading.Event) -> None:
    """Fica no ar até um sinal; um processo que sai antes disso é `StackError`."""
    watched = list(services)
    while not stop.wait(POLL_SECONDS):
        for service in watched:
            code = service.process.poll()
            if code is None:
                continue
            # O SIGTERM do Playwright vai para o grupo de processos inteiro: um filho pode sair
            # antes de o sinal chegar a este processo
            if stop.wait(1.0):
                return
            raise StackError(f"{service.name} parou (código {code})")


def remove_container() -> None:
    """`docker rm --force` no container do nginx, se ele existe (o de uma execução morta, na
    subida; o desta, no fim)."""
    subprocess.run(  # noqa: S603
        ["docker", "rm", "--force", NGINX_CONTAINER],  # noqa: S607
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def stop_nginx(service: Service) -> None:
    remove_container()
    stop_service(service)


def check_requirements(imported: Sequence[str]) -> None:
    """O que precisa existir antes de mexer em qualquer coisa."""
    for tool in ("docker", "bash"):
        if shutil.which(tool) is None:
            raise StackError(
                f"{tool} não encontrado: o E2E sobe o nginx de dev em container "
                "(apps/imago/dev/README.md)"
            )
    if not venv_python(IMAGO_BACKEND_DIR).is_file():
        raise StackError("falta a .venv do imago: uv sync --frozen em apps/imago/backend")
    for name, dist in FRONT_DISTS.items():
        if not (dist / "index.html").is_file():
            raise StackError(f"falta o build do {name}: npm run build em apps/{name}/frontend")
    imported_accounts_input(imported)


# --- stack ---


def start_imago(
    cleanup: ExitStack,
    *,
    data_dir: Path,
    ports: Mapping[str, int],
    smtp_port: int,
    ca_file: Path,
    imported: Sequence[str],
    stop: threading.Event,
) -> Service:
    """Banco novo migrado, as contas importadas e o servidor do imago, já respondendo."""
    environment = child_environment(
        imago_environment(data_dir=data_dir, ethos_port=ports["ethos"], smtp_port=smtp_port)
    )
    python = str(venv_python(IMAGO_BACKEND_DIR))
    run_step(
        "migração do imago",
        [python, "-m", "alembic", "upgrade", "head"],
        cwd=IMAGO_BACKEND_DIR,
        env=environment,
        stop=stop,
    )
    if imported:
        run_step(
            "import-users do imago",
            [python, "-m", "app.cli", "import-users", "-"],
            cwd=IMAGO_BACKEND_DIR,
            env=environment,
            stdin=imported_accounts_input(imported),
            stop=stop,
        )
    imago = start_service(
        "imago",
        uvicorn_args(python, "imago", ports["imago"]),
        cwd=IMAGO_BACKEND_DIR,
        env={**environment, "SSL_CERT_FILE": str(ca_file)},
    )
    cleanup.callback(stop_service, imago)
    wait_for(f"http://{HOST}:{ports['imago']}/health", HTTPStatus.OK, watch=[imago], stop=stop)
    return imago


def start_ethos(
    cleanup: ExitStack, *, data_dir: Path, ports: Mapping[str, int], stop: threading.Event
) -> Service:
    """Banco novo migrado e o servidor do ethos, já respondendo."""
    migrate(data_dir / "ethos.db")
    ethos = start_service(
        "ethos",
        uvicorn_args(sys.executable, "ethos", ports["ethos"]),
        cwd=BACKEND_DIR,
        env=child_environment(ethos_environment(data_dir=data_dir, imago_port=ports["imago"])),
    )
    cleanup.callback(stop_service, ethos)
    wait_for(f"http://{HOST}:{ports['ethos']}/health", HTTPStatus.OK, watch=[ethos], stop=stop)
    return ethos


def start_nginx(
    cleanup: ExitStack,
    *,
    data_dir: Path,
    host_network: bool,
    backends: Sequence[Service],
    stop: threading.Event,
) -> Service:
    """A config do nginx.sh, o container e a conferência das rotas pela origem do E2E."""
    conf_dir = data_dir / "nginx"
    render = ["bash", NGINX_SCRIPT.as_posix(), "render", conf_dir.as_posix()]
    if host_network:
        render.append("--host-network")
    run_step("nginx.sh render", render, cwd=REPO_DIR, stop=stop)
    raise_login_rate(conf_dir / "conf.d" / "app-imago.conf")

    inspect = subprocess.run(  # noqa: S603
        ["docker", "image", "inspect", NGINX_IMAGE],  # noqa: S607
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if inspect.returncode != 0:
        run_step("docker pull", ["docker", "pull", NGINX_IMAGE], cwd=data_dir, stop=stop)
    remove_container()
    nginx = start_service(
        "nginx", docker_run_args(conf_dir, host_network=host_network), cwd=data_dir, env=None
    )
    cleanup.callback(stop_nginx, nginx)
    watch = [nginx, *backends]
    wait_for(f"{ORIGIN}/api/imago/health", HTTPStatus.OK, watch=watch, stop=stop)
    # Sem cookie, o auth_request chega ao imago e o ethos responde 401 (500: o nginx não alcança
    # o imago)
    status = http_status(f"{ORIGIN}/api/ethos/me")
    if status != HTTPStatus.UNAUTHORIZED:
        raise StackError(f"{ORIGIN}/api/ethos/me respondeu {status}, e não 401")
    for name in FRONT_DISTS:
        wait_for(f"{ORIGIN}/{name}/", HTTPStatus.OK, watch=watch, stop=stop)
    return nginx


def run(args: argparse.Namespace, stop: threading.Event) -> None:
    check_requirements(args.imported_admin)
    data_dir = prepare_data_dir(args.data_dir)
    with ExitStack() as cleanup:
        cleanup.callback(shutil.rmtree, data_dir, ignore_errors=True)
        ca = trustme.CA()
        ca_file = data_dir / "smtp-ca.pem"
        ca.cert_pem.write_to_path(str(ca_file))
        smtp, stop_smtp = start_fake_smtp(ca)
        cleanup.callback(stop_smtp)

        ports = {name: app_port(name) for name in ROOT_PATHS}
        imago = start_imago(
            cleanup,
            data_dir=data_dir,
            ports=ports,
            smtp_port=smtp.port,
            ca_file=ca_file,
            imported=args.imported_admin,
            stop=stop,
        )
        ethos = start_ethos(cleanup, data_dir=data_dir, ports=ports, stop=stop)
        nginx = start_nginx(
            cleanup,
            data_dir=data_dir,
            host_network=args.host_network,
            backends=[imago, ethos],
            stop=stop,
        )

        mailbox = mailbox_server(smtp, args.mail_port)
        cleanup.callback(mailbox.server_close)
        thread = threading.Thread(target=mailbox.serve_forever, daemon=True)
        thread.start()
        cleanup.callback(mailbox.shutdown)
        print(f"stack do E2E no ar em {ORIGIN}", file=sys.stderr, flush=True)
        supervise([imago, ethos, nginx], stop)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mail-port", type=int, required=True, help="caixa de entrada")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument(
        "--host-network",
        action="store_true",
        help="o container do nginx na rede da máquina (Linux sem Docker Desktop)",
    )
    parser.add_argument(
        "--imported-admin",
        action="append",
        default=[],
        metavar="EMAIL",
        help="conta admin importada do ethos, sem os termos aceitos (repetível)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    stop = threading.Event()
    # Os sinais só marcam o fim: a limpeza roda na volta do `run`
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    with suppress(StackStopped):
        run(args, stop)


if __name__ == "__main__":
    try:
        main()
    except StackError as exc:
        raise SystemExit(f"erro: {exc}") from None
