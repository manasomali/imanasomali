"""Dados do cliente que vão para o `audit_log` e para `sessions`: IP e User-Agent.

O IP é o `request.client.host`, nunca um header lido aqui. Premissa (infra/apps/ethos): o
uvicorn escuta só em 127.0.0.1, atrás do nginx, e roda com
`--proxy-headers --forwarded-allow-ips=127.0.0.1`. O nginx manda
`X-Forwarded-For: $proxy_add_x_forwarded_for` (o que o cliente mandou + `$remote_addr` no fim), e
o uvicorn lê a lista da direita para a esquerda, pulando só os proxies confiáveis (127.0.0.1):
o primeiro endereço não confiável é o `$remote_addr` que o nginx viu. O que o cliente forja no
começo da lista é ignorado. Sem o nginx na frente (dev), o IP é o da conexão.

O valor nunca vai para o log do app (`app/logs.py`).
"""

import ipaddress

from fastapi import Request

from app.models import IP_MAX_LENGTH, USER_AGENT_MAX_LENGTH


def client_ip(request: Request) -> str | None:
    """IP do cliente normalizado (IPv4 mapeado em IPv6 vira IPv4), ou None se não for um IP."""
    host = request.client.host if request.client else None
    if not host:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Ex.: "testclient" do TestClient, ou um socket Unix
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    normalized = str(address)
    # IPv6 com zona (fe80::1%eth0) pode passar do tamanho da coluna
    return normalized if len(normalized) <= IP_MAX_LENGTH else None


def client_user_agent(request: Request) -> str | None:
    """User-Agent cortado no tamanho da coluna (`sessions.user_agent`), ou None se vazio."""
    value = request.headers.get("user-agent", "").strip()
    return value[:USER_AGENT_MAX_LENGTH] or None
