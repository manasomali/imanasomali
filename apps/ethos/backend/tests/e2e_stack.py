"""Backend do E2E (Playwright, `apps/ethos/frontend/e2e/`): banco novo, SMTP falso e a API.

PENDENTE (ETH-64): o login passou para o imago, e o E2E precisa do imago e do nginx de dev
(`apps/imago/dev/`) na frente desta API; o ethos não fala mais com SMTP. Até o E2E ser refeito,
este script só sobe as peças que já existiam, com a config nova do ethos.

Sobe, num processo só:

1. um banco SQLite novo em `--data-dir`, migrado pelo Alembic (`upgrade head`), como o deploy;
2. o servidor SMTP falso dos testes (`tests/fake_smtp.py`), com STARTTLS e login obrigatórios,
   como o provedor, com o certificado de uma CA de teste (`trustme`);
3. a caixa de entrada do SMTP falso por HTTP, só em 127.0.0.1: `GET /emails?to=<endereço>` devolve
   `[{"to": [...], "subject": "...", "text": "..."}]`, na ordem de chegada;
4. a API pelo uvicorn, com `--root-path /api/ethos` como em produção, chamando o imago em
   `IMAGO_INTERNAL_URL` com o `INTERNAL_API_TOKEN` de dev.

Uso, na pasta do backend (o `playwright.config.js` do front faz isso):

    uv run --frozen python -m tests.e2e_stack --api-port 47831 --mail-port 47832 \\
        --app-url http://127.0.0.1:47830/ethos --data-dir ../frontend/e2e/.stack

`--data-dir` é apagado e recriado a cada subida (só se estiver vazio ou tiver sido criado por este
script, com o arquivo `.ethos-e2e`). Nada disso vai para produção: `tests/` não sobe para a VM.
"""

import argparse
import json
import os
import shutil
import threading
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import trustme
import uvicorn
from alembic import command
from alembic.config import Config

from tests.fake_smtp import FakeSmtpServer, ReceivedEmail, start_fake_smtp

HOST = "127.0.0.1"
BACKEND_DIR = Path(__file__).resolve().parents[1]
# O mesmo prefixo de produção (o nginx tira, o uvicorn recebe no --root-path)
ROOT_PATH = "/api/ethos"
# Marca a pasta como criada por este script: só ela pode ser apagada na subida seguinte
MARKER = ".ethos-e2e"
# O imago de dev (apps/imago/dev/) e o token do ethos nele (o mesmo IMAGO_APP_TOKENS do imago)
IMAGO_INTERNAL_URL = "http://127.0.0.1:3003"
INTERNAL_API_TOKEN = "dev-only-ethos-token-not-a-secret-0000"  # noqa: S105 (só dev)


class StackError(RuntimeError):
    """Argumento inválido; a mensagem diz o que corrigir."""


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


def stack_environment(*, app_url: str, data_dir: Path) -> dict[str, str]:
    """As variáveis do app (as mesmas de produção)."""
    return {
        "APP_ENV": "dev",
        "APP_URL": app_url,
        "DATABASE_PATH": str(data_dir / "app.db"),
        "IMAGO_INTERNAL_URL": IMAGO_INTERNAL_URL,
        "INTERNAL_API_TOKEN": INTERNAL_API_TOKEN,
    }


def migrate(database_path: Path) -> None:
    """`alembic upgrade head` no banco, como o `ExecStartPre` da unit em produção."""
    config = Config(BACKEND_DIR / "alembic.ini")
    config.attributes["database_path"] = database_path
    command.upgrade(config, "head")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-port", type=int, required=True)
    parser.add_argument("--mail-port", type=int, required=True)
    parser.add_argument("--app-url", required=True, help="origem do front + /ethos")
    parser.add_argument("--data-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    data_dir = prepare_data_dir(args.data_dir)
    smtp, stop_smtp = start_fake_smtp(trustme.CA())
    try:
        os.environ.update(stack_environment(app_url=args.app_url, data_dir=data_dir))
        migrate(data_dir / "app.db")
        mailbox = mailbox_server(smtp, args.mail_port)
        thread = threading.Thread(target=mailbox.serve_forever, daemon=True)
        thread.start()
        try:
            # O uvicorn trata SIGINT e SIGTERM e volta daqui, para a limpeza abaixo rodar
            uvicorn.run(
                "app.main:app",
                host=HOST,
                port=args.api_port,
                root_path=ROOT_PATH,
                app_dir=str(BACKEND_DIR),
                access_log=False,
            )
        finally:
            mailbox.shutdown()
            mailbox.server_close()
    finally:
        stop_smtp()
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except StackError as exc:
        raise SystemExit(f"erro: {exc}") from None
