"""Upstreams falsos do .github/scripts/test-nginx-auth.sh, em 127.0.0.1.

    upstreams.py imago <porta> <arquivo>   o imago: GET /internal/session responde 200, com os
                                           X-User-* da conta do cookie __Host-imago_session
                                           (nenhum se o cookie falta ou não é de uma conta) e grava
                                           em <arquivo> o método e os headers que recebeu. O resto
                                           ecoa, como a aplicação
    upstreams.py echo <porta>...           uma aplicação: responde 200 com o método, o caminho e os
                                           headers recebidos (nomes em minúsculas), um por linha
"""

import http.cookies
import http.server
import sys
import threading

COOKIE = "__Host-imago_session"
# Contas do imago falso, pelo valor do cookie: uma admin e uma comum (sem X-User-Admin)
ACCOUNTS = {
    "admin": {
        "X-User-Id": "42",
        "X-User-Email": "ana@example.com",
        "X-User-Locale": "pt",
        "X-User-Timezone": "America/Sao_Paulo",
        "X-User-Admin": "1",
    },
    "comum": {
        "X-User-Id": "43",
        "X-User-Email": "bia@example.com",
        "X-User-Locale": "en",
        "X-User-Timezone": "Europe/Lisbon",
    },
}


def received(handler):
    lines = [f"{handler.command} {handler.path}"]
    lines += [f"{name.lower()}: {value}" for name, value in handler.headers.items()]
    return "\n".join(lines) + "\n"


class Echo(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def echo(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = received(self).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = echo

    def log_message(self, *args):
        pass


class Imago(Echo):
    record = None

    def session_account(self):
        jar = http.cookies.SimpleCookie()
        for header in self.headers.get_all("Cookie") or []:
            try:
                jar.load(header)
            except http.cookies.CookieError:
                continue
        morsel = jar.get(COOKIE)
        return ACCOUNTS.get(morsel.value) if morsel else None

    def do_GET(self):
        if self.path != "/internal/session":
            self.echo()
            return
        with open(self.record, "w", encoding="utf-8") as f:
            f.write(received(self))
        self.send_response(200)
        for name, value in (self.session_account() or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self.end_headers()


def serve(handler, port):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def main(argv):
    if len(argv) == 3 and argv[0] == "imago":
        Imago.record = argv[2]
        threads = [serve(Imago, int(argv[1]))]
    elif len(argv) >= 2 and argv[0] == "echo":
        threads = [serve(Echo, int(port)) for port in argv[1:]]
    else:
        sys.exit(__doc__)
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main(sys.argv[1:])
