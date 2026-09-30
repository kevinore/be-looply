"""Create the app_runtime role with SQL (fix for Neon, see below) and apply its grants.

On Neon, roles created from the Console join `neon_superuser`, which inherits
pg_write_all_data (DELETE on every table, UPDATE on events). That breaks R19/R20.
Roles created with SQL by neondb_owner do not. So:

1. Delete app_runtime in Neon Console (Branches -> <branch> -> Roles).
2. Run, with the env file of that branch:

    uv run --env-file .env python -m scripts.create_runtime_role .env

It generates a random password, writes it into DATABASE_URL of the given env file
(never printed), and re-applies migration 0003_grants.

3. Restart the branch compute (Neon Console -> Branches -> <branch> -> Computes ->
   Restart). Until then the pooler keeps connections of the deleted role and fails
   with "invalid role OID".
4. Run check_grants: all checks must pass through the pooled DATABASE_URL.
"""

import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql

ROLE = "app_runtime"
BACKEND_DIR = Path(__file__).resolve().parent.parent


def inherited_roles(conn: psycopg.Connection, role: str) -> list[str] | None:
    """None if the role does not exist; otherwise the roles it is a member of."""
    if not conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone():
        return None
    return [
        r
        for (r,) in conn.execute(
            "SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
            "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = %s",
            (role,),
        )
    ]


def with_password(url: str, password: str) -> str:
    """Same URL (host, pooler, params), new password for the same user."""
    parts = urlsplit(url)
    if parts.username != ROLE:
        raise SystemExit(f"DATABASE_URL user is {parts.username!r}, expected {ROLE!r}")
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    netloc = f"{parts.username}:{quote(password, safe='')}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def write_database_url(env_file: Path, new_url: str) -> None:
    lines = env_file.read_text().splitlines()
    pattern = re.compile(r"^DATABASE_URL=")
    if not any(pattern.match(line) for line in lines):
        raise SystemExit(f"No DATABASE_URL line in {env_file}")
    env_file.write_text(
        "\n".join(
            f"DATABASE_URL={new_url}" if pattern.match(line) else line for line in lines
        )
        + "\n"
    )


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m scripts.create_runtime_role <env-file>")
    env_file = Path(sys.argv[1])
    owner_url = os.environ.get("MIGRATION_DATABASE_URL")
    runtime_url = os.environ.get("DATABASE_URL")
    if not owner_url or not runtime_url:
        sys.exit("MIGRATION_DATABASE_URL and DATABASE_URL must be set")

    password = secrets.token_urlsafe(32)
    with psycopg.connect(owner_url, autocommit=True) as conn:
        roles = inherited_roles(conn, ROLE)
        if roles is not None:
            if roles:
                sys.exit(
                    f"{ROLE} exists and inherits {roles}. Delete it in Neon Console "
                    "(Branches -> this branch -> Roles) and run this again."
                )
            sys.exit(f"{ROLE} already exists and is clean. Nothing to do.")
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(ROLE), sql.Literal(password)
            )
        )
        print(f"Role {ROLE} created with SQL (no inherited roles).")

    # Re-apply 0003_grants to the new role, with our own migration.
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    command.downgrade(config, "0002_views")
    command.upgrade(config, "head")
    print("Grants re-applied (0003_grants).")

    write_database_url(env_file, with_password(runtime_url, password))
    print(f"New password written to DATABASE_URL in {env_file} (not shown).")
    print("Next: uv run --env-file <env-file> python -m scripts.check_grants")


if __name__ == "__main__":
    main()
