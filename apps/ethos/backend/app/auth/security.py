"""Primitivas de segurança do login por código e das sessões.

O banco guarda só o sha256 do código de login e do token de sessão, nunca o valor
em claro. Nenhuma função daqui loga: o valor em claro só sai de generate_code e
generate_token, para quem vai mandá-lo por email ou gravá-lo no cookie.
"""

import hashlib
import hmac
import secrets

CODE_DIGITS = 6
TOKEN_BYTES = 32


def generate_code() -> str:
    """Gera o código de login: 6 dígitos aleatórios, com zeros à esquerda."""
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def generate_token() -> str:
    """Gera o token de sessão: 32 bytes aleatórios em base64 para URL (43 caracteres)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def _to_bytes(value: str) -> bytes:
    # surrogatepass: um surrogate solto (possível num JSON com "\ud800") vira bytes
    # em vez de levantar UnicodeEncodeError; o resultado continua determinístico
    return value.encode("utf-8", "surrogatepass")


def hash_secret(value: str) -> str:
    """Devolve o sha256 do valor em hexadecimal (64 caracteres), o que vai para o banco."""
    return hashlib.sha256(_to_bytes(value)).hexdigest()


def verify_secret(value: str, expected_hash: str) -> bool:
    """Diz se o sha256 do valor é igual ao hash guardado, em tempo constante.

    Compara bytes, e não str, porque hmac.compare_digest recusa str com caracteres
    fora do ASCII. Hash de outro tamanho só dá False.
    """
    return hmac.compare_digest(_to_bytes(hash_secret(value)), _to_bytes(expected_hash))
