import pytest
from starlette.requests import Request

from app.request_info import client_ip, client_user_agent


def make_request(client=None, headers=()) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(name.encode(), value.encode()) for name, value in headers],
        "client": client,
    }
    return Request(scope)


@pytest.mark.parametrize(
    ("client", "expected"),
    [
        (("203.0.113.7", 1), "203.0.113.7"),
        (("2001:DB8::1", 1), "2001:db8::1"),
        (("::ffff:198.51.100.2", 1), "198.51.100.2"),
        (("testclient", 1), None),
        (("", 1), None),
        (None, None),
        # Com zona e longo demais para a coluna (45)
        (("fe80::1%" + "x" * 50, 1), None),
    ],
)
def test_client_ip(client, expected):
    assert client_ip(make_request(client)) == expected


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ((("user-agent", "Firefox/140"),), "Firefox/140"),
        ((("user-agent", "  "),), None),
        ((), None),
        ((("user-agent", "a" * 600),), "a" * 512),
    ],
)
def test_client_user_agent(headers, expected):
    assert client_user_agent(make_request(headers=headers)) == expected


def test_forwarded_headers_are_not_read_here():
    # Quem resolve o X-Forwarded-For é o uvicorn (--proxy-headers), só para o nginx local
    request = make_request(
        ("127.0.0.1", 1), headers=(("x-forwarded-for", "1.2.3.4"), ("x-real-ip", "1.2.3.4"))
    )
    assert client_ip(request) == "127.0.0.1"
