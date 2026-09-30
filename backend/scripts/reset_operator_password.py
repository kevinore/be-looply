"""Reset an operator's password and revoke all their sessions (11.1).

uv run --env-file .env python -m scripts.reset_operator_password
"""

import os
import sys

import psycopg
from argon2 import PasswordHasher

from scripts.create_operator import MIN_PASSWORD_LENGTH, ask_password


def reset_operator_password(
    conn: psycopg.Connection, *, email: str, password: str
) -> int:
    """Update the hash and revoke all sessions. Returns how many sessions were revoked."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must have at least {MIN_PASSWORD_LENGTH} characters"
        )
    row = conn.execute(
        "UPDATE operator SET password_hash = %s WHERE email = %s RETURNING id",
        (PasswordHasher().hash(password), email.strip().lower()),
    ).fetchone()
    if row is None:
        raise ValueError(f"operator {email!r} not found")
    return conn.execute(
        "UPDATE operator_session SET revoked_at = now() "
        "WHERE operator_id = %s AND revoked_at IS NULL",
        (row[0],),
    ).rowcount


def main() -> None:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        sys.exit("MIGRATION_DATABASE_URL is not set")
    email = input("Email: ").strip()
    password = ask_password()
    try:
        with psycopg.connect(url) as conn:
            revoked = reset_operator_password(conn, email=email, password=password)
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    print(f"Password updated. Sessions revoked: {revoked}")


if __name__ == "__main__":
    main()
