import hashlib

from app.core.security import hash_password, hash_token, new_token, verify_password


def test_hash_token_is_sha256_hex():
    assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()
    assert len(hash_token(new_token())) == 64


def test_new_token_is_random():
    assert new_token() != new_token()


def test_password_roundtrip():
    h = hash_password("correct horse battery")
    assert h.startswith("$argon2")
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "not-a-hash")
