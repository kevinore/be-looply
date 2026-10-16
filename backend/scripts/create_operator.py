"""Create an operator (11.1). Connects with MIGRATION_DATABASE_URL:

uv run --env-file .env python -m scripts.create_operator
"""

import getpass
import os
import sys

import psycopg
from argon2 import PasswordHasher

MIN_PASSWORD_LENGTH = 12
ROLES = ("owner", "operator")


def create_operator(
    conn: psycopg.Connection,
    *,
    business_slug: str,
    email: str,
    name: str,
    role: str,
    password: str,
):
    """Insert the operator and return its id. Stores only the argon2 hash."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must have at least {MIN_PASSWORD_LENGTH} characters"
        )
    row = conn.execute(
        "SELECT id FROM business WHERE slug = %s", (business_slug,)
    ).fetchone()
    if row is None:
        raise ValueError(f"business {business_slug!r} not found")
    return conn.execute(
        "INSERT INTO operator (business_id, email, name, password_hash, role) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (
            row[0],
            email.strip().lower(),
            name.strip(),
            PasswordHasher().hash(password),
            role,
        ),
    ).fetchone()[0]


def ask_password() -> str:
    password = getpass.getpass("Password (min 12 characters): ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    return password


def main() -> None:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        sys.exit("MIGRATION_DATABASE_URL is not set")
    business_slug = input("Business slug: ").strip()
    email = input("Email: ").strip()
    name = input("Name: ").strip()
    role = input(f"Role {ROLES}: ").strip()
    password = ask_password()
    try:
        with psycopg.connect(url) as conn:
            operator_id = create_operator(
                conn,
                business_slug=business_slug,
                email=email,
                name=name,
                role=role,
                password=password,
            )
    except (ValueError, psycopg.errors.UniqueViolation) as exc:
        sys.exit(f"Error: {exc}")
    print(f"Operator created: {operator_id}")


if __name__ == "__main__":
    main()
