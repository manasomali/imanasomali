"""Tamanho máximo do corpo (`app/body_limit.py`)."""

import asyncio
import json

import pytest

from app.body_limit import MAX_BODY_BYTES, BodyLimitMiddleware
from tests.internal_helpers import ETHOS_TOKEN, bearer

VALIDATION_ERROR = {"error": "validation_error", "field": None}


def call(headers: list[tuple[bytes, bytes]], *, scope_type: str = "http") -> tuple[int, bytes]:
    """Roda o middleware com um app que responde 200; devolve o status e o corpo."""
    sent: list[dict] = []

    async def downstream(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {"type": scope_type, "method": "POST", "path": "/x", "headers": headers}
    asyncio.run(BodyLimitMiddleware(downstream)(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"content-length", b"0")],
        [(b"content-length", str(MAX_BODY_BYTES).encode())],
        # Repetido com o mesmo valor: o mesmo corpo
        [(b"content-length", b"10"), (b"content-length", b"10")],
        [(b"content-length", b" 10 ")],
    ],
)
def test_allowed(headers):
    assert call(headers) == (200, b"ok")


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", str(MAX_BODY_BYTES + 1).encode())],
        [(b"content-length", b"10"), (b"content-length", b"11")],
        [(b"content-length", b"-1")],
        [(b"content-length", b"1e3")],
        [(b"content-length", b"")],
        [(b"content-length", b"9" * 5000)],
        [(b"transfer-encoding", b"chunked")],
        [(b"transfer-encoding", b"chunked"), (b"content-length", b"10")],
    ],
)
def test_refused(headers):
    status, body = call(headers)

    assert status == 422
    assert json.loads(body) == VALIDATION_ERROR


def test_other_scopes_pass_through():
    assert call([(b"content-length", b"999999999")], scope_type="websocket")[0] == 200


def test_app_refuses_a_body_over_100_kb(client):
    payload = {
        "kind": "notification",
        "user_id": 1,
        "subject": "Assunto",
        "text": "x" * MAX_BODY_BYTES,
        "html": "<p>x</p>",
    }

    response = client.post("/internal/mail", json=payload, headers=bearer(ETHOS_TOKEN))

    assert response.status_code == 422
    assert response.json() == VALIDATION_ERROR
