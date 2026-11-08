"""Primitivas de segurança do login por código, das sessões e das contas.

O banco guarda só o sha256 do código de login e do token de sessão, nunca o valor em claro.
Nenhuma função daqui loga: o valor em claro só sai de `generate_code` e `generate_token`, para
quem vai mandá-lo por email ou gravá-lo no cookie.
"""

import hashlib
import hmac
import secrets

from app.models import MAX_ACCOUNT_ID

CODE_DIGITS = 6
TOKEN_BYTES = 32


def generate_code() -> str:
    """Gera o código de login: 6 dígitos aleatórios, com zeros à esquerda."""
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def generate_token() -> str:
    """Gera o token de sessão: 32 bytes aleatórios em base64 para URL (43 caracteres)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def generate_account_id() -> int:
    """Sorteia o id de uma conta nova: inteiro de 1 a 2^53 - 1, nunca sequencial.

    Cabe num `Number` do javascript. Um id sequencial voltaria a ser dado a uma conta nova depois
    de restaurar um backup do imago, e a pessoa nova veria os dados de outra nas aplicações. Quem
    cria a conta confere se o id já existe e sorteia outro.
    """
    return secrets.randbelow(MAX_ACCOUNT_ID) + 1


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
