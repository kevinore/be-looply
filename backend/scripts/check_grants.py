"""Check that app_runtime cannot delete data nor edit events (R19, R20).

Connects with DATABASE_URL (app_runtime). Every attempt runs inside a transaction
that is always rolled back, so it is safe against production:

    uv run --env-file .env python -m scripts.check_grants
"""

import os
import sys

import psycopg

TABLES = [
    "business",
    "operator",
    "operator_session",
    "product",
    "workday",
    "customer",
    "customer_session",
    "sale",
    "prize_catalog",
    "spin",
    "prize_award",
    "sale_item",
    "event",
]

# (label, statement). Every one of them must be denied.
CHECKS = [(f"DELETE {t}", f"DELETE FROM {t} WHERE false") for t in TABLES] + [
    ("UPDATE event", "UPDATE event SET type = type WHERE false"),
    ("TRUNCATE event", "TRUNCATE event"),
    ("CREATE TABLE", "CREATE TABLE check_grants_probe (id int)"),
]


def check_grants(url: str) -> list[tuple[str, bool]]:
    """Returns (label, denied) for each check. Nothing is ever committed."""
    results = []
    with psycopg.connect(url, autocommit=True) as conn:
        user = conn.execute("SELECT current_user").fetchone()[0]
        if user != "app_runtime":
            raise SystemExit(f"Connected as {user!r}, expected 'app_runtime'")
        # Sanity check: the role can read.
        conn.execute("SELECT count(*) FROM business").fetchone()
        for label, sql in CHECKS:
            denied = False
            try:
                with conn.transaction(force_rollback=True):
                    conn.execute(sql)
            except psycopg.errors.InsufficientPrivilege:
                denied = True
            results.append((label, denied))
    return results


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    results = check_grants(url)
    for label, denied in results:
        print(
            f"{'OK  ' if denied else 'FAIL'} {label}: "
            f"{'permiso denegado' if denied else 'PERMITIDO'}"
        )
    if not all(denied for _, denied in results):
        sys.exit("app_runtime has privileges it must not have")
    print("All checks passed: app_runtime cannot delete data nor edit events.")


if __name__ == "__main__":
    main()
