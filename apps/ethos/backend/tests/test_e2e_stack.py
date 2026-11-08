"""O stack do E2E (`tests/e2e_stack.py`): pasta de dados, config dos backends, nginx, processos e
caixa de entrada. O stack inteiro (com o docker) só roda no job E2E do CI."""

import http.client
import json
import re
import signal
import subprocess
import sys
import threading
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.config import load_settings
from tests import e2e_stack
from tests.e2e_stack import (
    FRONT_DISTS,
    IMAGO_BACKEND_DIR,
    INTERNAL_API_TOKEN,
    LOGIN_RATE,
    MARKER,
    NGINX_CONTAINER,
    NGINX_IMAGE,
    NGINX_PORT,
    NGINX_SCRIPT,
    ORIGIN,
    REPO_DIR,
    Service,
    StackError,
    StackStopped,
    app_port,
    child_environment,
    docker_run_args,
    env_file_names,
    ethos_environment,
    http_status,
    imago_environment,
    imago_variable_names,
    imported_accounts_input,
    mailbox_server,
    prepare_data_dir,
    raise_login_rate,
    run_step,
    stop_service,
    supervise,
    uvicorn_args,
    wait_for,
)

ETHOS_ENV_EXAMPLE = REPO_DIR / "apps" / "ethos" / "backend" / ".env.example"
IMAGO_ENV_EXAMPLE = IMAGO_BACKEND_DIR / ".env.example"
IMAGO_NGINX_HTTP = REPO_DIR / "infra" / "apps" / "imago" / "nginx-http.conf"


def _message(to: str, subject: str = "Seu código") -> EmailMessage:
    message = EmailMessage()
    message["From"] = "manasomali.com <no-reply@example.com>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content("Código: 123456\n")
    return message


def _get(port: int, path: str) -> tuple[int, object]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _env_value(path: Path, name: str) -> str:
    [value] = [
        line.split("=", 1)[1]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"{name}=")
    ]
    return value


def _python(code: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", code])  # noqa: S603


@pytest.fixture
def status_server():
    """Servidor HTTP em 127.0.0.1 que responde `GET /<status>` com esse status."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(int(self.path.strip("/")))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


# --- pasta de dados ---


def test_prepare_data_dir_creates_and_recreates(tmp_path):
    path = prepare_data_dir(tmp_path / "stack")
    assert sorted(item.name for item in path.iterdir()) == [MARKER]
    (path / "ethos.db").write_text("velho")

    again = prepare_data_dir(tmp_path / "stack")

    assert again == path
    assert sorted(item.name for item in again.iterdir()) == [MARKER]


def test_prepare_data_dir_accepts_empty_dir(tmp_path):
    assert (prepare_data_dir(tmp_path) / MARKER).is_file()


def test_prepare_data_dir_never_deletes_a_foreign_dir(tmp_path):
    keep = tmp_path / "importante.txt"
    keep.write_text("não apagar")

    with pytest.raises(StackError, match="não foi criada pelo E2E"):
        prepare_data_dir(tmp_path)
    with pytest.raises(StackError, match="não é uma pasta"):
        prepare_data_dir(keep)

    assert keep.read_text() == "não apagar"


# --- config dos backends ---


def test_app_port_reads_the_app_conf(tmp_path):
    (tmp_path / "ok").mkdir()
    (tmp_path / "ok" / "app.conf").write_text("# porta\nPORT=3001\nPYTHON_VERSION=3.14.3\n")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "app.conf").write_text("PORT=80\n")
    (tmp_path / "none").mkdir()
    (tmp_path / "none" / "app.conf").write_text("PYTHON_VERSION=3.14.3\n")

    assert app_port("ok", tmp_path) == 3001
    for name in ("bad", "none"):
        with pytest.raises(StackError, match="sem um PORT válido"):
            app_port(name, tmp_path)
    with pytest.raises(StackError, match="não consegui ler"):
        app_port("missing", tmp_path)


def test_nginx_port_is_the_listen_of_nginx_sh():
    listen = re.search(r"^listen=(\d+)$", NGINX_SCRIPT.read_text(encoding="utf-8"), re.MULTILINE)
    assert listen is not None
    assert int(listen.group(1)) == NGINX_PORT
    assert f"image={NGINX_IMAGE}\n" in NGINX_SCRIPT.read_text(encoding="utf-8")


def test_ethos_environment_is_a_valid_config(tmp_path):
    environment = ethos_environment(data_dir=tmp_path, imago_port=3003)

    settings = load_settings(environment)

    assert settings.app_origin == ORIGIN
    assert settings.database_path == tmp_path / "ethos.db"
    assert settings.imago_internal_url == "http://127.0.0.1:3003"


def test_imago_environment_uses_imago_variables(tmp_path):
    environment = imago_environment(data_dir=tmp_path, ethos_port=3001, smtp_port=2525)

    # O imago não sobe neste venv: o .env.example dele tem os nomes da config (o teste dele confere)
    assert set(environment) <= imago_variable_names()
    assert environment["APP_URL"] == f"{ORIGIN}/imago"
    assert environment["DATABASE_PATH"] == str(tmp_path / "imago.db")
    assert environment["IMAGO_APPS"] == "ethos=http://127.0.0.1:3001"
    assert environment["SMTP_PORT"] == "2525"
    assert environment["EMAIL_BACKEND"] == "smtp"
    assert int(environment["MAX_EMAILS_PER_HOUR"]) <= int(environment["MAX_EMAILS_PER_DAY"])


def test_internal_token_is_the_dev_one_of_both_apps(tmp_path):
    # O token de dev dos .env.example: o mesmo nos dois sentidos, no formato que o imago aceita
    assert _env_value(ETHOS_ENV_EXAMPLE, "INTERNAL_API_TOKEN") == INTERNAL_API_TOKEN
    assert _env_value(IMAGO_ENV_EXAMPLE, "IMAGO_APP_TOKENS") == f"ethos:{INTERNAL_API_TOKEN}"
    environment = imago_environment(data_dir=tmp_path, ethos_port=3001, smtp_port=2525)
    assert environment["IMAGO_APP_TOKENS"] == f"ethos:{INTERNAL_API_TOKEN}"
    assert re.fullmatch(r"[A-Za-z0-9_-]{32,512}", INTERNAL_API_TOKEN)


def test_env_file_names(tmp_path):
    path = tmp_path / ".env.example"
    text = "# comentário com A=B\nAPP_ENV=dev\n\nSMTP_HOST=\n  EMPTY = x\nsolto\n"
    path.write_text(text, encoding="utf-8")

    assert env_file_names(path) == {"APP_ENV", "SMTP_HOST", "EMPTY"}


def test_child_environment_drops_app_variables():
    inherited = {
        "PATH": "/usr/bin",
        "HOME": "/home/e2e",
        "VIRTUAL_ENV": "/repo/apps/ethos/backend/.venv",
        "PYTHONPATH": "/outro",
        # Exportadas no shell de quem roda: nenhuma chega aos backends
        "MAX_HABITS_PER_USER": "1",
        "SMTP_HOST": "smtp.example.com",
        "DATABASE_PATH": "outro.db",
    }

    environment = child_environment({"APP_ENV": "dev"}, inherited)

    assert environment == {"PATH": "/usr/bin", "HOME": "/home/e2e", "APP_ENV": "dev"}


def test_imported_accounts_input():
    lines = imported_accounts_input(["a@example.com", "b@example.com"]).splitlines()

    *records, end = [json.loads(line) for line in lines]
    # A linha final do export-users, sem a qual o import-users do imago não grava nada
    assert end == {"end": True, "count": 2}
    assert [record["email"] for record in records] == ["a@example.com", "b@example.com"]
    assert len({record["id"] for record in records}) == 2
    for record in records:
        # Os campos do import-users do imago (apps/imago/backend/app/import_users.py)
        assert list(record) == [
            "id",
            "email",
            "is_active",
            "is_admin",
            "timezone",
            "locale",
            "created_at",
            "last_login_at",
        ]
        assert record["is_active"] is True
        assert record["is_admin"] is True
        assert 1 <= record["id"] <= 2**53 - 1
        assert record["created_at"].endswith("Z")
    assert json.loads(imported_accounts_input([])) == {"end": True, "count": 0}


@pytest.mark.parametrize("emails", [["A@example.com"], ["sem-arroba"], ["a@example.com"] * 2])
def test_imported_accounts_input_refuses_bad_emails(emails):
    with pytest.raises(StackError, match="--imported-admin"):
        imported_accounts_input(emails)


# --- nginx ---


def test_raise_login_rate(tmp_path):
    conf = tmp_path / "app-imago.conf"
    conf.write_text(IMAGO_NGINX_HTTP.read_text(encoding="utf-8"), encoding="utf-8")

    raise_login_rate(conf)

    text = conf.read_text(encoding="utf-8")
    assert f"zone=imago_auth:1m rate={LOGIN_RATE};" in text
    assert "10r/m" not in text


def test_raise_login_rate_refuses_an_unknown_form(tmp_path):
    conf = tmp_path / "app-imago.conf"
    zone = "limit_req_zone $binary_remote_addr zone=outra:1m rate=10r/m;\n"
    conf.write_text(zone, encoding="utf-8")

    with pytest.raises(StackError, match="zona imago_auth"):
        raise_login_rate(conf)

    assert "rate=10r/m" in conf.read_text(encoding="utf-8")


def test_docker_run_args(tmp_path):
    host = docker_run_args(tmp_path, host_network=True)
    bridge = docker_run_args(tmp_path, host_network=False)

    for args in (host, bridge):
        assert args[:5] == ["docker", "run", "--rm", "--name", NGINX_CONTAINER]
        assert args[-1] == NGINX_IMAGE
        mounts = [arg for arg in args if arg.startswith("--mount=")]
        assert len(mounts) == 2 + len(FRONT_DISTS)
        conf = f"source={tmp_path.as_posix()}/conf.d,target=/etc/nginx/conf.d"
        assert f"--mount=type=bind,{conf},readonly" in mounts
        ethos = f"source={FRONT_DISTS['ethos'].as_posix()},target=/var/www/ethos"
        assert f"--mount=type=bind,{ethos},readonly" in mounts
    assert host[-3:-1] == ["--network", "host"]
    assert "--publish" not in host
    assert "127.0.0.1:8080:8080" in bridge
    assert "--add-host=host.docker.internal:host-gateway" in bridge


def test_docker_run_args_refuse_a_comma_in_a_path(tmp_path):
    with pytest.raises(StackError, match="vírgula"):
        docker_run_args(tmp_path / "a,b", host_network=True)


def test_uvicorn_args_have_the_production_root_path():
    args = uvicorn_args("python", "imago", 3003)

    assert args[:4] == ["python", "-m", "uvicorn", "app.main:app"]
    assert args[args.index("--root-path") + 1] == "/api/imago"
    assert args[args.index("--port") + 1] == "3003"
    assert args[args.index("--host") + 1] == "127.0.0.1"


# --- processos ---


def test_run_step(tmp_path):
    stop = threading.Event()
    run_step("ok", [sys.executable, "-c", "pass"], stop=stop, cwd=tmp_path)
    # O stdin chega ao comando
    run_step(
        "lê",
        [sys.executable, "-c", "import sys; sys.exit(sys.stdin.read() != 'x\\n')"],
        stop=stop,
        cwd=tmp_path,
        stdin="x\n",
    )

    with pytest.raises(StackError, match=r"falha falhou \(código 3\)"):
        run_step("falha", [sys.executable, "-c", "raise SystemExit(3)"], stop=stop, cwd=tmp_path)
    stop.set()
    with pytest.raises(StackStopped):
        run_step("falha", [sys.executable, "-c", "raise SystemExit(3)"], stop=stop, cwd=tmp_path)


def test_http_status(status_server):
    assert http_status(f"{status_server}/200") == 200
    assert http_status(f"{status_server}/401") == 401
    assert http_status(f"{status_server}/503") == 503


def test_http_status_without_a_server():
    with ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler) as server:
        port = server.server_address[1]
    # A porta acabou de ser liberada: conexão recusada
    assert http_status(f"http://127.0.0.1:{port}/health", timeout=1) is None


def test_wait_for(status_server):
    stop = threading.Event()
    alive = Service("vivo", _python("import time; time.sleep(30)"))
    try:
        wait_for(f"{status_server}/200", 200, watch=[alive], stop=stop)
        with pytest.raises(StackError, match=r"não respondeu 200 em 0 s \(503\)"):
            wait_for(f"{status_server}/503", 200, watch=[alive], stop=stop, timeout=0.3)
        stop.set()
        with pytest.raises(StackStopped):
            wait_for(f"{status_server}/503", 200, watch=[alive], stop=stop)
    finally:
        stop_service(alive)


def test_wait_for_fails_when_a_watched_process_exits(status_server):
    dead = Service("imago", _python("raise SystemExit(4)"))
    dead.process.wait()

    with pytest.raises(StackError, match=r"imago parou antes de .* responder \(código 4\)"):
        wait_for(f"{status_server}/503", 200, watch=[dead], stop=threading.Event())


def test_supervise_returns_on_a_signal():
    stop = threading.Event()
    alive = Service("vivo", _python("import time; time.sleep(30)"))
    try:
        timer = threading.Timer(0.3, stop.set)
        timer.start()
        supervise([alive], stop)
        timer.join()
    finally:
        stop_service(alive)
    assert alive.process.poll() is not None


def test_supervise_fails_when_a_process_exits():
    dead = Service("nginx", _python("raise SystemExit(1)"))
    dead.process.wait()

    with pytest.raises(StackError, match=r"nginx parou \(código 1\)"):
        supervise([dead], threading.Event())


def test_supervise_accepts_a_process_that_exits_with_the_signal():
    # O SIGTERM do Playwright chega ao grupo inteiro: o filho pode sair antes do aviso daqui
    stop = threading.Event()
    dead = Service("ethos", _python("raise SystemExit(0)"))
    dead.process.wait()
    timer = threading.Timer(0.3, stop.set)
    timer.start()

    supervise([dead], stop)
    timer.join()


def test_stop_service_kills_what_ignores_sigterm():
    code = (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('pronto', flush=True)\n"
        "time.sleep(30)\n"
    )
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", code], stdout=subprocess.PIPE
    )
    assert process.stdout is not None
    # O handler já está instalado quando a linha chega (no Windows, com \r\n)
    assert process.stdout.readline().rstrip() == b"pronto"

    stop_service(Service("teimoso", process), timeout=0.5)

    assert process.poll() is not None
    process.stdout.close()


def test_main_installs_the_signal_handlers_and_stops_quietly(monkeypatch, tmp_path):
    installed = {}
    # Sem trocar os handlers do próprio pytest: o monkeypatch devolve o signal.signal no fim
    monkeypatch.setattr(e2e_stack.signal, "signal", installed.__setitem__)

    def interrupted(args, stop):
        assert args.imported_admin == ["a@example.com", "b@example.com"]
        assert args.host_network
        assert set(installed) == {signal.SIGINT, signal.SIGTERM}
        installed[signal.SIGTERM](signal.SIGTERM, None)
        assert stop.is_set()
        raise StackStopped

    monkeypatch.setattr(e2e_stack, "run", interrupted)
    e2e_stack.main(
        [
            "--mail-port",
            "47832",
            "--data-dir",
            str(tmp_path),
            "--host-network",
            "--imported-admin",
            "a@example.com",
            "--imported-admin",
            "b@example.com",
        ]
    )


# --- caixa de entrada ---


def test_fake_smtp_requires_starttls_and_login(smtp_server):
    smtp_server.send(_message("ana@example.com"))

    [received] = smtp_server.received
    assert received.tls
    assert received.authenticated


def test_mailbox_lists_the_emails_of_an_address(smtp_server):
    smtp_server.send(_message("Ana@Example.com", "primeiro"))
    smtp_server.send(_message("bia@example.com", "outro"))
    smtp_server.send(_message("ana@example.com", "segundo"))
    mailbox = mailbox_server(smtp_server, 0)
    port = mailbox.server_address[1]
    thread = threading.Thread(target=mailbox.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _get(port, "/emails?to=ANA%40example.com")
        health = _get(port, "/health")
        missing_to = _get(port, "/emails")
        other_path = _get(port, "/outra?to=ana%40example.com")
        nobody = _get(port, "/emails?to=caio%40example.com")
    finally:
        mailbox.shutdown()
        mailbox.server_close()
        thread.join(timeout=5)

    assert status == 200
    assert body == [
        {"to": ["Ana@Example.com"], "subject": "primeiro", "text": "Código: 123456\n"},
        {"to": ["ana@example.com"], "subject": "segundo", "text": "Código: 123456\n"},
    ]
    assert health == (200, {"status": "ok"})
    assert missing_to[0] == 404
    assert other_path[0] == 404
    assert nobody == (200, [])
