import hashlib
import re

import pytest

from app.auth import security
from app.auth.security import generate_code, generate_token, hash_secret, verify_secret


@pytest.mark.parametrize(
    ("drawn", "expected"),
    [(42, "000042"), (0, "000000"), (999_999, "999999"), (123_456, "123456")],
)
def test_generate_code_always_has_six_digits(monkeypatch, drawn, expected):
    calls = []

    def fake_randbelow(limit):
        calls.append(limit)
        return drawn

    monkeypatch.setattr(security.secrets, "randbelow", fake_randbelow)

    assert generate_code() == expected
    assert calls == [10**6]


def test_generate_code_without_mock_is_six_digits():
    for _ in range(100):
        assert re.fullmatch(r"\d{6}", generate_code())


def test_generate_token_uses_token_urlsafe_with_32_bytes(monkeypatch):
    calls = []

    def fake_token_urlsafe(nbytes):
        calls.append(nbytes)
        return "token"

    monkeypatch.setattr(security.secrets, "token_urlsafe", fake_token_urlsafe)

    assert generate_token() == "token"
    assert calls == [32]


def test_generate_token_is_urlsafe_and_unique():
    tokens = {generate_token() for _ in range(100)}

    assert len(tokens) == 100
    for token in tokens:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)


def test_hash_secret_is_sha256_hex():
    # Vetor de teste do FIPS 180-2
    assert hash_secret("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert hash_secret("123456") == hashlib.sha256(b"123456").hexdigest()


def test_hash_secret_is_deterministic():
    assert hash_secret("000042") == hash_secret("000042")


def test_hash_secret_differs_for_different_values():
    assert hash_secret("000042") != hash_secret("000043")
    assert hash_secret("") != hash_secret(" ")


@pytest.mark.parametrize(
    "value",
    ["", "ção", "\ud800", "x" * 100_000],
    ids=["empty", "non-ascii", "lone-surrogate", "huge"],
)
def test_hash_secret_handles_extreme_values(value):
    digest = hash_secret(value)

    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert verify_secret(value, digest)


def test_verify_secret_accepts_matching_hash():
    assert verify_secret("000042", hash_secret("000042")) is True


def test_verify_secret_rejects_wrong_hash():
    assert verify_secret("000042", hash_secret("000043")) is False


@pytest.mark.parametrize(
    "stored",
    ["", "abc", hash_secret("000042")[:-1], hash_secret("000042") + "0"],
    ids=["empty", "short", "one-less", "one-more"],
)
def test_verify_secret_rejects_hash_of_other_length(stored):
    assert verify_secret("000042", stored) is False


def test_verify_secret_rejects_non_ascii_hash_without_raising():
    assert verify_secret("000042", "ç" * 64) is False


def test_verify_secret_is_case_sensitive():
    # O banco guarda o hexdigest em minúsculas; outra grafia não é o mesmo hash
    assert verify_secret("abc", hash_secret("abc").upper()) is False


def test_verify_secret_uses_compare_digest(monkeypatch):
    calls = []

    def fake_compare_digest(a, b):
        calls.append((a, b))
        return True

    monkeypatch.setattr(security.hmac, "compare_digest", fake_compare_digest)

    assert verify_secret("000042", "stored") is True
    assert calls == [(hash_secret("000042").encode(), b"stored")]
