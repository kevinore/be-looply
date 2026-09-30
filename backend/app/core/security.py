import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Response

from app.core.config import settings

OPERATOR_COOKIE = "op_session"
OPERATOR_SESSION_DAYS = 30
CUSTOMER_COOKIE = "c_session"
CUSTOMER_SESSION_DAYS = 365

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Only this hash is stored in the database."""
    return hashlib.sha256(token.encode()).hexdigest()


def set_session_cookie(response: Response, name: str, token: str, max_age: int) -> None:
    # No `domain`: the cookie belongs to the frontend domain, which proxies the API.
    response.set_cookie(
        key=name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, name: str) -> None:
    response.delete_cookie(
        key=name,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
